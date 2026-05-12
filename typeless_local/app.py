"""Standalone Typeless-style macOS app coordinator."""

from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
import logging
import math
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from typing import Literal

from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
import numpy as np
from PyObjCTools import AppHelper

from typeless_local import app_version
from typeless_local.asr import JarvisASR
from typeless_local.audio import MicrophoneRecorder
from typeless_local.config import AppConfig, load_config
from typeless_local.mac_integration import (
    FocusContext,
    GlobalHotkeyMonitor,
    capture_focus_context,
    has_accessibility_trust,
    paste_text,
    request_accessibility_trust,
    set_clipboard_text,
)
from typeless_local.overlay import FloatingOverlay
from typeless_local.refine import TextRefiner
from typeless_local.trace import DictationTrace, SessionRecord
from typeless_local.vocab import as_initial_prompt, load_vocab, write_starter_file

LOGGER = logging.getLogger(__name__)
Mode = Literal["tap", "hands_free"]
DOUBLE_CLICK_SECONDS = 0.4
LONG_PRESS_SECONDS = 0.6
COUNTDOWN_BUFFER_SECONDS = 60.0
MIN_MIC_STARTUP_SECONDS = 0.75
PROCESSING_PROGRESS_POINTS = (
    (0.0, 0.0),
    (1.0, 0.80),
    (2.0, 0.90),
    (3.0, 0.95),
    (4.0, 0.97),
    (5.0, 0.98),
    (10.0, 0.99),
)


