from __future__ import annotations

from unittest.mock import MagicMock

from typeless_local.menubar import MenuBarIcon, STATE_TO_SYMBOL


def test_state_to_symbol_covers_all_states() -> None:
    for state in ("idle", "starting", "recording", "processing", "error"):
        assert state in STATE_TO_SYMBOL


def test_set_state_updates_tracked_state() -> None:
    icon = MenuBarIcon(on_reload_vocab=MagicMock(), on_quit=MagicMock())
    icon.set_state("recording")
    assert icon.current_state == "recording"
    icon.set_state("idle")
    assert icon.current_state == "idle"


def test_set_state_unknown_state_is_clamped_to_idle() -> None:
    icon = MenuBarIcon(on_reload_vocab=MagicMock(), on_quit=MagicMock())
    icon.set_state("nonsense")  # type: ignore[arg-type]
    assert icon.current_state == "idle"


def test_reload_callback_invoked_via_action() -> None:
    on_reload = MagicMock()
    icon = MenuBarIcon(on_reload_vocab=on_reload, on_quit=MagicMock())
    icon._on_reload_action(None)
    on_reload.assert_called_once()


def test_quit_callback_invoked_via_action() -> None:
    on_quit = MagicMock()
    icon = MenuBarIcon(on_reload_vocab=MagicMock(), on_quit=on_quit)
    icon._on_quit_action(None)
    on_quit.assert_called_once()
