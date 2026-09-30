"""Microphone and Accessibility permission checks, and the settings they live in."""

from __future__ import annotations

import logging
import subprocess

LOGGER = logging.getLogger(__name__)

MICROPHONE_SETTINGS = "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
ACCESSIBILITY_SETTINGS = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
KEYBOARD_SETTINGS = "x-apple.systempreferences:com.apple.Keyboard-Settings.extension"
SOUND_SETTINGS = "x-apple.systempreferences:com.apple.Sound-Settings.extension"
# AVAuthorizationStatus
_MIC_STATUS = {0: "not_determined", 1: "restricted", 2: "denied", 3: "authorized"}
_AUDIO = "soun"  # AVMediaTypeAudio


def open_url(url: str) -> None:
    try:
        from AppKit import NSWorkspace  # noqa: PLC0415
        from Foundation import NSURL  # noqa: PLC0415

        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))
    except Exception:
        try:
            subprocess.run(["/usr/bin/open", url], check=False, timeout=5)
        except Exception:
            LOGGER.warning("Could not open %s", url, exc_info=True)


def _capture_device_class():
    import objc  # noqa: PLC0415

    try:
        return objc.lookUpClass("AVCaptureDevice")
    except objc.nosuchclass_error:
        objc.loadBundle(
            "AVFoundation", {}, bundle_path="/System/Library/Frameworks/AVFoundation.framework"
        )
        return objc.lookUpClass("AVCaptureDevice")


def microphone_status() -> str:
    """"authorized", "denied", "restricted", "not_determined" or "unknown"."""

    try:
        value = _capture_device_class().authorizationStatusForMediaType_(_AUDIO)
        return _MIC_STATUS.get(int(value), "unknown")
    except Exception:
        LOGGER.debug("Could not read the microphone permission", exc_info=True)
        return "unknown"


def request_microphone() -> None:
    """Make macOS show its microphone prompt; the answer is read back with microphone_status().

    Opening a PortAudio stream does not reliably prompt (it did nothing on a
    fresh install, leaving the guide waiting), so ask AVFoundation directly.
    """

    try:
        import objc  # noqa: PLC0415

        objc.registerMetaDataForSelector(
            b"AVCaptureDevice",
            b"requestAccessForMediaType:completionHandler:",
            {"arguments": {3: {"callable": {"retval": {"type": b"v"}, "arguments": {0: {"type": b"^v"}, 1: {"type": b"Z"}}}}}},
        )
        _capture_device_class().requestAccessForMediaType_completionHandler_(_AUDIO, lambda _granted: None)
    except Exception:
        LOGGER.warning("Could not ask for the microphone", exc_info=True)


def accessibility_trusted() -> bool:
    from typeless_local.mac_integration import has_accessibility_trust  # noqa: PLC0415

    return has_accessibility_trust()


def system_dictation_uses_f5() -> bool:
    """Whether macOS's own dictation shortcut is on, which also listens to F5 (🎤)."""

    try:
        result = subprocess.run(
            ["/usr/bin/defaults", "read", "com.apple.HIToolbox", "AppleDictationAutoEnable"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return False
    return result.returncode == 0 and result.stdout.strip() == "1"
