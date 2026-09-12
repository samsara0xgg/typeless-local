from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np

from typeless_local.app import TypelessLocalApp
from typeless_local.asr import Transcript
from typeless_local.mac_integration import FocusContext
from typeless_local.refine import RefineResult


class _FakeOverlay:
    def __init__(self) -> None:
        self.calls = []

    def setup(self) -> None:
        self.calls.append(("setup",))

    def hide(self) -> None:
        self.calls.append(("hide",))

    def show_idle_base(self) -> None:
        self.calls.append(("idle-base",))

    def show_thinking(self, progress=0.0, message="Thinking") -> None:
        self.calls.append(("thinking", progress, message))

    def show_hover(self) -> None:
        self.calls.append(("hover",))

    def show_starting(self) -> None:
        self.calls.append(("starting",))

    def show_empty(self) -> None:
        self.calls.append(("empty",))

    def show_error(self, message: str) -> None:
        self.calls.append(("error", message))

    def show_recording(self, hands_free: bool = False, countdown_text: str = "") -> None:
        self.calls.append(("recording", hands_free, countdown_text))

    def show_copy_fallback(self, transcript: str, copied: bool = False) -> None:
        self.calls.append(("copy-fallback", transcript, copied))


class _FakeASR:
    def __init__(self, text: str, language: str = "en", confidence: float = 0.9) -> None:
        self.text = text
        self.language = language
        self.confidence = confidence
        self.calls = []

    def transcribe(self, audio: np.ndarray, initial_prompt: str | None = None) -> Transcript:
        self.calls.append(audio)
        return Transcript(text=self.text, language=self.language, confidence=self.confidence)


class _FakeRefiner:
    def __init__(self) -> None:
        self.calls = []

    def refine(self, text: str, context: FocusContext, vocab=None) -> RefineResult:
        self.calls.append((text, context))
        return RefineResult(text="Refined text.", raw_text=text, model="gpt-5.4-mini")


class _FailingHotkeys:
    def start(self) -> None:
        raise RuntimeError("no accessibility")


class _FakeHotkeys:
    """Mimics GlobalHotkeyMonitor's event-time fields used by _on_primary_*."""

    def __init__(self) -> None:
        self.last_primary_down_at = 0.0
        self.last_primary_up_at = 0.0

    def start(self) -> None:
        return None


class _FakeRecorder:
    def __init__(self) -> None:
        self.stopped = False
        self.started = False
        self.fail_start = False
        self.fail_stop = False
        self.elapsed = 1.0
        self.chunk_count = 1

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("mic unavailable")
        self.started = True

    def stop(self) -> np.ndarray:
        if self.fail_stop:
            raise RuntimeError("mic stop failed")
        self.stopped = True
        return np.ones(16000, dtype=np.float32)

    def is_quality_ok(self, audio, *, min_duration, low_volume_threshold):
        duration_seconds = audio.size / 16000
        volume = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64))) if audio.size else 0.0
        if audio.size == 0 or duration_seconds < min_duration or volume < low_volume_threshold:
            return False, "low quality"
        return True, "ok"


class _FakeExecutor:
    def __init__(self) -> None:
        self.submissions = []

    def submit(self, fn, *args):
        self.submissions.append((fn, args))
        return SimpleNamespace(add_done_callback=lambda callback: None)


class _FakeDucker:
    def __init__(self) -> None:
        self.calls = []

    def duck(self) -> bool:
        self.calls.append("duck")
        return True

    def restore(self) -> None:
        self.calls.append("restore")

    def restore_all(self) -> None:
        self.calls.append("restore_all")


def _make_app(raw_text: str) -> TypelessLocalApp:
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, low_volume_threshold=0.02)
    app.overlay = _FakeOverlay()
    app.asr = _FakeASR(raw_text)
    app.refiner = _FakeRefiner()
    app.recorder = _FakeRecorder()
    app.state = "processing"
    app._copy_fallback_text = ""
    return app


