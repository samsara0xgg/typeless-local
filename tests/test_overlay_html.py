from __future__ import annotations

import inspect

from typeless_local.overlay import OVERLAY_HTML, FloatingOverlay, _hover_kind_for_local_point


def test_overlay_uses_official_style_control_icon_paths() -> None:
    assert "M9 16.17 4.83 12" in OVERLAY_HTML
    assert "M18.3 5.71 12 12" in OVERLAY_HTML


def test_overlay_contains_copy_fallback_ui() -> None:
    assert "Copy last transcript" in OVERLAY_HTML
    assert "copy-fallback" in OVERLAY_HTML
    assert "Copied" in OVERLAY_HTML


def test_overlay_contains_official_recording_tooltips() -> None:
    assert 'data-tooltip="Cancel"' in OVERLAY_HTML
    assert 'data-tooltip="Finish"' in OVERLAY_HTML
    assert 'data-tooltip-key="F5"' in OVERLAY_HTML
    assert "Click to start dictating" in OVERLAY_HTML
    assert "bottom = rootRect.bottom - targetRect.top + 10" in OVERLAY_HTML
    assert 'bar.addEventListener("mousemove", updateTooltipFromPointer)' in OVERLAY_HTML
    assert 'target.addEventListener("pointerenter", show)' in OVERLAY_HTML
    assert "window.setPointerTooltip" in OVERLAY_HTML
    assert "filter: drop-shadow(0px 0px 1px rgba(128, 128, 128, 0.40));" in OVERLAY_HTML


def test_overlay_window_accepts_mouse_moved_events() -> None:
    assert "setAcceptsMouseMovedEvents_(True)" in inspect.getsource(FloatingOverlay.setup)
    assert "NSTimer.scheduledTimerWithTimeInterval" in inspect.getsource(FloatingOverlay._start_hover_tracking)


def test_appkit_hover_hit_test_matches_recording_controls() -> None:
    assert _hover_kind_for_local_point("recording", 199, 25) == "cancel"
    assert _hover_kind_for_local_point("recording", 287, 25) == "finish"
    assert _hover_kind_for_local_point("recording", 250, 25) == ""
    assert _hover_kind_for_local_point("recording", 181, 25, has_countdown=True) == "cancel"
    assert _hover_kind_for_local_point("recording", 309, 25, has_countdown=True) == "finish"
    assert _hover_kind_for_local_point("hover", 250, 25) == "idle"
    assert _hover_kind_for_local_point("thinking", 250, 25) == ""


def test_copy_fallback_uses_official_alert_constants() -> None:
    assert "width: 360px;" in OVERLAY_HTML
    assert "height: 120px;" in OVERLAY_HTML
    assert "border-radius: 8px;" in OVERLAY_HTML
    assert "background: rgba(29, 26, 26, 1);" in OVERLAY_HTML
    assert "border: 1px solid rgba(119, 119, 119, 0.30);" in OVERLAY_HTML
    assert "padding: 16px;" in OVERLAY_HTML
    assert "gap: 8px;" in OVERLAY_HTML
    assert "font-weight: 500;" in OVERLAY_HTML
    assert "line-height: 16px;" in OVERLAY_HTML


def test_overlay_waveform_uses_delayed_diffusion_model() -> None:
    assert "DIFFUSION_DELAY = 80" in OVERLAY_HTML
    assert "pendingPulses" in OVERLAY_HTML
    assert "setTimeout" in OVERLAY_HTML
    assert "sideTimers" in OVERLAY_HTML


def test_overlay_waveform_uses_tuned_official_like_response() -> None:
    assert "INPUT_RESPONSE_GAIN = 0.60" in OVERLAY_HTML
    assert "TRIGGER_PROBABILITY_GAIN = 0.60" in OVERLAY_HTML
    assert "TRIGGER_MAX_PROBABILITY = 0.32" in OVERLAY_HTML
    assert "PULSE_TRIGGER_THRESHOLD = NOISE_THRESHOLD * 0.85" in OVERLAY_HTML
    assert "SILENCE_DECAY_THRESHOLD = NOISE_THRESHOLD * 1.15" in OVERLAY_HTML
    assert "now - lastPulseAt < 130" in OVERLAY_HTML
    assert "MAX_PULSE_HEIGHT = 18" in OVERLAY_HTML


def test_screen_for_point_picks_the_display_under_the_pointer() -> None:
    """The overlay must follow the pointer across displays.

    ``FloatingOverlay.setup`` frames the panel once from ``NSScreen.mainScreen()``,
    so before this the overlay stayed on whichever display was main when the app
    launched. Geometry below is Allen's real 2026-09-12 layout: the BenQ at the
    origin and the built-in display to its left at a negative x.
    """

    from types import SimpleNamespace

    from typeless_local.overlay import _screen_for_point

    def screen(x, y, w, h):
        rect = SimpleNamespace(origin=SimpleNamespace(x=x, y=y), size=SimpleNamespace(width=w, height=h))
        return SimpleNamespace(frame=lambda rect=rect: rect, tag=(x, y))

    benq = screen(0, 0, 1920, 1080)
    built_in = screen(-1352, 0, 1352, 878)
    screens = [benq, built_in]

    assert _screen_for_point(SimpleNamespace(x=952, y=272), screens) is benq
    assert _screen_for_point(SimpleNamespace(x=-600, y=400), screens) is built_in
    # The menu bar sits above visibleFrame but still belongs to that display.
    assert _screen_for_point(SimpleNamespace(x=100, y=1070), screens) is benq
    # Exactly on the shared edge belongs to the display that owns that origin.
    assert _screen_for_point(SimpleNamespace(x=0, y=500), screens) is benq
    assert _screen_for_point(SimpleNamespace(x=-1, y=500), screens) is built_in
    # Off every display.
    assert _screen_for_point(SimpleNamespace(x=5000, y=5000), screens) is None
