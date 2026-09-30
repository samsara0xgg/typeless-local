from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import pytest

from typeless_local import app as app_module
from typeless_local.app import Insertion, TypelessLocalApp, count_units
from typeless_local.asr import Transcript
from typeless_local.capsule import Capsule
from typeless_local.mac_integration import FocusContext
from typeless_local.preferences import Preferences
from typeless_local.refine import MissingAPIKey, RefineResult

TARGET_PID = 4242


class _FakeOverlay:
    """Records what the capsule was asked to draw."""

    def __init__(self) -> None:
        self.calls = []

    def setup(self) -> None:
        self.calls.append(("setup",))

    def show(self, state, **data) -> None:
        self.calls.append(("show", state, data))

    def hide(self) -> None:
        self.calls.append(("hide",))

    def end_edit(self) -> None:
        self.calls.append(("end_edit",))

    def update_level(self, level) -> None:
        self.calls.append(("level", level))

    def set_handle(self, on) -> None:
        self.calls.append(("handle", on))

    def set_anchor(self, mode, caret=None) -> None:
        self.calls.append(("anchor", mode, caret))

    def shown(self) -> list[str]:
        return [call[1] for call in self.calls if call[0] == "show"]

    def last(self):
        return [call for call in self.calls if call[0] in ("show", "hide")][-1]


class _ManualTimer:
    """A threading.Timer that only fires when the test says so."""

    made: list["_ManualTimer"] = []

    def __init__(self, delay, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.daemon = False
        self.cancelled = False
        _ManualTimer.made.append(self)

    def start(self) -> None:
        pass

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


def _attach(app) -> _FakeOverlay:
    """Give an app built with __new__ a capsule that draws into a fake overlay."""

    overlay = _FakeOverlay()
    app.overlay = overlay
    app.capsule = Capsule(overlay, lambda fn, *a, **k: fn(*a, **k), timer=_ManualTimer)
    return overlay


@pytest.fixture(autouse=True)
def _mac(monkeypatch):
    """Keep the tests off the real Mac: permissions, the frontmost app, keys."""

    _ManualTimer.made = []
    monkeypatch.setattr(app_module.permissions, "microphone_status", lambda: "authorized")
    monkeypatch.setattr(app_module, "frontmost_pid", lambda: TARGET_PID)
    monkeypatch.setattr(app_module, "caret_rect", lambda: None)
    monkeypatch.setattr(app_module, "undo_last_edit", lambda: None)


class _FakeASR:
    def __init__(self, text: str, language: str = "en", confidence: float = 0.9) -> None:
        self.text = text
        self.language = language
        self.confidence = confidence
        self.calls = []
        self.prompts = []

    def transcribe(self, audio: np.ndarray, initial_prompt: str | None = None) -> Transcript:
        self.calls.append(audio)
        self.prompts.append(initial_prompt)
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
    _attach(app)
    app.asr = _FakeASR(raw_text)
    app.refiner = _FakeRefiner()
    app.recorder = _FakeRecorder()
    app._lock = threading.RLock()
    app.state = "processing"
    app._copy_fallback_text = ""
    return app


def _recording_app() -> TypelessLocalApp:
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app._recording_timer = None
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, max_recording_seconds=0)
    app.state = "idle"
    app.mode = "tap"
    _attach(app)
    app.recorder = _FakeRecorder()
    app.audio_ducker = _FakeDucker()
    app.executor = _FakeExecutor()
    app.focus_context = FocusContext(app_name="", window_title="")
    return app