def test_process_audio_transcribes_refines_and_pastes(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    app = _make_app("raw dictation")
    context = FocusContext(app_name="TextEdit", window_title="Untitled", can_insert_text=True)

    app._process_audio(np.ones(16000, dtype=np.float32), context)

    assert app.asr.calls
    assert app.refiner.calls == [("raw dictation", context)]
    assert pasted == ["Refined text."]
    assert app.overlay.calls[-1] == ("hide",)


def test_process_audio_shows_copy_fallback_when_focus_is_not_editable(monkeypatch) -> None:
    """With nowhere to paste, the text still lands on the clipboard by itself.

    It used to wait for a click on the overlay's Copy button, so a dictation
    aimed at a non-editable target was one missed click away from being lost.
    """

    pasted = []
    copied = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", copied.append)
    app = _make_app("raw dictation")
    context = FocusContext(app_name="Finder", window_title="Desktop", focused_role="AXGroup")

    app._process_audio(np.ones(16000, dtype=np.float32), context)

    assert pasted == []
    assert copied == ["Refined text."]
    assert app._copy_fallback_text == "Refined text."
    assert app.overlay.calls[-1] == ("copy-fallback", "Refined text.", True)


def test_copy_fallback_action_sets_clipboard_and_marks_copied(monkeypatch) -> None:
    copied = []
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", copied.append)
    app = _make_app("raw dictation")
    app._copy_fallback_text = "Refined text."

    app._copy_last_transcript()

    assert copied == ["Refined text."]
    assert app.overlay.calls[-1] == ("copy-fallback", "Refined text.", True)


def test_process_audio_empty_transcript_does_not_paste(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    monkeypatch.setattr("typeless_local.app.time.sleep", lambda seconds: None)
    app = _make_app("")

    app._process_audio(np.ones(16000, dtype=np.float32), FocusContext("", ""))

    assert pasted == []
    assert ("empty",) in app.overlay.calls


def test_process_audio_drops_low_quality_audio_before_asr(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    monkeypatch.setattr("typeless_local.app.time.sleep", lambda seconds: None)
    app = _make_app("hallucinated prior")

    app._process_audio(np.zeros(16000, dtype=np.float32), FocusContext("", ""))

    assert app.asr.calls == []
    assert pasted == []
    assert ("empty",) in app.overlay.calls


def test_process_audio_drops_short_non_zh_fragment(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    monkeypatch.setattr("typeless_local.app.time.sleep", lambda seconds: None)
    app = _make_app("you")
    app.asr = _FakeASR("you", language="en", confidence=0.31)

    app._process_audio(np.ones(16000, dtype=np.float32), FocusContext("", ""))

    assert app.asr.calls
    assert app.refiner.calls == []
    assert pasted == []
    assert ("empty",) in app.overlay.calls


def test_hands_free_hotkey_upgrades_active_tap_recording() -> None:
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app.state = "recording"
    app.mode = "tap"
    app.overlay = _FakeOverlay()

    app._on_hotkey("hands_free")

    assert app.mode == "hands_free"
    assert app.overlay.calls == [("recording", True, "")]


def test_start_shows_permission_state_when_hotkey_install_fails(monkeypatch) -> None:
    monkeypatch.setattr("typeless_local.app.has_accessibility_trust", lambda: False)
    monkeypatch.setattr("typeless_local.app.request_accessibility_trust", lambda: False)
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app.overlay = _FakeOverlay()
    app.hotkeys = _FailingHotkeys()

    app.start()

    assert app.overlay.calls == [("setup",), ("hide",), ("error", "Enable Access")]


def test_recording_timeout_finishes_and_submits_processing() -> None:
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app._recording_timer = None
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25)
    app.state = "recording"
    app.overlay = _FakeOverlay()
    app.recorder = _FakeRecorder()
    app.audio_ducker = _FakeDucker()
    app.executor = _FakeExecutor()
    app.focus_context = FocusContext(app_name="TextEdit", window_title="Untitled")
    app._start_processing_progress = lambda: None

    app._finish_recording_after_timeout()

    assert app.state == "processing"
    assert app.recorder.stopped is True
    assert app.audio_ducker.calls == ["restore_all"]
    assert app.overlay.calls == [("thinking", 0.0, "Thinking")]
    assert app.executor.submissions[0][0] == app._process_audio


def test_recording_ducks_system_audio_until_finish(monkeypatch) -> None:
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda: FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app._recording_timer = None
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, max_recording_seconds=0)
    app.state = "idle"
    app.mode = "tap"
    app.overlay = _FakeOverlay()
    app.recorder = _FakeRecorder()
    app.audio_ducker = _FakeDucker()
    app.executor = _FakeExecutor()
    app._start_processing_progress = lambda: None

    app._start_recording("tap")
    app._finish_recording()

    assert app.audio_ducker.calls == ["duck", "restore_all"]
    assert app.recorder.started is True
    assert app.recorder.stopped is True


def test_recording_restores_audio_when_microphone_start_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda: FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._recording_timer = None
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, max_recording_seconds=0)
    app.state = "idle"
    app.overlay = _FakeOverlay()
    app.recorder = _FakeRecorder()
    app.recorder.fail_start = True
    app.audio_ducker = _FakeDucker()

    app._start_recording("tap")

    assert app.state == "idle"
    assert app.audio_ducker.calls == ["duck", "restore_all"]
    assert ("error", "Mic error") in app.overlay.calls


def test_recording_restores_audio_when_microphone_stop_fails() -> None:
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app._recording_timer = None
    app._countdown_timer = None
    app._finish_debounce_timer = None
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, max_recording_seconds=0)
    app.state = "recording"
    app.overlay = _FakeOverlay()
    app.recorder = _FakeRecorder()
    app.recorder.fail_stop = True
    app.audio_ducker = _FakeDucker()
    app.executor = _FakeExecutor()
    app.focus_context = FocusContext(app_name="TextEdit", window_title="Untitled")

    app._finish_recording()

    assert app.state == "idle"
    assert app.audio_ducker.calls == ["restore_all"]
    assert app.executor.submissions == []
    assert ("error", "Mic error") in app.overlay.calls


