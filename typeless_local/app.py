"""Standalone Typeless-style macOS app coordinator."""

from __future__ import annotations

import atexit
import dataclasses
from concurrent.futures import Future, ThreadPoolExecutor
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
from typeless_local.asr import JarvisASR, Transcript, mlx_whisper_repo
from typeless_local.audio import MicrophoneRecorder, keep_recording, peak_level
from typeless_local import devices
from typeless_local.config import (
    AppConfig,
    load_config,
    migrate_legacy_config_dir,
    preset_names,
    refine_config_for,
    save_input_device,
    save_default_preset,
)
from typeless_local.mac_integration import (
    FocusContext,
    GlobalHotkeyMonitor,
    capture_focus_context,
    has_accessibility_trust,
    paste_text,
    request_accessibility_trust,
    set_clipboard_text,
)
from typeless_local.first_run import (
    download_model,
    ensure_api_key,
    model_is_cached,
    set_api_key,
)
from typeless_local.overlay import FloatingOverlay
from typeless_local.refine import MissingAPIKey, RefineResult, TextRefiner
from typeless_local.trace import DictationTrace, SessionRecord, append_correction
from typeless_local.vocab import as_initial_prompt, load_user_terms, load_vocab, write_starter_file

LOGGER = logging.getLogger(__name__)
Mode = Literal["tap", "hands_free"]
DOUBLE_CLICK_SECONDS = 0.4
LONG_PRESS_SECONDS = 0.6
COUNTDOWN_BUFFER_SECONDS = 60.0
MIN_MIC_STARTUP_SECONDS = 0.75
# A non-Chinese transcript this short is usually Whisper inventing a word over
# noise ("you", "Bye."), but it is also how "OK" and "Yes" come out. Whisper's
# own confidence tells them apart: invented words score low.
SHORT_FRAGMENT_CHARS = 5
WHISPER_WINDOW_S = 30
MIN_SHORT_ENGLISH_CONFIDENCE = 0.4
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
            self.whisper_prompt = as_initial_prompt(load_user_terms(user_paths.vocab_path))
            self.trace = DictationTrace(user_paths.trace_db_path)
        else:
            self.vocab = []
            self.whisper_prompt = ""
            self.trace = None

        components = self._build_components()
        self.asr = components.asr
        self.refiner = components.refiner
        self.recorder = components.recorder

        if not headless:
            self.overlay = FloatingOverlay.alloc().init()
            self.overlay.set_action_callback(self._on_overlay_action)
            try:
                from typeless_local._vendor.jarvis_core.media_ducking import SystemAudioDucker
            except ImportError:
                from core.media_ducking import SystemAudioDucker

            self.audio_ducker = SystemAudioDucker.from_config(config.jarvis_config)
            atexit.register(self.audio_ducker.restore_all)
            self.hotkeys = GlobalHotkeyMonitor(
                self._on_hotkey,
                debug_hotkey=config.debug_hotkey,
                is_active_fn=lambda: self.state != "idle",
                wants_return_fn=self._overlay_awaits_return,
            )

            from typeless_local.menubar import MenuBarIcon
            from AppKit import NSApp

            self.menubar = MenuBarIcon(
                on_reload_vocab=self.reload_vocab,
                on_quit=lambda: NSApp().terminate_(None),
                trace_folder=user_paths.config_dir if user_paths else None,
                log_path=user_paths.log_path if user_paths else None,
                presets=preset_names(config.jarvis_config),
                active_preset=config.refine.preset,
                on_select_model=self.select_model,
                input_devices=devices.list_input_devices(),
                output_devices=devices.list_output_devices(),
                active_input=getattr(config, "input_device", "") or devices.current_input_device(),
                active_output=devices.current_output_device(),
                on_select_input=self.select_input_device,
                on_select_output=self.select_output_device,
                on_set_api_key=self.change_api_key,
            )
        else:
            self.overlay = None
            self.audio_ducker = None
            self.hotkeys = None
            self.menubar = None

        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="typeless-local")
        # Muting and unmuting shell out to osascript, which is too slow to run
        # between the hotkey and the microphone opening. One worker keeps every
        # restore behind the duck it undoes.
        self._audio_io = ThreadPoolExecutor(max_workers=1, thread_name_prefix="typeless-audio-io")
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
        self._stretches: list[Future[Transcript]] = []

    def _build_components(self) -> SimpleNamespace:
        """Construct ASR / refiner / recorder. Patched by tests to inject fakes."""

        config = self.config
        asr = JarvisASR(config.jarvis_root, config.jarvis_config)
        refiner = TextRefiner(config.refine)
        recorder = MicrophoneRecorder(
            sample_rate=config.sample_rate,
            on_level=self._on_audio_level,
            device=devices.resolve_input_index(getattr(config, "input_device", "")),
            on_stretch=self._on_stretch,
        )
        return SimpleNamespace(asr=asr, refiner=refiner, recorder=recorder)

    def reload_vocab(self) -> None:
        """Atomically replace ``self.vocab`` with a freshly loaded list."""

        user_paths = getattr(self.config, "user_paths", None)
        if user_paths is None:
            return
        self.vocab = load_vocab(user_paths.vocab_path)
        self.whisper_prompt = as_initial_prompt(load_user_terms(user_paths.vocab_path))
        LOGGER.info("Reloaded vocab: %d terms", len(self.vocab))

    def _select_capture_device(self) -> str:
        """Point the recorder at the preferred mic, or the system default if it is gone.

        Resolved per recording rather than once at launch: the mic gets plugged
        and pulled between dictations, and the answer has to be the device that
        is actually there now. Returns the name being captured with, which is
        what decides whether the speakers still need ducking.
        """

        devices.refresh_if_changed()
        return self._resolve_capture_device()

    def _resolve_capture_device(self) -> str:
        preferred = getattr(self.config, "input_device", "")
        index = devices.resolve_input_index(preferred)
        recorder = getattr(self, "recorder", None)
        if recorder is not None:
            recorder.device = index
        return preferred if index is not None else devices.current_input_device()

    def _speakers_need_ducking(self, capture: str) -> bool:
        """Whether the speakers must be silenced for this capture to stay clean.

        A capture device with hardware echo cancellation already removes what the
        speakers play, but only while it is fed the same signal they get, so the
        answer depends on the input and output pairing rather than on the mic
        alone. Anything unrecognised ducks, which is the behaviour that was there
        before any pairing was configured. ``capture`` is the device actually in
        use, not the configured preference, so falling back to the built-in mic
        ducks even while the paired mic stays configured.
        """

        playback = devices.current_output_device()
        pairs = list(getattr(self.config, "aec_pairs", ()) or ())
        if devices.has_hardware_aec(capture, playback, pairs):
            LOGGER.info(
                "Leaving system audio up: %s + %s cancels the speakers in hardware",
                capture,
                playback,
            )
            return False
        return True

    def select_input_device(self, name: str) -> None:
        """Point capture at ``name`` from the next recording on, and persist it."""

        self.config = dataclasses.replace(self.config, input_device=name)
        recorder = getattr(self, "recorder", None)
        if recorder is not None:
            recorder.device = devices.resolve_input_index(name)
        user_paths = getattr(self.config, "user_paths", None)
        if user_paths is not None:
            save_input_device(user_paths, name)
        menubar = getattr(self, "menubar", None)
        if menubar is not None:
            menubar.set_active_input(name)
        LOGGER.info("Capture device set to %s", name or "(system default)")

    def select_output_device(self, name: str) -> None:
        """Switch the system default output; the menu follows what actually took."""

        devices.set_output_device(name)
        menubar = getattr(self, "menubar", None)
        if menubar is not None:
            menubar.set_active_output(devices.current_output_device())

    def select_model(self, preset: str) -> None:
        """Switch the refinement preset live and persist it to the user config."""

        refine = refine_config_for(self.config.jarvis_config, preset)
        self.config = dataclasses.replace(self.config, refine=refine)
        self.refiner = TextRefiner(refine)
        user_paths = getattr(self.config, "user_paths", None)
        if user_paths is not None:
            save_default_preset(user_paths, preset)
        menubar = getattr(self, "menubar", None)
        if menubar is not None:
            menubar.set_active_preset(preset)
        LOGGER.info("Refinement model switched to %s (%s)", preset, refine.model)

    def _prompt_for_missing_api_key(self) -> None:
        """Ask for the key on first launch, once the app can show a window."""

        user_paths = getattr(self.config, "user_paths", None)
        if user_paths is None:
            return
        ensure_api_key(
            self.config.refine.api_key_env,
            self.config.refine.model,
            user_paths.env_path,
        )

    def change_api_key(self) -> None:
        """Replace the key for the active preset from the menu bar."""

        user_paths = getattr(self.config, "user_paths", None)
        if user_paths is None:
            return
        if set_api_key(
            self.config.refine.api_key_env,
            self.config.refine.model,
            user_paths.env_path,
        ):
            LOGGER.info("%s updated", self.config.refine.api_key_env)

    def _start_model_prefetch(self) -> None:
        """Pull the ASR weights now, with a progress bar, instead of inside the
        first F5 where a 1.5 GB download looks like the app has hung."""

        asr_config = self.config.jarvis_config.get("asr") or {}
        provider = str(asr_config.get("provider") or "").strip().lower()
        repo_id = mlx_whisper_repo(asr_config)
        if provider != "mlx_whisper" or model_is_cached(repo_id):
            self._warm_up_asr()
            return

        def report(fraction: float) -> None:
            self._call_ui(
                self.overlay.show_thinking,
                progress=fraction,
                message="Downloading model",
            )

        def run() -> None:
            try:
                report(0.0)
                download_model(repo_id, report)
                LOGGER.info("ASR model %s is ready", repo_id)
                self._warm_up_asr()
            except Exception:
                # The first dictation will download it the slow way; that is a
                # worse experience, not a broken one, so the app stays up.
                LOGGER.exception("Model prefetch failed for %s", repo_id)
            finally:
                self._call_ui(self.overlay.hide)

        threading.Thread(target=run, daemon=True, name="model-prefetch").start()

    def _warm_up_asr(self) -> None:
        """Load the recognizer in the background before the first dictation.

        Queued on the processing worker so it can never run alongside a real
        transcription; a dictation made meanwhile waits for the load it would
        have had to do anyway.
        """

        warmup = getattr(self.asr, "warmup", None)
        if warmup is not None:
            self.executor.submit(warmup)

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
        self._start_model_prefetch()
        # Deferred onto the run loop: this app is LSUIElement, and before
        # -[NSApplication run] it is not active yet, so a modal alert can open
        # behind whatever the user is looking at or not come up at all.
        AppHelper.callLater(0.3, self._prompt_for_missing_api_key)
        LOGGER.info("Typlus ready. Press F5 to start/stop dictation.")

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
        # A tap cannot land before the one it follows, so a negative gap means
        # the two timestamps came from different clocks rather than that this
        # was a double tap. Treating it as one wedges every later press into
        # the double-tap branch, where a second press only re-renders and never
        # stops the recording, for the life of the process.
        if 0.0 <= gap <= DOUBLE_CLICK_SECONDS:
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
            elif action == "return_pressed":
                self._dismiss_overlay()
            elif action == "edit-focused":
                self._editing = True
                self._cancel_overlay_dismiss()
            elif action == "edit-blurred":
                self._editing = False
            elif action.startswith("edit-live:"):
                # Clipboard only: _copy_fallback_text stays the original so the
                # correction recorded on commit is measured against what the
                # dictation actually produced, not against the last keystroke.
                set_clipboard_text(action[len("edit-live:") :])
            elif action.startswith("edit-commit:"):
                self._commit_edit(action[len("edit-commit:") :])
            elif action == "edit-cancel":
                self._end_edit()
            elif action == "dismiss":
                self.state = "idle"
                self._set_menubar("idle")
                self._copy_fallback_text = ""
                self._call_ui(self.overlay.hide)

    def _schedule_overlay_dismiss(self, delay: float = 8.0) -> None:
        """Take the transcript down after a while if nothing is done with it."""

        self._cancel_overlay_dismiss()
        timer = threading.Timer(delay, self._dismiss_overlay)
        timer.daemon = True
        self._dismiss_timer = timer
        timer.start()

    def _cancel_overlay_dismiss(self) -> None:
        timer = getattr(self, "_dismiss_timer", None)
        if timer is not None:
            timer.cancel()
        self._dismiss_timer = None

    def _dismiss_overlay(self) -> None:
        """Put the transcript away unless it is being edited right now."""

        if getattr(self, "_editing", False) or self.state != "idle":
            return
        self._cancel_overlay_dismiss()
        self._copy_fallback_text = ""
        self._call_ui(self.overlay.hide)

    def _overlay_awaits_return(self) -> bool:
        """Whether a Return in another app should take the transcript down.

        Read from inside the keyboard event tap on every Return press, so it
        stays a couple of attribute reads and never takes a lock.
        """

        return bool(self._copy_fallback_text) and not getattr(self, "_editing", False)

    def _end_edit(self) -> None:
        """Dismiss the field, leaving the clipboard as the transcript left it."""

        self._editing = False
        self._cancel_overlay_dismiss()
        self._call_ui(self.overlay.end_edit)
        self.state = "idle"
        self._set_menubar("idle")
        self._copy_fallback_text = ""
        self._call_ui(self.overlay.hide)

    def _commit_edit(self, text: str) -> None:
        """Take the edited text to the clipboard and record what was changed.

        The field only appears where there was nowhere to paste, so the
        clipboard is the destination and nothing has to be undone first.
        """

        before = getattr(self, "_copy_fallback_text", "")
        corrected = text.strip()
        self._editing = False
        self._cancel_overlay_dismiss()
        self._call_ui(self.overlay.end_edit)
        if corrected:
            set_clipboard_text(corrected)
            if corrected != before:
                user_paths = getattr(self.config, "user_paths", None)
                if user_paths is not None:
                    append_correction(
                        user_paths.corrections_path,
                        getattr(self, "_last_trace_id", None),
                        before,
                        corrected,
                    )
                LOGGER.info(
                    "Correction recorded: %d chars -> %d chars",
                    len(before),
                    len(corrected),
                )
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
        # The microphone opens first: everything that used to come before it
        # (focus probing, re-enumerating devices, two osascript runs to mute)
        # delayed it by enough to lose the first words, and ran inside the
        # keyboard event tap, stalling typing system-wide meanwhile.
        capture = self._select_capture_device()
        self._call_ui(self.overlay.show_starting)
        self._stretches = []
        try:
            capture = self._start_microphone(capture)
        except Exception:
            LOGGER.exception("Failed to start microphone")
            self._restore_audio_ducking()
            self.state = "idle"
            self._set_menubar("error")
            self._call_ui(self.overlay.show_error, "Mic error")
            return
        self.focus_context = capture_focus_context()
        if self._speakers_need_ducking(capture):
            self._run_audio_io(self.audio_ducker.duck)
        self.state = "recording"
        self._set_menubar("recording")
        self._show_recording_ui()
        self._start_recording_timeout()

    def _start_microphone(self, capture: str) -> str:
        """Open the mic; if it fails, re-read the devices once and try again.

        Devices are only re-enumerated when CoreAudio reports a change, so a
        change that slipped past that check surfaces here as a failed open.
        Returns the name of the device actually being captured.
        """

        try:
            self.recorder.start()
            return capture
        except Exception:
            LOGGER.warning("Microphone failed to open; re-reading devices and retrying", exc_info=True)
        devices.refresh()
        capture = self._resolve_capture_device()
        self.recorder.start()
        return capture

    def _run_audio_io(self, job) -> None:
        """Run a system-audio side effect off the hotkey path, in order."""

        executor = getattr(self, "_audio_io", None)
        if executor is None:
            job()
            return
        executor.submit(job)

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
        stretches, self._stretches = getattr(self, "_stretches", []), []
        heard_until = int(getattr(self.recorder, "heard_until", 0))
        future = self.executor.submit(
            self._process_audio, audio, self.focus_context, session_id, stretches, heard_until
        )
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
        for stretch in getattr(self, "_stretches", []):
            stretch.cancel()
        self._stretches = []
        self._restore_audio_ducking()
        self.state = "idle"
        self._set_menubar("idle")
        self._call_ui(self.overlay.hide)

    def _restore_audio_ducking(self) -> None:
        restore_all = getattr(self.audio_ducker, "restore_all", None)
        self._run_audio_io(restore_all if restore_all is not None else self.audio_ducker.restore)

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

    def _on_stretch(self, stretch: np.ndarray) -> None:
        """Audio thread: a stretch cut at his pause is heard now, ahead of the stop."""

        self._stretches.append(self.executor.submit(self._hear, stretch))

    def _hear(self, audio: np.ndarray) -> Transcript:
        """One stretch through Whisper; one too quiet for the recording's own gate is not sent."""

        floor = float(getattr(self.config, "low_volume_threshold", 0.02))
        if peak_level(audio, int(getattr(self.config, "sample_rate", 16000))) < floor:
            return Transcript(text="", language="unknown", confidence=0.0)
        return self._whisper(audio)

    def _whisper(self, audio: np.ndarray) -> Transcript:
        """The user's word list goes into Whisper's prompt only for a chunk that
        fits one 30 s window: across windows it used to loop on longer speech."""

        sample_rate = int(getattr(self.config, "sample_rate", 16000))
        prompt = getattr(self, "whisper_prompt", "") if audio.size <= WHISPER_WINDOW_S * sample_rate else ""
        return self.asr.transcribe(audio, initial_prompt=prompt or None)

    def _process_audio(
        self,
        audio: np.ndarray,
        context: FocusContext,
        session_id: int | None = None,
        stretches: list[Future[Transcript]] | tuple[()] = (),
        heard_until: int = 0,
    ) -> None:
        session_id = getattr(self, "_active_session_id", 0) if session_id is None else session_id
        headless = bool(getattr(self, "headless", False))
        started = time.time()
        missing_api_key = False

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
            if not headless:
                self._prewarm_refiner()
            LOGGER.info("Starting ASR")

            asr_start = time.monotonic()
            vocab_terms = getattr(self, "vocab", []) or []
            # Stretches cut at his pauses were heard while he talked (on this
            # executor, so they are done); only the rest is left. Without a cut the whole recording already passed the quality gate;
            # after one, the rest may be only his closing pause.
            parts = [stretch.result() for stretch in stretches]
            rest = audio[heard_until:]
            parts.append(self._hear(rest) if parts else self._whisper(rest))
            transcript = _join(parts)
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
            try:
                refined = self.refiner.refine(transcript.text, context, vocab=vocab_terms)
            except Exception as exc:
                # The transcript is already in hand; losing the whole dictation
                # because the polish step failed is the worst outcome available.
                LOGGER.exception("Refinement failed; pasting the raw transcript")
                record.error = f"refine failed, pasted raw transcript: {exc!r}"
                refined = RefineResult(
                    text=transcript.text, raw_text=transcript.text, model=refine_model, fallback="error"
                )
                missing_api_key = isinstance(exc, MissingAPIKey)
            else:
                fallback = getattr(refined, "fallback", "")
                if fallback:
                    record.error = f"refine {fallback}, pasted raw transcript"
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
                # paste_text puts the old clipboard back when it is done, so
                # without this a Cmd+V the target app swallowed would leave the
                # text nowhere at all. Keeping it here means one manual paste
                # always recovers it, and makes the panel's "Copied" true.
                set_clipboard_text(final_text)
                LOGGER.info("Dictation inserted %d characters", len(final_text))
                self.state = "idle"
                self._set_menubar("idle")
                self._copy_fallback_text = final_text
                # Shown but not focused: the text is already in the target app
                # and the next key is usually Return there, which dismisses this.
                self._call_ui(self.overlay.show_copy_fallback, final_text, True, False)
                self._schedule_overlay_dismiss()
                if missing_api_key:
                    # Only after the paste: the prompt takes focus, and a Cmd+V
                    # posted after it would land in the key field instead.
                    self._call_ui(self._prompt_for_missing_api_key)
                return

            LOGGER.info(
                "Focused target is not editable (app=%s role=%s); showing copy fallback",
                context.app_name or "unknown",
                context.focused_role or "unknown",
            )
            self._copy_fallback_text = final_text
            set_clipboard_text(final_text)
            self._editing = True
            self.state = "idle"
            self._set_menubar("idle")
            self._call_ui(self.overlay.show_copy_fallback, final_text, True, True)
            if missing_api_key:
                self._call_ui(self._prompt_for_missing_api_key)
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
                self._last_trace_id = trace.log(record)
            self._keep_recording(audio, sample_rate, started)

    def _keep_recording(self, audio: np.ndarray, sample_rate: int, started: float) -> None:
        """Save this dictation's audio, dropped ones included, when configured to."""

        keep = int(getattr(self.config, "keep_recordings", 0) or 0)
        user_paths = getattr(self.config, "user_paths", None)
        if keep <= 0 or user_paths is None:
            return
        # Named by start time plus the trace.db session id it belongs to.
        name = time.strftime("%Y%m%d-%H%M%S", time.localtime(started))
        trace_id = getattr(self, "_last_trace_id", None)
        if trace_id is not None:
            name = f"{name}-{int(trace_id):06d}"
        try:
            keep_recording(user_paths.config_dir / "recordings", name, audio, sample_rate, keep)
        except Exception:
            LOGGER.warning("Could not keep the recording", exc_info=True)

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

    def _prewarm_refiner(self) -> None:
        """Connect to the refinement API while the recognizer is still running."""

        prewarm = getattr(self.refiner, "prewarm", None)
        if prewarm is not None:
            threading.Thread(target=prewarm, daemon=True, name="refine-prewarm").start()

    def _should_drop_transcript(self, transcript) -> bool:
        text = str(getattr(transcript, "text", "") or "").strip()
        if not text:
            return True
        language = str(getattr(transcript, "language", "") or "").lower()
        if language and language != "zh" and len(text) <= SHORT_FRAGMENT_CHARS:
            confidence = float(getattr(transcript, "confidence", 0.0) or 0.0)
            if language == "en" and confidence >= MIN_SHORT_ENGLISH_CONFIDENCE:
                return False
            LOGGER.info(
                "Dropping short non-zh ASR fragment: lang=%s conf=%.2f text=%r",
                language,
                confidence,
                text,
            )
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
        self._call_ui(self.overlay.show_copy_fallback, text, True, True)

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


def _join(parts: list[Transcript]) -> Transcript:
    """The stretches' words in order; language and confidence from the longest one."""

    text = ""
    for part in parts:
        piece = part.text
        if text and piece and _latin(text[-1]) and _latin(piece[0]):
            text += " "
        text += piece
    longest = max(parts, key=lambda part: len(part.text))
    return Transcript(text=text, language=longest.language, confidence=longest.confidence)


def _latin(char: str) -> bool:
    return char.isascii() and char.isalnum()


def configure_logging() -> None:
    """Configure process logging."""

    from logging.handlers import RotatingFileHandler

    level_name = os.environ.get("TYPELESS_LOCAL_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        # Runs before load_config, so it is the first thing to touch the config
        # directory and therefore the one that has to carry the old one over.
        log_dir = migrate_legacy_config_dir()
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
