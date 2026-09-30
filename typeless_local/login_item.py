"""Open at login, through SMAppService (macOS 13+).

The class is looked up at runtime so the app needs no extra PyObjC wrapper,
and only a real .app bundle registers: run from source, "the main app" would
be the Python interpreter.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)

# SMAppServiceStatus
_STATUS = {0: "disabled", 1: "enabled", 2: "requires_approval", 3: "unavailable"}


def _service():
    try:
        import objc  # noqa: PLC0415
        from Foundation import NSBundle  # noqa: PLC0415

        if not str(NSBundle.mainBundle().bundlePath() or "").endswith(".app"):
            return None
        try:
            cls = objc.lookUpClass("SMAppService")
        except objc.nosuchclass_error:
            objc.loadBundle(
                "ServiceManagement",
                {},
                bundle_path="/System/Library/Frameworks/ServiceManagement.framework",
            )
            cls = objc.lookUpClass("SMAppService")
        return cls.mainAppService()
    except Exception:
        LOGGER.debug("SMAppService unavailable", exc_info=True)
        return None


def status() -> str:
    """"enabled", "disabled", "requires_approval" or "unavailable"."""

    service = _service()
    if service is None:
        return "unavailable"
    try:
        return _STATUS.get(int(service.status()), "unavailable")
    except Exception:
        LOGGER.debug("Could not read the login item status", exc_info=True)
        return "unavailable"


def set_enabled(enabled: bool) -> str:
    """Register or unregister, and return the status that resulted."""

    service = _service()
    if service is None:
        return "unavailable"
    try:
        if enabled:
            result = service.registerAndReturnError_(None)
        else:
            result = service.unregisterAndReturnError_(None)
        ok, error = result if isinstance(result, tuple) else (result, None)
        if not ok:
            LOGGER.warning("Login item %s failed: %s", "register" if enabled else "unregister", error)
    except Exception:
        LOGGER.warning("Login item change failed", exc_info=True)
    return status()


def open_system_settings() -> None:
    """The Login Items pane, where a "requires approval" item is switched on."""

    try:
        import objc  # noqa: PLC0415

        objc.lookUpClass("SMAppService").openSystemSettingsLoginItems()
    except Exception:
        from typeless_local.permissions import open_url  # noqa: PLC0415

        open_url("x-apple.systempreferences:com.apple.LoginItems-Settings.extension")