def test_primary_down_up_finishes_hold_to_talk(monkeypatch) -> None:
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda: FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app._recording_timer = None
    app._countdown_timer = None
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, max_recording_seconds=0)
    app.state = "idle"
    app.mode = "tap"
    app.overlay = _FakeOverlay()
    app.recorder = _FakeRecorder()
    app.audio_ducker = _FakeDucker()
    app.executor = _FakeExecutor()
    app.focus_context = FocusContext(app_name="", window_title="")
    app._start_processing_progress = lambda: None

    hotkeys = _FakeHotkeys()
    app.hotkeys = hotkeys
    times = iter([10.0, 10.0, 10.7, 10.7])
    monkeypatch.setattr("typeless_local.app.time.monotonic", lambda: next(times))

    hotkeys.last_primary_down_at = 10.0
    app._on_hotkey("primary_down")
    hotkeys.last_primary_up_at = 10.7
    app._on_hotkey("primary_up")

    assert app.state == "processing"
    assert app.recorder.started is True
    assert app.recorder.stopped is True
    assert app.executor.submissions


def test_short_tap_release_keeps_recording_until_next_press(monkeypatch) -> None:
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda: FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app._recording_timer = None
    app._countdown_timer = None
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, max_recording_seconds=0)
    app.state = "idle"
    app.mode = "tap"
    app.overlay = _FakeOverlay()
    app.recorder = _FakeRecorder()
    app.audio_ducker = _FakeDucker()
    app.executor = _FakeExecutor()
    app.focus_context = FocusContext(app_name="", window_title="")
    app._start_processing_progress = lambda: None

    hotkeys = _FakeHotkeys()
    app.hotkeys = hotkeys
    times = iter([30.0, 30.0, 30.1, 30.1, 31.0, 31.0])
    monkeypatch.setattr("typeless_local.app.time.monotonic", lambda: next(times))

    hotkeys.last_primary_down_at = 30.0
    app._on_hotkey("primary_down")
    hotkeys.last_primary_up_at = 30.1
    app._on_hotkey("primary_up")

    assert app.state == "recording"
    assert app.recorder.stopped is False
    assert app.executor.submissions == []

    hotkeys.last_primary_down_at = 31.0
    app._on_hotkey("primary_down")

    assert app.state == "processing"
    assert app.recorder.stopped is True
    assert app.executor.submissions


