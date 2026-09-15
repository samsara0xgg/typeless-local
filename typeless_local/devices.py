"""Audio device enumeration, system output switching, and hardware-AEC pairing.

Ducking exists because the microphone would otherwise pick up whatever the
speakers are playing. A capture device with hardware echo cancellation removes
that reason, but only while it is fed the same signal the speakers get, which
means the pairing of input and output device is what decides whether ducking is
still needed. ``has_hardware_aec`` answers exactly that question.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any

LOGGER = logging.getLogger(__name__)

SWITCH_AUDIO_SOURCE = "SwitchAudioSource"
SYSTEM_DEFAULT = ""
# Launched from Finder the app inherits no shell PATH, so a Homebrew install is
# invisible to shutil.which. Same reason API keys live in ~/.typlus/env.
_SWITCH_FALLBACK_PATHS = (
    "/opt/homebrew/bin/SwitchAudioSource",
    "/usr/local/bin/SwitchAudioSource",
)


def _switch_binary() -> str | None:
    found = shutil.which(SWITCH_AUDIO_SOURCE)
    if found:
        return found
    for path in _SWITCH_FALLBACK_PATHS:
        if os.access(path, os.X_OK):
            return path
    return None


def _sounddevice() -> Any:  # noqa: ANN401 - module handle
    import sounddevice as sd  # noqa: PLC0415

    return sd


def _names(kind: str) -> list[str]:
    """Device names exposing at least one channel of ``kind``, in system order."""

    key = f"max_{kind}_channels"
    try:
        devices = _sounddevice().query_devices()
    except Exception:
        LOGGER.warning("Unable to enumerate audio devices", exc_info=True)
        return []
    out: list[str] = []
    seen: set[str] = set()
    for device in devices:
        name = str(device.get("name") or "").strip()
        if not name or name in seen or int(device.get(key, 0) or 0) <= 0:
            continue
        seen.add(name)
        out.append(name)
    return out


def list_input_devices() -> list[str]:
    return _names("input")


def list_output_devices() -> list[str]:
    return _names("output")


def _default_name(slot: int) -> str:
    """Name of the current system default device; "" when it cannot be read."""

    try:
        sd = _sounddevice()
        index = sd.default.device[slot]
        if index is None or int(index) < 0:
            return ""
        return str(sd.query_devices(int(index)).get("name") or "").strip()
    except Exception:
        LOGGER.debug("Unable to read default audio device %d", slot, exc_info=True)
        return ""


def current_input_device() -> str:
    return _default_name(0)


def current_output_device() -> str:
    return _default_name(1)


def refresh() -> None:
    """Re-read the hardware list so a mic plugged or pulled since launch is seen.

    PortAudio enumerates once when it initialises, so a long-running process
    keeps offering a device that has since been unplugged and then fails to
    open it with an internal error. Only safe while no stream is open.
    """

    sd = _sounddevice()
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        LOGGER.warning("Unable to refresh the audio device list", exc_info=True)


def resolve_input_index(name: str) -> int | None:
    """sounddevice index for ``name``; None means "let the system decide"."""

    wanted = (name or "").strip()
    if not wanted:
        return None
    try:
        devices = _sounddevice().query_devices()
    except Exception:
        LOGGER.warning("Unable to resolve input device %r", wanted, exc_info=True)
        return None
    for index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0) or 0) <= 0:
            continue
        if str(device.get("name") or "").strip() == wanted:
            return index
    LOGGER.warning("Input device %r not present; falling back to system default", wanted)
    return None


def can_switch_output() -> bool:
    return _switch_binary() is not None


def set_output_device(name: str) -> bool:
    """Point the system default output at ``name``. False when it did not happen."""

    wanted = (name or "").strip()
    if not wanted:
        return False
    binary = _switch_binary()
    if binary is None:
        LOGGER.warning("%s not found; cannot switch output", SWITCH_AUDIO_SOURCE)
        return False
    try:
        subprocess.run(
            [binary, "-s", wanted, "-t", "output"],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        LOGGER.warning("Failed to switch system output to %r", wanted, exc_info=True)
        return False
    LOGGER.info("System output switched to %s", wanted)
    return True


def has_hardware_aec(input_name: str, output_name: str, pairs: list[Any]) -> bool:
    """Whether this input/output pairing cancels the speakers on its own."""

    if not input_name or not output_name:
        return False
    for pair in pairs or []:
        if not isinstance(pair, dict):
            continue
        if (
            str(pair.get("input") or "").strip() == input_name
            and str(pair.get("output") or "").strip() == output_name
        ):
            return True
    return False