def test_process_audio_transcribes_refines_and_pastes(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", lambda text: None)
    app = _make_app("raw dictation")
    context = FocusContext(app_name="TextEdit", window_title="Untitled", can_insert_text=True)

    app._process_audio(np.ones(16000, dtype=np.float32), context)

    assert app.asr.calls
    assert app.refiner.calls == [("raw dictation", context)]
    assert pasted == ["Refined text."]
    assert app.overlay.shown() == ["refining", "inserted"]
    assert app.overlay.calls[-1] == ("show", "inserted", {"n": 2, "replaced": False})
    # Until the user types, the capsule can still take the paste back.
    assert app._insertion == Insertion("Refined text.", "raw dictation", TARGET_PID, context)
    assert app._keys_wanted is True
    assert app.state == "idle"


def test_process_audio_joins_stretches_heard_while_talking_with_the_rest(monkeypatch) -> None:
    from concurrent.futures import Future

    monkeypatch.setattr("typeless_local.app.paste_text", lambda _text: None)
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", lambda text: None)
    app = _make_app("the rest")
    heard = Future()
    heard.set_result(Transcript(text="第一段。", language="zh", confidence=0.9))
    audio = np.concatenate([np.full(16000, 0.5, dtype=np.float32), np.ones(8000, dtype=np.float32)])
    context = FocusContext(app_name="TextEdit", window_title="Untitled", can_insert_text=True)

    app._process_audio(audio, context, None, [heard], 16000)

    # Only the part after the cut goes to Whisper; the words join in order.
    (tail,) = app.asr.calls
    assert tail.size == 8000
    assert app.refiner.calls == [("第一段。the rest", context)]


def test_word_list_goes_to_whisper_only_for_chunks_within_one_window() -> None:
    app = _make_app("hi")
    app.whisper_prompt = "Common terms: Jarvis, StarTrial."

    app._hear(np.full(16000 * 10, 0.5, dtype=np.float32))
    app._hear(np.full(16000 * 31, 0.5, dtype=np.float32))

    assert app.asr.prompts == ["Common terms: Jarvis, StarTrial.", None]


def test_process_audio_hands_the_text_over_in_a_card_when_focus_is_not_editable(monkeypatch) -> None:
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
    assert app.overlay.calls[-1] == ("show", "edit-notarget", {"text": "Refined text."})
    assert getattr(app, "_insertion", None) is None


def test_copy_last_transcript_sets_the_clipboard_and_says_so(monkeypatch) -> None:
    copied = []
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", copied.append)
    app = _make_app("raw dictation")
    app._copy_fallback_text = "Refined text."

    app._copy_last_transcript()

    assert copied == ["Refined text."]
    assert app.overlay.calls[-1] == ("show", "copied", {})


def test_process_audio_empty_transcript_does_not_paste(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    app = _make_app("")
    app._capture_device = "MacBook Pro 麦克风"

    app._process_audio(np.ones(16000, dtype=np.float32), FocusContext("", ""))

    assert pasted == []
    assert app.overlay.calls[-1] == ("show", "empty", {"device": "MacBook Pro 麦克风"})
    assert app.state == "idle"


def test_process_audio_drops_low_quality_audio_before_asr(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    app = _make_app("hallucinated prior")

    app._process_audio(np.zeros(16000, dtype=np.float32), FocusContext("", ""))

    assert app.asr.calls == []
    assert pasted == []
    assert app.overlay.shown() == ["empty"]


def test_process_audio_drops_short_non_zh_fragment(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    app = _make_app("you")
    app.asr = _FakeASR("you", language="en", confidence=0.31)

    app._process_audio(np.ones(16000, dtype=np.float32), FocusContext("", ""))

    assert app.asr.calls
    assert app.refiner.calls == []
    assert pasted == []
    assert app.overlay.shown() == ["empty"]


def test_empty_capsule_goes_away_by_itself() -> None:
    app = _make_app("")
    app._process_audio(np.zeros(16000, dtype=np.float32), FocusContext("", ""))

    (timer,) = _ManualTimer.made
    assert timer.delay == 2.4
    timer.fire()

    assert app.overlay.calls[-1] == ("hide",)


def test_hands_free_hotkey_upgrades_active_tap_recording() -> None:
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app.state = "recording"
    app.mode = "tap"
    app.config = SimpleNamespace(max_recording_seconds=540)
    overlay = _attach(app)

    app._on_hotkey("hands_free")

    assert app.mode == "hands_free"
    ((kind, state, data),) = overlay.calls
    assert (kind, state, data["mode"], data["max"]) == ("show", "rec", "latch", 540.0)


def test_start_shows_permission_state_when_hotkey_install_fails(monkeypatch) -> None:
    monkeypatch.setattr("typeless_local.app.has_accessibility_trust", lambda: False)
    monkeypatch.setattr("typeless_local.app.request_accessibility_trust", lambda: False)
    later = []
    monkeypatch.setattr("typeless_local.app.AppHelper.callLater", lambda delay, fn: later.append((delay, fn)))
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    overlay = _attach(app)
    app.hotkeys = _FailingHotkeys()
    app._start_model_prefetch = lambda: None
    app._prime_microphone = lambda: None

    app.start()

    assert overlay.calls == [("setup",), ("handle", True), ("show", "perm", {})]
    retry = [fn for delay, fn in later if fn == app._retry_hotkeys]
    assert retry, "a retry is scheduled while Accessibility is missing"

    # Still missing: it keeps looking.
    later.clear()
    app._retry_hotkeys()
    assert [fn for _, fn in later] == [app._retry_hotkeys]

    # Granted: the tap goes in and the permission capsule goes away.
    app.hotkeys.start = lambda: None
    later.clear()
    app._retry_hotkeys()
    assert later == []
    assert overlay.calls[-1] == ("hide",)


def test_recording_timeout_finishes_and_submits_processing() -> None:
    app = _recording_app()
    app.state = "recording"
    app.focus_context = FocusContext(app_name="TextEdit", window_title="Untitled")

    app._finish_recording_after_timeout()

    assert app.state == "processing"
    assert app.recorder.stopped is True
    assert app.audio_ducker.calls == ["restore_all"]
    assert app.overlay.calls == [("show", "transcribing", {})]
    assert app.executor.submissions[0][0] == app._process_audio


def test_recording_ducks_system_audio_until_finish(monkeypatch) -> None:
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda **_: FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    app = _recording_app()

    app._start_recording("tap")
    app._finish_recording()

    assert app.audio_ducker.calls == ["duck", "restore_all"]
    assert app.recorder.started is True
    assert app.recorder.stopped is True
    assert app.overlay.shown() == ["starting", "rec", "transcribing"]


def test_recording_restores_audio_when_microphone_start_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda **_: FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    app = _recording_app()
    app.recorder.fail_start = True

    app._start_recording("tap")

    # The mic opens before the speakers are muted, so a mic that never opens
    # leaves them alone; the restore on the error path is then a no-op.
    assert app.state == "idle"
    assert app.audio_ducker.calls == ["restore_all"]
    assert app.overlay.calls[-1] == ("show", "mic", {"why": "busy"})


def test_a_denied_microphone_is_reported_instead_of_recording_silence(monkeypatch) -> None:
    monkeypatch.setattr(app_module.permissions, "microphone_status", lambda: "denied")
    app = _recording_app()

    app._start_recording("tap")

    assert app.recorder.started is False
    assert app.state == "idle"
    assert app.overlay.calls == [("show", "mic", {"why": "denied"})]


def test_recording_restores_audio_when_microphone_stop_fails() -> None:
    app = _recording_app()
    app._countdown_timer = None
    app._finish_debounce_timer = None
    app.state = "recording"
    app.recorder.fail_stop = True
    app.focus_context = FocusContext(app_name="TextEdit", window_title="Untitled")

    app._finish_recording()

    assert app.state == "idle"
    assert app.audio_ducker.calls == ["restore_all"]
    assert app.executor.submissions == []
    assert app.overlay.calls[-1] == ("show", "error", {"msg": "麦克风出错"})


def _hotkey_app(monkeypatch):
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda **_: FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    app = _recording_app()
    app._countdown_timer = None
    app.hotkeys = _FakeHotkeys()
    clock = [0.0]
    monkeypatch.setattr("typeless_local.app.time.monotonic", lambda: clock[0])
    return app, app.hotkeys, clock


def test_primary_down_up_finishes_hold_to_talk(monkeypatch) -> None:
    app, hotkeys, clock = _hotkey_app(monkeypatch)

    clock[0] = hotkeys.last_primary_down_at = 10.0
    app._on_hotkey("primary_down")
    clock[0] = hotkeys.last_primary_up_at = 10.7
    app._on_hotkey("primary_up")

    assert app.state == "processing"
    assert app.recorder.started is True
    assert app.recorder.stopped is True
    assert app.executor.submissions
    assert app._hold_timer is None


def test_holding_the_key_switches_the_capsule_to_release_to_finish(monkeypatch) -> None:
    app, hotkeys, clock = _hotkey_app(monkeypatch)
    timers = []
    monkeypatch.setattr(
        "typeless_local.app.threading.Timer",
        lambda delay, callback: timers.append(_ManualTimer(delay, callback)) or timers[-1],
    )

    clock[0] = hotkeys.last_primary_down_at = 10.0
    app._on_hotkey("primary_down")
    (hold,) = [t for t in timers if t.delay == app_module.LONG_PRESS_SECONDS]
    clock[0] = 10.6
    hold.fire()  # still held: no key up since the key down

    assert app.overlay.calls[-1][1] == "rec" and app.overlay.calls[-1][2]["mode"] == "hold"
    assert app.overlay.calls[-1][2]["elapsed"] == 0.6


def test_hold_view_does_not_appear_after_a_quick_tap(monkeypatch) -> None:
    app, hotkeys, clock = _hotkey_app(monkeypatch)
    timers = []
    monkeypatch.setattr(
        "typeless_local.app.threading.Timer",
        lambda delay, callback: timers.append(_ManualTimer(delay, callback)) or timers[-1],
    )

    clock[0] = hotkeys.last_primary_down_at = 20.0
    app._on_hotkey("primary_down")
    clock[0] = hotkeys.last_primary_up_at = 20.1
    app._on_hotkey("primary_up")
    for timer in timers:
        timer.fire()

    assert app.state == "recording"
    assert [call[2]["mode"] for call in app.overlay.calls if call[:2] == ("show", "rec")] == ["click"]


def test_short_tap_release_keeps_recording_until_next_press(monkeypatch) -> None:
    app, hotkeys, clock = _hotkey_app(monkeypatch)

    clock[0] = hotkeys.last_primary_down_at = 30.0
    app._on_hotkey("primary_down")
    clock[0] = hotkeys.last_primary_up_at = 30.1
    app._on_hotkey("primary_up")

    assert app.state == "recording"
    assert app.recorder.stopped is False
    assert app.executor.submissions == []

    clock[0] = hotkeys.last_primary_down_at = 31.0
    app._on_hotkey("primary_down")

    assert app.state == "processing"
    assert app.recorder.stopped is True
    assert app.executor.submissions


def test_short_double_press_upgrades_to_hands_free(monkeypatch) -> None:
    app, hotkeys, clock = _hotkey_app(monkeypatch)

    clock[0] = hotkeys.last_primary_down_at = 20.0
    app._on_hotkey("primary_down")
    clock[0] = hotkeys.last_primary_up_at = 20.08
    app._on_hotkey("primary_up")
    clock[0] = hotkeys.last_primary_down_at = 20.24
    app._on_hotkey("primary_down")

    assert app.state == "recording"
    assert app.mode == "hands_free"
    assert app.overlay.calls[-1][1] == "rec" and app.overlay.calls[-1][2]["mode"] == "latch"
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

    app = _recording_app()
    app._countdown_timer = None
    app._finish_debounce_timer = None
    app._active_session_id = 1
    app.state = "recording"
    app.recorder.elapsed = 0.40
    app.recorder.chunk_count = 0

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


def test_stale_empty_result_does_not_hide_new_recording() -> None:
    app = _make_app("")
    app.state = "processing"
    app._active_session_id = 1

    app._show_empty_then_idle(session_id=1)
    app.capsule.show("rec", mode="click")  # a new dictation starts before "empty" goes away
    for timer in _ManualTimer.made:
        timer.fire()

    assert app.overlay.calls == [("show", "empty", {"device": ""}), ("show", "rec", {"mode": "click"})]


def test_cancel_while_recording_says_so() -> None:
    app = _recording_app()
    app.state = "recording"

    app._cancel()

    assert app.state == "idle"
    assert app.recorder.stopped is True
    assert app.overlay.calls == [("show", "cancelled", {})]
    assert _ManualTimer.made[-1].delay == 0.8


class _FailingRefiner:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def refine(self, text, context, vocab=None):
        raise self.exc


def test_refine_failure_pastes_the_raw_transcript(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", lambda text: None)
    app = _make_app("我们明天下午三点开会")
    app.asr = _FakeASR("我们明天下午三点开会", language="zh")
    app.refiner = _FailingRefiner(TimeoutError("refine timed out"))

    app._process_audio(
        np.ones(16000, dtype=np.float32),
        FocusContext("TextEdit", "Untitled", can_insert_text=True),
    )

    assert pasted == ["我们明天下午三点开会"]
    assert app.overlay.calls[-1] == ("show", "inserted-raw-net", {"why": "timeout"})


def test_missing_key_pastes_raw_and_offers_to_set_one(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", lambda text: None)
    app = _make_app("hello there")
    app.refiner = _FailingRefiner(MissingAPIKey("OPENAI_API_KEY is required"))

    app._process_audio(np.ones(16000, dtype=np.float32), FocusContext("Notes", "", can_insert_text=True))

    assert pasted == ["hello there"]
    assert app.overlay.calls[-1] == ("show", "inserted-raw-key", {})
    assert _ManualTimer.made[-1].delay == 8.0


def test_refinement_switched_off_pastes_the_transcript_as_heard(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", lambda text: None)
    app = _make_app("straight from whisper")
    app.prefs = Preferences(refine=False)

    app._process_audio(np.ones(16000, dtype=np.float32), FocusContext("Notes", "", can_insert_text=True))

    assert app.refiner.calls == []
    assert pasted == ["straight from whisper"]
    assert app.overlay.shown() == ["inserted"]


def test_privacy_settings_limit_what_refinement_sees() -> None:
    app = _make_app("改一下")
    context = FocusContext(
        "Mail", "Re: 报价", selected_text="原来的句子", can_insert_text=True, before_text="王总您好，"
    )

    app.prefs = Preferences(send_before_text=True)
    assert app._refine_context(context) is context
    app.prefs = Preferences(rewrite_selection=False, send_window_title=False, send_before_text=False)
    assert app._refine_context(context) == FocusContext("", "", selected_text="", can_insert_text=True)


def test_short_confident_english_is_kept(monkeypatch) -> None:
    pasted = []
    monkeypatch.setattr("typeless_local.app.paste_text", pasted.append)
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", lambda text: None)
    app = _make_app("OK.")
    app.asr = _FakeASR("OK.", language="en", confidence=0.82)

    app._process_audio(
        np.ones(16000, dtype=np.float32),
        FocusContext("Slack", "#general", can_insert_text=True),
    )

    assert app.refiner.calls
    assert pasted == ["Refined text."]


def test_short_fragment_in_another_language_is_still_dropped() -> None:
    app = _make_app("はい")
    app.asr = _FakeASR("はい", language="ja", confidence=0.9)

    app._process_audio(np.ones(16000, dtype=np.float32), FocusContext("", ""))

    assert app.refiner.calls == []


def _inserted_app(text: str = "Refined text.") -> TypelessLocalApp:
    app = _make_app("raw dictation")
    app.state = "idle"
    app.executor = _FakeExecutor()
    app._active_session_id = 3
    context = FocusContext("TextEdit", "Untitled", can_insert_text=True)
    app._insertion = Insertion(text, "raw dictation", TARGET_PID, context)
    app._keys_wanted = True
    app.capsule.show("inserted", n=2, replaced=False)
    return app


def test_undo_button_takes_the_paste_back_in_the_same_app(monkeypatch) -> None:
    undos = []
    monkeypatch.setattr(app_module, "undo_last_edit", lambda: undos.append("cmd-z"))
    app = _inserted_app()

    app._on_overlay_action("undo")

    assert undos == ["cmd-z"]
    assert app.overlay.calls[-1] == ("show", "undone", {})
    assert app._insertion is None and app._keys_wanted is False


def test_undo_button_refuses_once_another_app_is_in_front(monkeypatch) -> None:
    undos = []
    monkeypatch.setattr(app_module, "undo_last_edit", lambda: undos.append("cmd-z"))
    monkeypatch.setattr(app_module, "frontmost_pid", lambda: 999)
    app = _inserted_app()

    app._on_overlay_action("undo")

    assert undos == []
    assert app.overlay.calls[-1] == ("show", "notice", {"msg": "目标 App 已切换，没法撤销"})


def test_typing_after_the_paste_takes_the_undo_offer_away() -> None:
    app = _inserted_app()

    app._on_hotkey("typed")

    assert app.overlay.calls[-1] == ("hide",)
    assert app._insertion is None and app._keys_wanted is False


def test_the_users_own_cmd_z_is_confirmed() -> None:
    app = _inserted_app()

    app._on_hotkey("undo")

    assert app.overlay.calls[-1] == ("show", "undone", {})
    assert app._insertion is None


def _run_threads_inline(monkeypatch) -> None:
    monkeypatch.setattr(
        "typeless_local.app.threading.Thread",
        lambda target, args=(), **kwargs: SimpleNamespace(start=lambda: target(*args)),
    )
    monkeypatch.setattr("typeless_local.app.time.sleep", lambda seconds: None)


def test_replace_takes_the_paste_back_and_pastes_the_edit(monkeypatch) -> None:
    events = []
    _run_threads_inline(monkeypatch)
    monkeypatch.setattr(app_module, "undo_last_edit", lambda: events.append("cmd-z"))
    monkeypatch.setattr("typeless_local.app.paste_text", lambda text: events.append(("paste", text)))
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", lambda text: None)
    app = _inserted_app()
    app._on_overlay_action("edit")
    assert app.overlay.calls[-1] == ("show", "edit-modify", {"text": "Refined text."})

    app._on_overlay_action("replace", {"text": "  改好的文字 "})

    assert events == ["cmd-z", ("paste", "改好的文字")]
    assert app.overlay.calls[-2:] == [("end_edit",), ("show", "replaced", {"n": 5})]
    assert app._insertion.text == "改好的文字"


def test_replace_after_typing_elsewhere_copies_instead_of_undoing(monkeypatch) -> None:
    events, copied = [], []
    _run_threads_inline(monkeypatch)
    monkeypatch.setattr(app_module, "undo_last_edit", lambda: events.append("cmd-z"))
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", copied.append)
    app = _inserted_app()
    app._on_overlay_action("edit")
    app._on_overlay_action("field", {"focus": False})  # clicked back into the other app
    app._on_hotkey("typed")

    app._on_overlay_action("replace", {"text": "改好的文字"})

    assert events == []
    assert copied == ["改好的文字"]
    assert app.overlay.calls[-1] == ("show", "notice", {"msg": "原文已经改动过，修改后的文字已复制"})


def test_rerefine_replaces_the_raw_paste_with_the_refined_text(monkeypatch) -> None:
    events = []
    _run_threads_inline(monkeypatch)
    monkeypatch.setattr(app_module, "undo_last_edit", lambda: events.append("cmd-z"))
    monkeypatch.setattr("typeless_local.app.paste_text", lambda text: events.append(("paste", text)))
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", lambda text: None)
    app = _inserted_app("raw dictation")
    app.capsule.show("inserted-raw-net", why="timeout")

    app._on_overlay_action("rerefine")
    fn, args = app.executor.submissions[-1]
    fn(*args)

    assert app.refiner.calls[-1][0] == "raw dictation"
    assert events == ["cmd-z", ("paste", "Refined text.")]
    assert app.overlay.shown()[-2:] == ["refining", "replaced"]


def test_rerefine_that_fails_again_leaves_the_raw_text(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(app_module, "undo_last_edit", lambda: events.append("cmd-z"))
    app = _inserted_app("raw dictation")
    app.refiner = _FailingRefiner(TimeoutError("timed out again"))

    app._on_overlay_action("rerefine")
    fn, args = app.executor.submissions[-1]
    fn(*args)

    assert events == []
    assert app.overlay.calls[-1] == ("show", "inserted-raw-net", {"why": "timeout"})


def test_card_draft_keeps_the_clipboard_current_only_where_nothing_was_pasted(monkeypatch) -> None:
    copied = []
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", copied.append)
    app = _make_app("x")
    app.capsule.show("edit-notarget", text="第一版")
    app._on_overlay_action("draft", {"text": "第二版"})
    app.capsule.show("edit-modify", text="已粘贴的")
    app._on_overlay_action("draft", {"text": "不该进剪贴板"})

    assert copied == ["第二版"]


def test_done_in_the_card_copies_the_edit(monkeypatch) -> None:
    copied = []
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", copied.append)
    app = _make_app("x")
    app.config = SimpleNamespace(user_paths=None)
    app._copy_fallback_text = "提醒我周五"

    app._on_overlay_action("done", {"text": "提醒我周五之前续证书"})

    assert copied == ["提醒我周五之前续证书"]
    assert app.overlay.calls[-2:] == [("end_edit",), ("show", "copied", {})]


def test_hovering_holds_the_capsule_until_the_pointer_leaves() -> None:
    app = _inserted_app()
    (timer,) = _ManualTimer.made
    app._on_overlay_hover(True)
    assert timer.cancelled

    app._on_overlay_hover(False)
    resumed = _ManualTimer.made[-1]
    assert resumed is not timer and resumed.delay >= 1.2
    resumed.fire()
    assert app.overlay.calls[-1] == ("hide",)


def test_download_in_progress_blocks_recording(monkeypatch) -> None:
    app = _recording_app()
    app._download = (0.5, 0.0)
    monkeypatch.setattr("typeless_local.app.time.monotonic", lambda: 20.0)

    app._start_recording("tap")

    assert app.recorder.started is False
    assert app.overlay.calls == [("show", "download", {"p": 0.5, "eta": "约 20 秒"})]


def test_download_progress_never_replaces_a_dictation(monkeypatch) -> None:
    monkeypatch.setattr("typeless_local.app.model_is_cached", lambda repo: False)
    monkeypatch.setattr(
        "typeless_local.app.threading.Thread",
        lambda target, **kwargs: SimpleNamespace(start=target),
    )
    app = _recording_app()
    app.config = SimpleNamespace(jarvis_config={"asr": {"provider": "mlx_whisper"}})
    app.asr = SimpleNamespace(warmup=lambda: None)

    def download(repo, report):
        app.state = "recording"
        app.capsule.show("rec", mode="click")
        report(0.4)  # mid-dictation: must not show
        app.state = "idle"
        app.capsule.hide()
        report(0.8)

    monkeypatch.setattr("typeless_local.app.download_model", download)

    app._start_model_prefetch()

    assert app.overlay.shown() == ["download", "rec", "download"]
    assert app.overlay.calls[-1] == ("hide",)  # taken down once the model is in
    assert app._download is None


def test_mic_opens_before_focus_probe_and_mute_runs_off_the_hotkey_path(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    order = []
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda **_: order.append("focus") or FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    app = _recording_app()
    original_start = app.recorder.start
    app.recorder.start = lambda: (order.append("mic"), original_start())
    release = threading.Event()

    class SlowDucker(_FakeDucker):
        def duck(self) -> bool:
            release.wait(2)
            return super().duck()

    app.audio_ducker = SlowDucker()
    app._audio_io = ThreadPoolExecutor(max_workers=1)

    app._start_recording("tap")
    # The slow mute has not finished, yet the recording is already running.
    assert order == ["mic", "focus"]
    assert app.state == "recording"
    app._finish_recording()
    release.set()
    app._audio_io.shutdown(wait=True)

    assert app.audio_ducker.calls == ["duck", "restore_all"]


def test_capsule_follows_the_caret_when_asked(monkeypatch) -> None:
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda **_: FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    monkeypatch.setattr(app_module, "caret_rect", lambda: (400.0, 600.0, 2.0, 18.0))
    app = _recording_app()
    app.prefs = Preferences(capsule_position="caret")

    app._start_recording("tap")

    # No "starting" at the bottom first: the capsule appears at the caret.
    kinds = [call[0] if call[0] != "show" else call[1] for call in app.overlay.calls]
    assert kinds == ["anchor", "rec"]
    assert app.overlay.calls[0] == ("anchor", "caret", (400.0, 600.0, 2.0, 18.0))


def test_prefetch_warms_the_recognizer_when_weights_are_cached(monkeypatch) -> None:
    monkeypatch.setattr("typeless_local.app.model_is_cached", lambda repo: True)
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app.config = SimpleNamespace(jarvis_config={"asr": {"provider": "mlx_whisper"}})
    app.asr = SimpleNamespace(warmup=lambda: None)
    app.executor = _FakeExecutor()

    app._start_model_prefetch()

    assert app.executor.submissions == [(app.asr.warmup, ())]


def test_refine_prewarm_runs_at_most_once_every_few_seconds(monkeypatch) -> None:
    clock = [100.0]
    monkeypatch.setattr("typeless_local.app.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "typeless_local.app.threading.Thread",
        lambda target, **kwargs: SimpleNamespace(start=target),
    )
    app = _make_app("hi")
    prewarms = []
    app.refiner.prewarm = lambda: prewarms.append(clock[0])

    app._prewarm_refiner()  # recording starts
    clock[0] += 1.0
    app._prewarm_refiner()  # a stretch is cut a second later: still warm
    clock[0] += 3.0
    app._prewarm_refiner()  # four seconds in: warm it again before it idles out

    assert prewarms == [100.0, 104.0]


def test_count_units_counts_chinese_characters_and_latin_words() -> None:
    assert count_units("明天下午四点跟设计组过一下。") == 13
    assert count_units("Refined text.") == 2
    assert count_units("过一下 Typlus 的新版浮窗，then ship it") == 12


# ------------------------------------------------------------- menu bar


class _FakeMenubar:
    def __init__(self) -> None:
        self.issues = None
        self.states = []

    def set_issues(self, issues) -> None:
        self.issues = tuple(issues)

    def set_state(self, state) -> None:
        self.states.append(state)


def _menu_app(monkeypatch, env=None) -> TypelessLocalApp:
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(app_module, "has_accessibility_trust", lambda: True)
    app = _recording_app()
    app.menubar = _FakeMenubar()
    jarvis = {
        "llm": {
            "default_preset": "mini",
            "presets": {
                "mini": {"model": "gpt-mini", "api_key_env": "TEST_KEY_A"},
                "deep": {"model": "deepseek-chat", "api_key_env": "TEST_KEY_B"},
            },
        }
    }
    app.config = SimpleNamespace(
        jarvis_config=jarvis,
        refine=app_module.refine_config_for(jarvis, "mini"),
        input_device="",
        user_paths=None,
        sample_rate=16000,
        min_recording_seconds=0.25,
        max_recording_seconds=0,
    )
    return app


def test_missing_key_accessibility_and_mic_badge_the_icon(monkeypatch) -> None:
    monkeypatch.delenv("TEST_KEY_A", raising=False)
    app = _menu_app(monkeypatch)
    assert app._refresh_issues() == ("key",)
    assert app.menubar.issues == ("key",)

    monkeypatch.setenv("TEST_KEY_A", "sk-test")
    monkeypatch.setattr(app_module, "has_accessibility_trust", lambda: False)
    monkeypatch.setattr(app_module.permissions, "microphone_status", lambda: "denied")
    assert app._refresh_issues() == ("perm", "mic")


def test_refine_off_needs_no_key(monkeypatch) -> None:
    monkeypatch.delenv("TEST_KEY_A", raising=False)
    app = _menu_app(monkeypatch)
    app.prefs = Preferences(refine=False)
    assert app._current_issues() == ()


def test_menu_snapshot_reads_presets_devices_and_the_last_dictation(monkeypatch) -> None:
    monkeypatch.delenv("TEST_KEY_B", raising=False)
    app = _menu_app(monkeypatch, env={"TEST_KEY_A": "sk-test"})
    monkeypatch.setattr(app_module.devices, "refresh_if_changed", lambda: False)
    monkeypatch.setattr(app_module.devices, "list_input_devices", lambda: ["MacBook Pro 麦克风"])
    app._remember("明天开会", "备忘录")

    snap = app._menu_snapshot()

    assert snap.state == "idle" and snap.issues == ()
    assert [(p.name, p.needs_key) for p in snap.presets] == [("mini", False), ("deep", True)]
    assert snap.active_preset == "mini"
    assert snap.inputs == ("MacBook Pro 麦克风",)
    assert (snap.recent.text, snap.recent.app) == ("明天开会", "备忘录")
    assert app._copy_fallback_text == "明天开会"


def test_menu_actions_reach_the_app(monkeypatch) -> None:
    app = _menu_app(monkeypatch, env={"TEST_KEY_A": "sk-test"})
    calls = []
    app._start_recording = lambda mode: calls.append(("start", mode))
    app.select_model = lambda name: calls.append(("model", name))
    app.select_input_device = lambda name: calls.append(("input", name))
    app.open_settings = lambda pane=None: calls.append(("settings", pane))
    app.open_history = lambda: calls.append(("history",))
    monkeypatch.setattr(app_module.permissions, "open_url", lambda url: calls.append(("url", url)))
    monkeypatch.setattr(app_module, "request_accessibility_trust", lambda: calls.append(("ask-ax",)))

    for key in ("toggle", "latch", "preset:deep", "input:", "settings:", "settings:vocab", "history", "fix:key", "fix:perm"):
        app._on_menu_action(key)

    assert calls == [
        ("start", "tap"),
        ("start", "hands_free"),
        ("model", "deep"),
        ("input", ""),
        ("settings", None),
        ("settings", "vocab"),
        ("history",),
        ("settings", "model"),
        ("ask-ax",),
        ("url", app_module.permissions.ACCESSIBILITY_SETTINGS),
    ]


def test_menu_toggle_finishes_a_recording(monkeypatch) -> None:
    app = _menu_app(monkeypatch, env={"TEST_KEY_A": "sk-test"})
    finished = []
    app.state = "recording"
    app._finish_recording = lambda: finished.append(True)
    app._on_menu_action("toggle")
    app._on_menu_action("latch")  # only starts from idle
    assert finished == [True]


def test_menu_copy_puts_the_last_dictation_back(monkeypatch) -> None:
    copied = []
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", copied.append)
    app = _menu_app(monkeypatch, env={"TEST_KEY_A": "sk-test"})
    app._remember("上一段话", "Notes")
    app._on_menu_action("copy")
    assert copied == ["上一段话"]
    assert app.overlay.calls[-1] == ("show", "copied", {})


def test_a_failed_dictation_leaves_the_icon_idle(monkeypatch) -> None:
    app = _make_app("hello there friend")
    app.menubar = _FakeMenubar()
    app.headless = False
    app.state = "processing"
    app._active_session_id = 1
    app.refiner.refine = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setattr("typeless_local.app.paste_text", lambda text: (_ for _ in ()).throw(RuntimeError("no paste")))
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", lambda text: None)

    app._process_audio(np.ones(16000, dtype=np.float32), FocusContext("TextEdit", "x", can_insert_text=True), 1)

    assert app.menubar.states[-1] == "idle"
    assert app.overlay.calls[-1][:2] == ("show", "error")


def test_recording_start_queues_a_whisper_warm_up_ahead_of_the_audio(monkeypatch) -> None:
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda **_: FocusContext(app_name="TextEdit", window_title="Untitled"),
    )
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app._recording_timer = None
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, max_recording_seconds=0)
    app.state = "idle"
    app.mode = "tap"
    _attach(app)
    app.recorder = _FakeRecorder()
    app.audio_ducker = _FakeDucker()
    app.executor = _FakeExecutor()
    app.asr = SimpleNamespace(warmup=lambda: None)

    app._start_recording("tap")

    assert [fn for fn, _args in app.executor.submissions] == [app.asr.warmup]


def test_microphone_is_primed_at_launch_under_the_hotkey_lock(monkeypatch) -> None:
    app = TypelessLocalApp.__new__(TypelessLocalApp)
    app._lock = threading.RLock()
    app.config = SimpleNamespace(sample_rate=16000)
    app.recorder = SimpleNamespace(device=2)
    primed = []
    app._select_capture_device = lambda: "reSpeaker"
    monkeypatch.setattr(
        "typeless_local.app.devices.prime_input",
        lambda index, rate: primed.append((index, rate, app._lock._is_owned())),
    )
    monkeypatch.setattr(
        "typeless_local.app.threading.Thread",
        lambda target, **kwargs: SimpleNamespace(start=target),
    )

    app._prime_microphone()

    assert primed == [(2, 16000, True)]


# ------------------------------------------------------------- windows


class _FakeWindows:
    def __init__(self) -> None:
        self.calls = []

    def show_onboarding(self) -> None:
        self.calls.append(("onboarding",))

    def refresh(self, history=False) -> None:
        self.calls.append(("refresh", history))

    def download(self, fraction, eta="", done=False, error=False) -> None:
        self.calls.append(("download", fraction, done, error))


def _windows_app(monkeypatch, env=None):
    app = _menu_app(monkeypatch, env)
    app.windows = _FakeWindows()
    app.prefs = app_module.Preferences()
    saved = []
    app.set_preference = lambda key, value: saved.append((key, value))
    app._saved = saved
    monkeypatch.setattr(app_module.permissions, "microphone_status", lambda: "authorized")
    monkeypatch.setattr(app_module, "model_is_cached", lambda repo: True)
    return app


def test_first_launch_opens_the_guide(monkeypatch) -> None:
    app = _windows_app(monkeypatch)  # no API key yet
    app._first_run()
    assert app.windows.calls == [("onboarding",)]
    assert app._saved == []


def test_first_launch_skips_the_guide_when_everything_is_set_up(monkeypatch) -> None:
    app = _windows_app(monkeypatch, {"TEST_KEY_A": "sk-test-aaaaaaaaaaaa1234"})
    app._first_run()
    assert app.windows.calls == []
    assert app._saved == [("onboarding_done", True)]


def test_the_guide_is_shown_only_once(monkeypatch) -> None:
    app = _windows_app(monkeypatch)
    app.prefs = app_module.Preferences(onboarding_done=True)
    app._first_run()
    assert app.windows.calls == []


def test_language_and_ducking_apply_live_and_persist(monkeypatch, tmp_path) -> None:
    app = _windows_app(monkeypatch)
    written = []
    monkeypatch.setattr(app_module, "save_user_setting", lambda paths, *args: written.append(args))
    app.config.user_paths = SimpleNamespace(env_path=tmp_path / "env")
    languages = []
    app.asr = SimpleNamespace(set_language=languages.append)

    app.set_language("en")
    app.set_language("klingon")
    app.set_ducking(False)

    assert languages == ["en", ""]
    assert app.config.jarvis_config["asr"]["language"] == ""
    assert app.audio_ducker.enabled is False
    assert app.config.jarvis_config["audio_ducking"]["enabled"] is False
    assert written == [("asr", "language", "en"), ("asr", "language", ""), ("audio_ducking", "enabled", False)]


def test_a_new_key_for_the_active_model_replaces_the_client(monkeypatch, tmp_path) -> None:
    app = _windows_app(monkeypatch)
    stored = []
    monkeypatch.setattr(app_module, "_store_api_key", lambda env, key, path: stored.append((env, key, path)))
    app.config.user_paths = SimpleNamespace(env_path=tmp_path / "env")
    old = app.refiner = object()

    app.store_api_key("TEST_KEY_A", "sk-test-aaaaaaaaaaaa1234")

    assert stored == [("TEST_KEY_A", "sk-test-aaaaaaaaaaaa1234", tmp_path / "env")]
    assert app.refiner is not old and app.refiner.config.api_key_env == "TEST_KEY_A"


def test_download_progress_reaches_the_guide(monkeypatch) -> None:
    app = _windows_app(monkeypatch)
    app._download_progress(0.4, "约 30 秒")
    app._download_progress(1.0, done=True)
    assert app.windows.calls == [("download", 0.4, False, False), ("download", 1.0, True, False)]


def test_switching_model_or_mic_redraws_settings(monkeypatch) -> None:
    app = _windows_app(monkeypatch)
    monkeypatch.setattr(app_module.devices, "resolve_input_index", lambda name: None)
    app.config = app_module.AppConfig(
        root=Path("."), jarvis_root=Path("."), jarvis_config=app.config.jarvis_config, refine=app.config.refine
    )
    app.select_model("deep")
    app.select_input_device("USB Mic")
    assert app.windows.calls == [("refresh", False), ("refresh", False)]


def test_extend_adds_fifteen_minutes_to_a_recording_near_its_limit(monkeypatch) -> None:
    monkeypatch.setattr(app_module.threading, "Timer", _ManualTimer)
    clock = [1000.0]
    monkeypatch.setattr(app_module.time, "monotonic", lambda: clock[0])
    app = _recording_app()
    app.config = SimpleNamespace(sample_rate=16000, min_recording_seconds=0.25, max_recording_seconds=900.0)
    app.prefs = app_module.Preferences()
    app.state = "recording"
    app._recording_started_at = 1000.0
    app._recording_limit_s = 900.0
    app._start_recording_timeout()
    (first,) = _ManualTimer.made
    assert first.delay == 900.0

    clock[0] += 870.0  # 30 seconds left: the countdown is up
    app._on_overlay_action("extend")

    assert first.cancelled
    second = _ManualTimer.made[-1]
    assert second.delay == 930.0 and not second.cancelled
    kind, state, data = app.overlay.calls[-1]
    assert (kind, state, data["max"], data["ext"]) == ("show", "rec", 1800.0, 15)
    assert data["elapsed"] == 870.0


def test_extend_does_nothing_once_the_recording_is_over(monkeypatch) -> None:
    monkeypatch.setattr(app_module.threading, "Timer", _ManualTimer)
    app = _recording_app()
    app.state = "processing"
    app._recording_limit_s = 900.0
    app._on_overlay_action("extend")
    assert _ManualTimer.made == [] and app.overlay.calls == []


def test_a_pasted_dictation_is_watched_until_it_is_sent(monkeypatch, tmp_path) -> None:
    from typeless_local.config import UserPaths
    from typeless_local.trace import DictationTrace
    import dataclasses

    from typeless_local import history

    monkeypatch.setattr("typeless_local.app.paste_text", lambda _text: None)
    monkeypatch.setattr("typeless_local.app.set_clipboard_text", lambda text: None)
    app = _make_app("raw dictation")
    db = tmp_path / "trace.db"
    app.config.user_paths = UserPaths(
        config_dir=tmp_path, vocab_path=tmp_path / "v.yaml", corrections_path=tmp_path / "c.yaml", trace_db_path=db,
        log_path=tmp_path / "a.log", stopwords_dir=tmp_path, user_config_path=tmp_path / "config.yaml", env_path=tmp_path / "env",
    )
    app.trace = DictationTrace(db)
    watched = []
    app.sent_watcher = SimpleNamespace(watch=lambda *args: watched.append(args), cancel=lambda: None)

    app._process_audio(np.ones(16000, dtype=np.float32), FocusContext(app_name="微信", window_title="", can_insert_text=True))

    ((row, pasted, pid),) = watched
    assert pasted == "Refined text." and pid == TARGET_PID
    app._store_sent_text(row, "Refined text, edited.")
    assert history.recent_sessions(db)[0]["sent"] == "Refined text, edited."

    # Off in Settings: nothing is watched.
    app.prefs = dataclasses.replace(app.prefs, save_sent_text=False)
    watched.clear()
    app._process_audio(np.ones(16000, dtype=np.float32), FocusContext(app_name="微信", window_title="", can_insert_text=True))
    assert watched == []


def test_text_before_the_caret_is_only_read_when_the_setting_is_on(monkeypatch) -> None:
    asked = []
    monkeypatch.setattr(
        "typeless_local.app.capture_focus_context",
        lambda read_before_text=False: asked.append(read_before_text) or FocusContext("TextEdit", "Untitled"),
    )
    app = _recording_app()
    assert app.prefs.send_before_text is False  # off unless the user turns it on

    app._start_recording("tap")
    app._finish_recording()
    app.prefs = Preferences(send_before_text=True)
    app.state = "idle"
    app._start_recording("tap")
    app._finish_recording()

    assert asked == [False, True]