def test_short_double_press_upgrades_to_hands_free(monkeypatch) -> None:
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda: FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app._recording_timer = None
    app._countdown_timer = None
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, max_recording_seconds=0)
    app.state = "idle"
    app.mode = "tap"
    app.overlay = _FakeOverlay()
    app.recorder = _FakeRecorder()
    app.audio_ducker = _FakeDucker()
    app.executor = _FakeExecutor()
    app.focus_context = FocusContext(app_name="", window_title="")

    hotkeys = _FakeHotkeys()
    app.hotkeys = hotkeys
    times = iter([20.0, 20.0, 20.08, 20.08, 20.24])
    monkeypatch.setattr("typeless_local.app.time.monotonic", lambda: next(times))

    hotkeys.last_primary_down_at = 20.0
    app._on_hotkey("primary_down")
    hotkeys.last_primary_up_at = 20.08
    app._on_hotkey("primary_up")
    hotkeys.last_primary_down_at = 20.24
    app._on_hotkey("primary_down")

    assert app.state == "recording"
    assert app.mode == "hands_free"
    assert ("recording", True, "") in app.overlay.calls
    assert app.executor.submissions == []


def test_finish_defers_until_microphone_delivers_first_chunk(monkeypatch) -> None:
    timers = []

    class FakeTimer:
        def __init__(self, delay, callback):
            self.delay = delay
            self.callback = callback
            self.daemon = False
            self.cancelled = False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr("typeless_local.app.threading.Timer", FakeTimer)

    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app._recording_timer = None
    app._countdown_timer = None
    app._finish_debounce_timer = None
    app._active_session_id = 1
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, max_recording_seconds=0)
    app.state = "recording"
    app.overlay = _FakeOverlay()
    app.recorder = _FakeRecorder()
    app.recorder.elapsed = 0.40
    app.recorder.chunk_count = 0
    app.audio_ducker = _FakeDucker()
    app.executor = _FakeExecutor()
    app.focus_context = FocusContext(app_name="", window_title="")
    app._start_processing_progress = lambda: None

    app._finish_recording()

    assert app.state == "recording"
    assert app.recorder.stopped is False
    assert app.executor.submissions == []
    assert timers
    assert round(timers[0].delay, 2) == 0.35

    app.recorder.elapsed = 0.80
    timers[0].callback()

    assert app.state == "processing"
    assert app.recorder.stopped is True
    assert app.executor.submissions


def test_stale_empty_result_does_not_hide_new_recording(monkeypatch) -> None:
    app = _make_app("")
    app.state = "processing"
    app._active_session_id = 1

    def start_new_recording(_seconds):
        app._active_session_id = 2
        app.state = "recording"
        app.overlay.show_recording(False, "")

    monkeypatch.setattr("typeless_local.app.time.sleep", start_new_recording)

    app._show_empty_then_idle(session_id=1)

    assert app.state == "recording"
    assert app.overlay.calls == [("empty",), ("recording", False, "")]


def test_processing_progress_curve_matches_typeless_shape() -> None:
    app = TypelessLocalApp.__new__(TypelessLocalApp)

    assert app._processing_progress_at(0.0) == 0.0
    assert app._processing_progress_at(1.0) == 0.80
    assert app._processing_progress_at(2.0) == 0.90
    assert app._processing_progress_at(5.0) == 0.98
    assert app._processing_progress_at(10.0) == 0.99


def test_countdown_formats_last_minute() -> None:
    app = TypelessLocalApp.__new__(TypelessLocalApp)

    assert app._format_countdown(60.0) == "1:00"
    assert app._format_countdown(59.2) == "1:00"
    assert app._format_countdown(58.9) == "0:59"