class TypelessLocalApp:
    """Coordinate hotkeys, recording, ASR, refinement, UI, and insertion."""

    def __init__(self, config: AppConfig, headless: bool = False) -> None:
        self.config = config
        self.headless = headless

        # Vocab + trace are file-backed and cheap; load them before components
        # so _build_components-injected fakes see a fully initialized app shell.
        user_paths = getattr(config, "user_paths", None)
        if user_paths is not None:
            write_starter_file(user_paths.vocab_path)
            self.vocab = load_vocab(user_paths.vocab_path)
            self.trace = DictationTrace(user_paths.trace_db_path)
        else:
            self.vocab = []
            self.trace = None

        components = self._build_components()
        self.asr = components.asr
        self.refiner = components.refiner
        self.recorder = components.recorder

        if not headless:
            self.overlay = FloatingOverlay.alloc().init()
            self.overlay.set_action_callback(self._on_overlay_action)
            from core.media_ducking import SystemAudioDucker

            self.audio_ducker = SystemAudioDucker.from_config(config.jarvis_config)
            atexit.register(self.audio_ducker.restore_all)
            self.hotkeys = GlobalHotkeyMonitor(
                self._on_hotkey,
                debug_hotkey=config.debug_hotkey,
                is_active_fn=lambda: self.state != "idle",
            )

            from typeless_local.menubar import MenuBarIcon
            from AppKit import NSApp

            self.menubar = MenuBarIcon(
                on_reload_vocab=self.reload_vocab,
                on_quit=lambda: NSApp().terminate_(None),
                trace_folder=user_paths.config_dir if user_paths else None,
                log_path=user_paths.log_path if user_paths else None,
            )
        else:
            self.overlay = None
            self.audio_ducker = None
            self.hotkeys = None
            self.menubar = None

        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="typeless-local")
        self.state = "idle"
        self._set_menubar("idle")
        self.mode: Mode = "tap"
        self.focus_context = FocusContext(app_name="", window_title="", selected_text="")
        self._copy_fallback_text = ""
        self._lock = threading.RLock()
        self._processing_started_at = 0.0
        self._processing_message = "Thinking"
        self._processing_timer: threading.Timer | None = None
        self._recording_timer: threading.Timer | None = None
        self._countdown_timer: threading.Timer | None = None
        self._finish_debounce_timer: threading.Timer | None = None
        self._recording_started_at = 0.0
        self._countdown_text = ""
        self._primary_down_at = 0.0
        self._last_short_tap_at = 0.0
        self._active_session_id = 0

    def _build_components(self) -> SimpleNamespace:
        """Construct ASR / refiner / recorder. Patched by tests to inject fakes."""

        config = self.config
        asr = JarvisASR(config.jarvis_root, config.jarvis_config)
        refiner = TextRefiner(config.refine)
        recorder = MicrophoneRecorder(
            sample_rate=config.sample_rate,
            on_level=self._on_audio_level,
        )
        return SimpleNamespace(asr=asr, refiner=refiner, recorder=recorder)

    def reload_vocab(self) -> None:
        """Atomically replace ``self.vocab`` with a freshly loaded list."""

        user_paths = getattr(self.config, "user_paths", None)
        if user_paths is None:
            return
        self.vocab = load_vocab(user_paths.vocab_path)
        LOGGER.info("Reloaded vocab: %d terms", len(self.vocab))

    def _set_menubar(self, state: str) -> None:
        """Update the menu-bar status icon. No-op when menubar is unavailable."""

        if getattr(self, "headless", False):
            return
        mb = getattr(self, "menubar", None)
        if mb is not None:
            mb.set_state(state)

    def start(self) -> None:
        """Start the app."""

        self.overlay.setup()
        self._call_ui(self.overlay.hide)
        if not has_accessibility_trust():
            LOGGER.warning("Accessibility permission is not granted; Fn capture/paste may fail.")
            request_accessibility_trust()
        menubar = getattr(self, "menubar", None)
        if menubar is not None:
            menubar.setup()
            menubar.set_state("idle")
        try:
            self.hotkeys.start()
        except RuntimeError:
            LOGGER.exception("Failed to install global hotkey monitor")
            self._set_menubar("error")
            self._call_ui(self.overlay.show_error, "Enable Access")
            return
        LOGGER.info("Typeless Local ready. Press F5 to start/stop dictation.")

    def _on_hotkey(self, action: str) -> None:
        with self._lock:
            if action == "cancel":
                self._cancel()
                return
            if action == "hands_free":
                if self.state == "idle":
                    self._start_recording("hands_free")
                elif self.state == "recording" and self.mode == "tap":
                    self.mode = "hands_free"
                    self._show_recording_ui()
                elif self.state == "recording" and self.mode == "hands_free":
                    self._finish_recording()
                return
            if action == "primary_down":
                self._on_primary_down()
                return
            if action == "primary_up":
                self._on_primary_up()
                return
            if action == "primary":
                if self.state == "idle":
                    self._start_recording("tap")
                elif self.state == "recording":
                    self._finish_recording()

    def _on_primary_down(self) -> None:
        # Use the event-generation time captured by the hotkey monitor, not
        # time.monotonic() here. Handler time is unreliable: _start_recording
        # blocks the runloop briefly while the mic opens, so KeyUp can wait in
        # the queue and look like a long press, misfiring hold-to-talk.
        now = self.hotkeys.last_primary_down_at
        self._primary_down_at = now
        gap = now - getattr(self, "_last_short_tap_at", 0.0)
        LOGGER.info("HOTKEY-DEBUG primary_down now=%.3f last_short_tap=%.3f gap=%.3f state=%s mode=%s", now, getattr(self, "_last_short_tap_at", 0.0), gap, self.state, self.mode)
        if gap <= DOUBLE_CLICK_SECONDS:
            if self.state == "idle":
                self._start_recording("hands_free")
            elif self.state == "recording":
                self.mode = "hands_free"
                self._show_recording_ui()
            return

        if self.state == "idle":
            self._start_recording("tap")
        elif self.state == "recording" and self.mode == "tap":
            self._finish_recording()
        elif self.state == "recording" and self.mode == "hands_free":
            self._finish_recording()

    def _on_primary_up(self) -> None:
        if self.state != "recording" or self.mode != "tap":
            return

        up_at = self.hotkeys.last_primary_up_at
        held_for = up_at - getattr(self, "_primary_down_at", 0.0)
        LOGGER.info("HOTKEY-DEBUG primary_up up_at=%.3f down_at=%.3f held_for=%.3f", up_at, getattr(self, "_primary_down_at", 0.0), held_for)
        if held_for < LONG_PRESS_SECONDS:
            self._last_short_tap_at = up_at
            return

        self._finish_recording()

    def _on_overlay_action(self, action: str) -> None:
        with self._lock:
            if action == "primary" and self.state == "idle":
                self._start_recording("tap")
            elif action == "cancel":
                self._cancel()
            elif action == "finish" and self.state == "recording":
                self._finish_recording()
            elif action == "copy-fallback":
                self._copy_last_transcript()
            elif action == "dismiss":
                self.state = "idle"
                self._set_menubar("idle")
                self._copy_fallback_text = ""
                self._call_ui(self.overlay.hide)

    def _start_recording(self, mode: Mode) -> None:
        self._active_session_id = getattr(self, "_active_session_id", 0) + 1
        self.mode = mode
        self.state = "starting"
        self._set_menubar("starting")
        self._recording_started_at = time.monotonic()
        self._countdown_text = ""
        self.focus_context = capture_focus_context()
        self._call_ui(self.overlay.show_starting)
        self.audio_ducker.duck()
        try:
            self.recorder.start()
        except Exception:
            LOGGER.exception("Failed to start microphone")
            self._restore_audio_ducking()
            self.state = "idle"
            self._set_menubar("error")
            self._call_ui(self.overlay.show_error, "Mic error")
            return
        self.state = "recording"
        self._set_menubar("recording")
        self._show_recording_ui()
        self._start_recording_timeout()

    def _finish_recording(self) -> None:
        if self.state != "recording":
            return
        if self._defer_finish_until_microphone_ready():
            return
        self._cancel_recording_timeout()
        session_id = getattr(self, "_active_session_id", 0)
        self.state = "processing"
        self._set_menubar("processing")
        try:
            audio = self.recorder.stop()
        except Exception:
            LOGGER.exception("Failed to stop microphone")
            self._restore_audio_ducking()
            self.state = "idle"
            self._set_menubar("error")
            self._call_ui(self.overlay.show_error, "Mic error")
            return
        self._restore_audio_ducking()
        self._processing_started_at = time.monotonic()
        self._processing_message = "Thinking"
        self._call_ui(self.overlay.show_thinking, progress=0.0, message=self._processing_message)
        self._start_processing_progress()
        future = self.executor.submit(self._process_audio, audio, self.focus_context, session_id)
        future.add_done_callback(self._log_processing_done)

    def _cancel(self) -> None:
        self._active_session_id = getattr(self, "_active_session_id", 0) + 1
        self._cancel_recording_timeout()
        self._stop_processing_progress()
        if self.state == "recording":
            try:
                self.recorder.stop()
            except Exception:
                LOGGER.exception("Failed to stop microphone during cancel")
        self._restore_audio_ducking()
        self.state = "idle"
        self._set_menubar("idle")
        self._call_ui(self.overlay.hide)

    def _restore_audio_ducking(self) -> None:
        restore_all = getattr(self.audio_ducker, "restore_all", None)
        if restore_all is not None:
            restore_all()
        else:
            self.audio_ducker.restore()

    def _start_recording_timeout(self) -> None:
        self._cancel_recording_timeout()
        max_seconds = float(getattr(self.config, "max_recording_seconds", 0.0) or 0.0)
        if max_seconds <= 0:
            return
        self._recording_timer = threading.Timer(max_seconds, self._finish_recording_after_timeout)
        self._recording_timer.daemon = True
        self._recording_timer.start()
        self._start_recording_countdown()

    def _cancel_recording_timeout(self) -> None:
        recording_timer = getattr(self, "_recording_timer", None)
        if recording_timer is not None:
            recording_timer.cancel()
            self._recording_timer = None
        countdown_timer = getattr(self, "_countdown_timer", None)
        if countdown_timer is not None:
            countdown_timer.cancel()
            self._countdown_timer = None
        finish_timer = getattr(self, "_finish_debounce_timer", None)
        if finish_timer is not None:
            finish_timer.cancel()
            self._finish_debounce_timer = None
        self._countdown_text = ""

    def _defer_finish_until_microphone_ready(self) -> bool:
        if getattr(self.recorder, "chunk_count", 1) > 0:
            return False
        elapsed = float(getattr(self.recorder, "elapsed", 0.0) or 0.0)
        min_seconds = max(float(getattr(self.config, "min_recording_seconds", 0.0) or 0.0), MIN_MIC_STARTUP_SECONDS)
        if elapsed <= 0.0 or elapsed >= min_seconds:
            return False
        if getattr(self, "_finish_debounce_timer", None) is not None:
            return True
        delay = max(0.05, min_seconds - elapsed)
        LOGGER.info("Deferring finish %.2fs until microphone input delivers audio", delay)
        timer = threading.Timer(delay, self._finish_recording_after_startup_delay)
        timer.daemon = True
        self._finish_debounce_timer = timer
        timer.start()
        return True

    def _finish_recording_after_startup_delay(self) -> None:
        with self._lock:
            self._finish_debounce_timer = None
            if self.state == "recording":
                self._finish_recording()

    def _show_recording_ui(self) -> None:
        self._call_ui(
            self.overlay.show_recording,
            hands_free=self.mode == "hands_free",
            countdown_text=getattr(self, "_countdown_text", ""),
        )

    def _start_recording_countdown(self) -> None:
        self._schedule_countdown_tick(0.25)

    def _schedule_countdown_tick(self, delay: float) -> None:
        timer = threading.Timer(delay, self._update_recording_countdown)
        timer.daemon = True
        self._countdown_timer = timer
        timer.start()

    def _update_recording_countdown(self) -> None:
        with self._lock:
            if self.state != "recording":
                return
            max_seconds = float(getattr(self.config, "max_recording_seconds", 0.0) or 0.0)
            if max_seconds <= 0:
                return
            elapsed = time.monotonic() - getattr(self, "_recording_started_at", time.monotonic())
            remaining = max(0.0, max_seconds - elapsed)
            next_text = self._format_countdown(remaining) if remaining <= COUNTDOWN_BUFFER_SECONDS else ""
            if next_text != getattr(self, "_countdown_text", ""):
                self._countdown_text = next_text
                self._show_recording_ui()
            if remaining > 0:
                next_delay = 0.25 if remaining <= COUNTDOWN_BUFFER_SECONDS + 1 else min(5.0, remaining - COUNTDOWN_BUFFER_SECONDS)
                self._schedule_countdown_tick(max(0.25, next_delay))

    def _format_countdown(self, remaining: float) -> str:
        total_seconds = max(0, int(math.ceil(remaining)))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def _finish_recording_after_timeout(self) -> None:
        with self._lock:
            if self.state == "recording":
                LOGGER.info("Maximum recording duration reached; finishing dictation.")
                self._finish_recording()

    def _process_audio(self, audio: np.ndarray, context: FocusContext, session_id: int | None = None) -> None:
        session_id = getattr(self, "_active_session_id", 0) if session_id is None else session_id
        headless = bool(getattr(self, "headless", False))
        started = time.time()

        sample_rate = int(getattr(self.config, "sample_rate", 16000))
        try:
            audio_rms = float(self.recorder.get_volume_level(audio))
        except Exception:
            audio_rms = 0.0
        refine_model = ""
        refine_cfg = getattr(self.config, "refine", None)
        if refine_cfg is not None:
            refine_model = str(getattr(refine_cfg, "model", "") or "")

        record = SessionRecord(
            started_at=started,
            audio_duration_s=(audio.size / sample_rate) if sample_rate else 0.0,
            audio_rms=audio_rms,
            audio_sample_rate=sample_rate,
            focus_app=context.app_name or "",
            focus_window=context.window_title or "",
            vocab_terms_used=", ".join(getattr(self, "vocab", []) or []),
            hotwords_count=len(getattr(self, "vocab", []) or []),
            asr_model=str(getattr(self.asr, "model_name", "") or ""),
            refine_model=refine_model,
            app_version=app_version(),
        )

        try:
            LOGGER.info("Processing %.2fs audio", audio.size / sample_rate if sample_rate else 0.0)
            quality_ok, quality_message = self.recorder.is_quality_ok(
                audio,
                min_duration=float(getattr(self.config, "min_recording_seconds", 0.25)),
                low_volume_threshold=float(getattr(self.config, "low_volume_threshold", 0.02)),
            )
            if not quality_ok:
                LOGGER.info("Dropping low-quality audio before ASR: %s", quality_message)
                record.error = f"dropped: {quality_message}"
                if not headless:
                    self._show_empty_then_idle(session_id)
                return

            if not headless and not self._is_current_processing_session(session_id):
                return
            self._set_processing_message("Thinking")
            LOGGER.info("Starting ASR")

            asr_start = time.monotonic()
            vocab_terms = getattr(self, "vocab", []) or []
            transcript = self.asr.transcribe(
                audio, initial_prompt=as_initial_prompt(vocab_terms) or None
            )
            record.raw_asr_text = transcript.text
            record.raw_asr_language = transcript.language
            record.raw_asr_confidence = float(getattr(transcript, "confidence", 0.0) or 0.0)
            record.latency_asr_ms = int((time.monotonic() - asr_start) * 1000)
            LOGGER.info(
                "ASR result language=%s confidence=%.2f text=%r",
                transcript.language,
                transcript.confidence,
                transcript.text,
            )
            if self._should_drop_transcript(transcript):
                record.error = "dropped: empty/short transcript"
                if not headless:
                    self._show_empty_then_idle(session_id)
                return

            if not headless and not self._is_current_processing_session(session_id):
                return
            self._set_processing_message("Thinking")
            LOGGER.info("Starting refinement")
            refine_start = time.monotonic()
            refined = self.refiner.refine(transcript.text, context, vocab=vocab_terms)
            record.refined_text = refined.text or transcript.text
            record.latency_refine_ms = int((time.monotonic() - refine_start) * 1000)
            final_text = record.refined_text

            if headless:
                return  # tests stop here; no overlay/paste path

            if not self._is_current_processing_session(session_id):
                return
            self._stop_processing_progress()
            self._call_ui(self.overlay.show_thinking, progress=1.0, message="Thinking")
            if context.can_insert_text:
                LOGGER.info("Pasting refined text into focused app: %s", context.app_name or "unknown")
                paste_text(final_text)
                record.was_pasted = True
                LOGGER.info("Dictation inserted %d characters", len(final_text))
                self.state = "idle"
                self._set_menubar("idle")
                self._copy_fallback_text = ""
                self._call_ui(self.overlay.hide)
                return

            LOGGER.info(
                "Focused target is not editable (app=%s role=%s); showing copy fallback",
                context.app_name or "unknown",
                context.focused_role or "unknown",
            )
            self._copy_fallback_text = final_text
            self.state = "idle"
            self._set_menubar("idle")
            self._call_ui(self.overlay.show_copy_fallback, final_text, False)
        except Exception as exc:
            record.error = repr(exc)
            LOGGER.exception("Dictation failed")
            if not headless:
                self._stop_processing_progress()
                self.state = "idle"
                self._set_menubar("error")
                self._call_ui(self.overlay.show_error, "Retry")
                time.sleep(1.4)
                self._call_ui(self.overlay.hide)
                return
            raise
        finally:
            record.ended_at = time.time()
            record.latency_total_ms = int((record.ended_at - started) * 1000)
            trace = getattr(self, "trace", None)
            if trace is not None:
                trace.log(record)

    def _start_processing_progress(self) -> None:
        self._stop_processing_progress()
        self._schedule_processing_tick(0.1)

    def _schedule_processing_tick(self, delay: float) -> None:
        timer = threading.Timer(delay, self._update_processing_progress)
        timer.daemon = True
        self._processing_timer = timer
        timer.start()

    def _stop_processing_progress(self) -> None:
        timer = getattr(self, "_processing_timer", None)
        if timer is not None:
            timer.cancel()
            self._processing_timer = None

    def _update_processing_progress(self) -> None:
        with self._lock:
            if self.state != "processing":
                return
            progress = self._processing_progress_at(
                time.monotonic() - getattr(self, "_processing_started_at", time.monotonic())
            )
            self._call_ui(
                self.overlay.show_thinking,
                progress=progress,
                message=getattr(self, "_processing_message", "Thinking"),
            )
            self._schedule_processing_tick(0.1)

    def _processing_progress_at(self, elapsed: float) -> float:
        points = PROCESSING_PROGRESS_POINTS
        if elapsed <= points[0][0]:
            return points[0][1]
        for index in range(1, len(points)):
            prev_time, prev_progress = points[index - 1]
            next_time, next_progress = points[index]
            if elapsed <= next_time:
                span = next_time - prev_time
                if span <= 0:
                    return next_progress
                fraction = (elapsed - prev_time) / span
                return prev_progress + (next_progress - prev_progress) * fraction
        return points[-1][1]

    def _set_processing_message(self, message: str) -> None:
        self._processing_message = message

    def _is_current_processing_session(self, session_id: int) -> bool:
        return self.state == "processing" and session_id == getattr(self, "_active_session_id", 0)

    def _should_drop_transcript(self, transcript) -> bool:
        text = str(getattr(transcript, "text", "") or "").strip()
        if not text:
            return True
        language = str(getattr(transcript, "language", "") or "").lower()
        if language and language != "zh" and len(text) <= 5:
            LOGGER.info("Dropping short non-zh ASR fragment: lang=%s text=%r", language, text)
            return True
        return False

    def _show_empty_then_idle(self, session_id: int | None = None) -> None:
        session_id = getattr(self, "_active_session_id", 0) if session_id is None else session_id
        if not self._is_current_processing_session(session_id):
            return
        self._stop_processing_progress()
        self.state = "idle"
        self._set_menubar("idle")
        self._call_ui(self.overlay.show_empty)
        time.sleep(1.0)
        if self.state == "idle" and session_id == getattr(self, "_active_session_id", 0):
            self._call_ui(self.overlay.hide)

    def _copy_last_transcript(self) -> None:
        text = getattr(self, "_copy_fallback_text", "")
        if not text:
            return
        set_clipboard_text(text)
        self._call_ui(self.overlay.show_copy_fallback, text, True)

    def _on_audio_level(self, level: float) -> None:
        if self.state == "recording":
            self._call_ui(self.overlay.update_level, level)

    def _call_ui(self, callback, *args, **kwargs) -> None:
        if threading.current_thread() is threading.main_thread():
            callback(*args, **kwargs)
        else:
            AppHelper.callAfter(callback, *args, **kwargs)

    def _log_processing_done(self, future) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("Processing worker crashed")


def configure_logging() -> None:
    """Configure process logging."""

    from logging.handlers import RotatingFileHandler

    level_name = os.environ.get("TYPELESS_LOCAL_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir = Path.home() / ".typeless-local"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "app.log"
        handlers.append(
            RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5)
        )
    except Exception:
        pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def main() -> None:
    """Run the macOS app."""

    configure_logging()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    coordinator = TypelessLocalApp(load_config())
    coordinator.start()
    app.run()
