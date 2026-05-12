"""macOS menu-bar status indicator for typeless-local."""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import Callable, Literal

LOGGER = logging.getLogger(__name__)

State = Literal["idle", "starting", "recording", "processing", "error"]

STATE_TO_SYMBOL: dict[str, str] = {
    "idle": "mic",
    "starting": "mic",
    "recording": "record.circle.fill",
    "processing": "ellipsis.circle",
    "error": "exclamationmark.triangle.fill",
}

STATE_TO_LABEL: dict[str, str] = {
    "idle": "Ready",
    "starting": "Starting…",
    "recording": "Recording",
    "processing": "Thinking…",
    "error": "Error",
}

_DEFAULT_TRACE_FOLDER = Path.home() / ".typeless-local"
_DEFAULT_LOG_PATH = _DEFAULT_TRACE_FOLDER / "app.log"


class MenuBarIcon:
    """NSStatusItem wrapper; thread-safe ``set_state`` via callAfter."""

    def __init__(
        self,
        on_reload_vocab: Callable[[], None],
        on_quit: Callable[[], None],
        trace_folder: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._on_reload_vocab = on_reload_vocab
        self._on_quit = on_quit
        self._trace_folder = trace_folder or _DEFAULT_TRACE_FOLDER
        self._log_path = log_path or _DEFAULT_LOG_PATH
        self.current_state: State = "idle"
        self._status_item = None
        self._status_label_item = None
        self._lock = threading.Lock()

    def setup(self) -> None:
        """Create the NSStatusItem. Must run on the main thread."""

        from AppKit import (
            NSImage,
            NSImageSymbolConfiguration,
            NSMenu,
            NSMenuItem,
            NSStatusBar,
            NSColor,
        )

        bar = NSStatusBar.systemStatusBar()
        item = bar.statusItemWithLength_(-1)  # NSVariableStatusItemLength
        button = item.button()
        button.setImagePosition_(2)  # NSImageOnly

        menu = NSMenu.alloc().init()

        label = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Typeless Local — {STATE_TO_LABEL['idle']}", None, ""
        )
        label.setEnabled_(False)
        self._status_label_item = label
        menu.addItem_(label)
        menu.addItem_(NSMenuItem.separatorItem())

        reload_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Reload Vocab", "reloadVocabAction:", "r"
        )
        reload_item.setTarget_(_make_action_target(self._on_reload_action))
        menu.addItem_(reload_item)
        menu.addItem_(NSMenuItem.separatorItem())

        open_trace = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open Trace Folder", "openTraceAction:", ""
        )
        open_trace.setTarget_(_make_action_target(self._on_open_trace_action))
        menu.addItem_(open_trace)

        show_log = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show Log", "showLogAction:", ""
        )
        show_log.setTarget_(_make_action_target(self._on_show_log_action))
        menu.addItem_(show_log)
        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "quitAction:", "q"
        )
        quit_item.setTarget_(_make_action_target(self._on_quit_action))
        menu.addItem_(quit_item)

        item.setMenu_(menu)
        self._status_item = item
        self._apply_state(self.current_state)

    def set_state(self, state: State) -> None:
        """Thread-safe state update; clamps unknown states to 'idle'."""

        with self._lock:
            if state not in STATE_TO_SYMBOL:
                state = "idle"
            self.current_state = state
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._apply_state, self.current_state)
        except Exception:
            LOGGER.debug("set_state called without AppKit available", exc_info=True)

    def _apply_state(self, state: State) -> None:
        if self._status_item is None:
            return
        try:
            from AppKit import NSImage, NSImageSymbolConfiguration, NSColor

            symbol = STATE_TO_SYMBOL.get(state, "mic")
            image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                symbol, f"Typeless Local {state}"
            )
            if image is not None:
                tint = _state_color(state)
                image.setTemplate_(False)
                config = NSImageSymbolConfiguration.configurationWithHierarchicalColor_(tint)
                tinted = image.imageWithSymbolConfiguration_(config)
                self._status_item.button().setImage_(tinted or image)
            if self._status_label_item is not None:
                self._status_label_item.setTitle_(
                    f"Typeless Local — {STATE_TO_LABEL.get(state, state)}"
                )
        except Exception:
            LOGGER.debug("_apply_state failed", exc_info=True)

    def _on_reload_action(self, sender) -> None:
        try:
            self._on_reload_vocab()
        except Exception:
            LOGGER.warning("Reload-vocab callback failed", exc_info=True)

    def _on_quit_action(self, sender) -> None:
        try:
            self._on_quit()
        except Exception:
            LOGGER.warning("Quit callback failed", exc_info=True)

    def _on_open_trace_action(self, sender) -> None:
        try:
            self._trace_folder.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["open", str(self._trace_folder)])
        except Exception:
            LOGGER.warning("Open trace folder failed", exc_info=True)

    def _on_show_log_action(self, sender) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            if not self._log_path.exists():
                self._log_path.touch()
            subprocess.Popen(["open", str(self._log_path)])
        except Exception:
            LOGGER.warning("Show log failed", exc_info=True)


def _state_color(state: str):
    from AppKit import NSColor

    if state == "recording" or state == "error":
        return NSColor.systemRedColor()
    if state == "starting" or state == "processing":
        return NSColor.systemYellowColor()
    return NSColor.systemGrayColor()


def _make_action_target(handler: Callable):
    """Wrap a Python callable as an NSObject that responds to ObjC selectors.

    The menu items above use selectors like ``reloadVocabAction:`` etc., so
    we generate a class with those exact selector names. Each selector dispatches
    to the corresponding Python handler.
    """

    from objc import python_method
    from Foundation import NSObject

    class _ActionTarget(NSObject):
        def initWithHandler_(self, h):
            self = NSObject.init(self)
            if self is None:
                return None
            self._handler = h
            return self

        def reloadVocabAction_(self, sender):
            self._handler(sender)

        def quitAction_(self, sender):
            self._handler(sender)

        def openTraceAction_(self, sender):
            self._handler(sender)

        def showLogAction_(self, sender):
            self._handler(sender)

    target = _ActionTarget.alloc().initWithHandler_(handler)
    # Keep a strong reference; ObjC retains weakly here.
    _ACTION_TARGETS.append(target)
    return target


_ACTION_TARGETS: list = []
