from __future__ import annotations

import pytest
import yaml

from typeless_local import config as cfg_mod
from typeless_local.preferences import Preferences, coerce, load_preferences, save_preference


def _paths(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    return cfg_mod.resolve_user_paths()


def test_defaults_keep_history_forever_and_sounds_off(monkeypatch, tmp_path) -> None:
    prefs = load_preferences(_paths(monkeypatch, tmp_path))

    assert prefs == Preferences()
    assert prefs.history_days == 0  # nothing is deleted unless the user asks
    assert prefs.sounds == "off"
    assert prefs.dismiss_seconds == 4.0


def test_saved_preference_lands_under_ui_next_to_engine_sections(monkeypatch, tmp_path) -> None:
    paths = _paths(monkeypatch, tmp_path)
    prefs = load_preferences(paths)

    prefs = save_preference(paths, prefs, "dismiss_seconds", "6")
    prefs = save_preference(paths, prefs, "refine", False)

    data = yaml.safe_load(paths.user_config_path.read_text(encoding="utf-8"))
    assert data["ui"] == {"dismiss_seconds": 6.0, "refine": False}
    assert list(data) == ["ui"]  # only what changed; the engine defaults stay in the bundled file
    assert load_preferences(paths).dismiss_seconds == 6.0
    assert load_preferences(paths).refine is False


def test_choices_are_validated() -> None:
    assert coerce("max_minutes", "15") == 15
    assert coerce("capsule_position", "caret") == "caret"
    with pytest.raises(ValueError):
        coerce("max_minutes", 7)
    with pytest.raises(ValueError):
        coerce("history_days", 1)
    with pytest.raises(ValueError):
        coerce("no_such_setting", 1)


def test_a_hand_edited_bad_value_falls_back_to_its_default(monkeypatch, tmp_path) -> None:
    paths = _paths(monkeypatch, tmp_path)
    paths.user_config_path.write_text("ui:\n  max_minutes: 7\n  sounds: start_end\n", encoding="utf-8")

    prefs = load_preferences(paths)

    assert prefs.max_minutes == 15
    assert prefs.sounds == "start_end"
