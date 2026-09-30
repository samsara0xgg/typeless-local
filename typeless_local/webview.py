"""WKWebView plumbing shared by the capsule and the app's windows.

Pages live in ``typeless_local/web`` and talk to Python through one message
handler, ``bridge``, posting JSON strings; Python answers by calling
``window.app.receive(message)``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
from typing import Callable

import objc
from AppKit import NSApplication, NSColor, NSWorkspace
from Foundation import NSURL, NSObject
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

LOGGER = logging.getLogger(__name__)

MessageCallback = Callable[[dict], None]


def web_root() -> Path:
    """Where the pages are: next to this module, or in the bundle's Resources."""

    here = Path(__file__).resolve().parent / "web"
    if (here / "kit.js").exists():
        return here
    # py2app keeps the package inside Resources/lib/python3.x/; the pages are
    # copied to Resources/web.
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "web"
        if parent.name == "Resources" and (candidate / "kit.js").exists():
            return candidate
    resources = Path(sys.executable).resolve().parent.parent / "Resources" / "web"
    return resources if (resources / "kit.js").exists() else here


def accessibility_env() -> dict:
    """The display accommodations the pages adapt to, read from the system."""

    workspace = NSWorkspace.sharedWorkspace()

    def flag(name: str) -> bool:
        try:
            return bool(getattr(workspace, name)())
        except Exception:
            return False

    return {
        "rm": flag("accessibilityDisplayShouldReduceMotion"),
        "rt": flag("accessibilityDisplayShouldReduceTransparency"),
        "hc": flag("accessibilityDisplayShouldIncreaseContrast"),
    }


def announce(text: str) -> None:
    """Have VoiceOver say ``text`` (the capsule is never focused, so it cannot be read)."""

    if not text:
        return
    try:
        if not NSWorkspace.sharedWorkspace().isVoiceOverEnabled():
            return
    except Exception:
        pass
    try:
        from AppKit import (  # noqa: PLC0415
            NSAccessibilityAnnouncementKey,
            NSAccessibilityAnnouncementRequestedNotification,
            NSAccessibilityPostNotificationWithUserInfo,
            NSAccessibilityPriorityHigh,
            NSAccessibilityPriorityKey,
        )

        NSAccessibilityPostNotificationWithUserInfo(
            NSApplication.sharedApplication(),
            NSAccessibilityAnnouncementRequestedNotification,
            {NSAccessibilityAnnouncementKey: text, NSAccessibilityPriorityKey: NSAccessibilityPriorityHigh},
        )
    except Exception:
        LOGGER.debug("VoiceOver announcement failed", exc_info=True)


class BridgeHandler(NSObject):
    """Receives ``window.webkit.messageHandlers.bridge.postMessage(json)``."""

    def initWithCallback_(self, callback):  # noqa: N802 - Cocoa selector
        self = objc.super(BridgeHandler, self).init()
        if self is None:
            return None
        self.callback = callback
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message) -> None:  # noqa: N802
        del controller
        callback = getattr(self, "callback", None)
        if callback is not None:
            dispatch(str(message.body()), callback)


def dispatch(body: str, callback: MessageCallback) -> None:
    """Parse one bridge message and hand it to ``callback``; never raises."""

    try:
        payload = json.loads(body)
    except Exception:
        LOGGER.debug("Ignoring a bridge message that is not JSON")
        return
    if not isinstance(payload, dict):
        return
    if payload.get("t") == "jserror":
        LOGGER.warning("Page error: %s (%s:%s)", payload.get("msg"), payload.get("src"), payload.get("line"))
        return
    try:
        callback(payload)
    except Exception:
        LOGGER.exception("Bridge handler failed for %s", payload.get("t"))


class NavigationDelegate(NSObject):
    """Reloads a page whose web content process was killed (memory pressure).

    The capsule's page lives for the whole session; without this it would
    silently stop drawing if WebKit's content process ever went away.
    """

    def webViewWebContentProcessDidTerminate_(self, webview) -> None:  # noqa: N802
        LOGGER.warning("Web content process ended; reloading the page")
        webview.reload()


class WebPage:
    """One transparent web view, its bridge and the page it shows."""

    def __init__(self, frame, callback: MessageCallback, view_class=WKWebView) -> None:
        self.controller = WKUserContentController.alloc().init()
        self.handler = BridgeHandler.alloc().initWithCallback_(callback)
        self.controller.addScriptMessageHandler_name_(self.handler, "bridge")
        config = WKWebViewConfiguration.alloc().init()
        config.setUserContentController_(self.controller)
        self.view = view_class.alloc().initWithFrame_configuration_(frame, config)
        self.view.setValue_forKey_(False, "drawsBackground")
        try:
            self.view.setUnderPageBackgroundColor_(NSColor.clearColor())
        except Exception:
            pass
        # WKWebView holds its navigation delegate weakly.
        self.delegate = NavigationDelegate.alloc().init()
        self.view.setNavigationDelegate_(self.delegate)

    def load(self, name: str) -> None:
        root = web_root()
        page = NSURL.fileURLWithPath_(str(root / name))
        self.view.loadFileURL_allowingReadAccessToURL_(page, NSURL.fileURLWithPath_isDirectory_(str(root), True))

    def send(self, message: dict) -> None:
        """Deliver ``message`` to the page's ``window.app.receive``."""

        script = f"window.app&&window.app.receive({json.dumps(message, default=str)})"
        self.view.evaluateJavaScript_completionHandler_(script, None)

    def close(self) -> None:
        """Break the controller -> handler -> owner cycle when a window closes."""

        try:
            self.controller.removeScriptMessageHandlerForName_("bridge")
        except Exception:
            pass
        self.handler.callback = None
