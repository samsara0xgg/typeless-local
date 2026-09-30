"""Preferences set from the Settings window.

They live under ``ui:`` in ~/.typlus/config.yaml, next to the engine's own
sections, so one file still holds everything a user has changed. Settings that
belong to an existing section (the recognition language, the refine preset,
the input device, ducking) are written there instead, where the engine already
reads them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
import logging
from typing import Any

from typeless_local import i18n
from typeless_local.config import UserPaths, load_yaml, save_user_setting

LOGGER = logging.getLogger(__name__)

SECTION = "ui"
# Allowed values for the settings that are a choice rather than a switch.
CHOICES: dict[str, tuple[Any, ...]] = {
    "capsule_position": ("bottom", "caret"),
    "dismiss_seconds": (2.0, 4.0, 6.0, 10.0),
    "sounds": ("off", "start_end"),
    "max_minutes": (5, 9, 15),
    # 0 keeps everything. Nothing is ever deleted unless the user picks a limit.
    "history_days": (30, 90, 365, 0),
    # "auto" speaks the Mac's own language: Chinese on a Chinese system, English otherwise.
    "ui_language": i18n.CHOICES,
}


@dataclass(frozen=True)
class Preferences:
    capsule_position: str = "bottom"
    show_handle: bool = True
    dismiss_seconds: float = 4.0
    sounds: str = "off"
    max_minutes: int = 15
    refine: bool = True
    rewrite_selection: bool = True
    show_ducked: bool = False
    save_history: bool = True
    history_days: int = 0
    send_window_title: bool = True
    # After a paste, keep what the text finally went out as (sent_text.py).
    save_sent_text: bool = True
    # Off by default: it costs tokens and a few AX reads, and has not yet been
    # shown to help. When off, the text is not even read.
    send_before_text: bool = False
    onboarding_done: bool = False
    ui_language: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_DEFAULTS = Preferences()
_TYPES = {field.name: type(getattr(_DEFAULTS, field.name)) for field in fields(Preferences)}


def coerce(key: str, value: Any) -> Any:
    """``value`` as the type ``key`` holds; ValueError when it cannot be."""

    if key not in _TYPES:
        raise ValueError(f"unknown preference {key!r}")
    kind = _TYPES[key]
    if kind is bool:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off", ""}:
                return False
            raise ValueError(f"{key}: not a switch value: {value!r}")
        return bool(value)
    try:
        coerced = kind(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key}: {value!r} is not a {kind.__name__}") from exc
    allowed = CHOICES.get(key)
    if allowed is not None and coerced not in allowed:
        raise ValueError(f"{key}: {coerced!r} is not one of {allowed}")
    return coerced


def _read_section(user_paths: UserPaths) -> dict[str, Any]:
    path = user_paths.user_config_path
    if not path.exists():
        return {}
    try:
        section = load_yaml(path).get(SECTION) or {}
    except Exception:
        LOGGER.warning("Could not read %s; using default preferences", path, exc_info=True)
        return {}
    return section if isinstance(section, dict) else {}


def load_preferences(user_paths: UserPaths | None) -> Preferences:
    """The saved preferences; a value that doesn't fit falls back to its default."""

    if user_paths is None:
        return _DEFAULTS
    values: dict[str, Any] = {}
    for key, raw in _read_section(user_paths).items():
        try:
            values[key] = coerce(key, raw)
        except ValueError:
            LOGGER.warning("Ignoring preference %s=%r", key, raw)
    return replace(_DEFAULTS, **values)


def save_preference(user_paths: UserPaths | None, prefs: Preferences, key: str, value: Any) -> Preferences:
    """Validate, persist and return the updated preferences."""

    coerced = coerce(key, value)
    updated = replace(prefs, **{key: coerced})
    if user_paths is not None:
        save_user_setting(user_paths, SECTION, key, coerced)
    return updated
