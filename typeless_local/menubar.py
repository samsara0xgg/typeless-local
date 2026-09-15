"""macOS menu-bar status indicator for Typlus."""

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

# Unicode glyph used as a fallback title when SF Symbols don't load. Shown
# directly in the menu bar so the icon never disappears even if SF Symbol
# resolution silently fails.
STATE_TO_TITLE: dict[str, str] = {
    "idle": "TL",
    "starting": "TL•",
    "recording": "●REC",
    "processing": "TL…",
    "error": "TL!",
}

SYSTEM_DEFAULT_LABEL = "System Default"

_DEFAULT_TRACE_FOLDER = Path.home() / ".typlus"
_DEFAULT_LOG_PATH = _DEFAULT_TRACE_FOLDER / "app.log"


class MenuBarIcon:
    """NSStatusItem wrapper; thread-safe ``set_state`` via callAfter."""

    def __init__(
        self,
        on_reload_vocab: Callable[[], None],
        on_quit: Callable[[], None],
        trace_folder: Path | None = None,
        log_path: Path | None = None,
        presets: list[str] | None = None,
        active_preset: str = "",
        on_select_model: Callable[[str], None] | None = None,
        input_devices: list[str] | None = None,
        output_devices: list[str] | None = None,
        active_input: str = "",
        active_output: str = "",
        on_select_input: Callable[[str], None] | None = None,
        on_select_output: Callable[[str], None] | None = None,
        on_set_api_key: Callable[[], None] | None = None,
    ) -> None:
        self._on_reload_vocab = on_reload_vocab
        self._on_quit = on_quit
        self._presets = list(presets or [])
        self.active_preset = active_preset
        self._on_select_model = on_select_model
        self._model_items: dict[str, object] = {}
        self._input_devices = list(input_devices or [])
        self._output_devices = list(output_devices or [])
        self.active_input = active_input
        self.active_output = active_output
        self._on_select_input = on_select_input
        self._on_select_output = on_select_output
        self._on_set_api_key = on_set_api_key
        self._input_items: dict[str, object] = {}
        self._output_items: dict[str, object] = {}
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
        # Dragging the icon off the menu bar persists isVisible = false, and
        # AppKit restores it on every later launch, so the icon never comes
        # back on its own. This is the only way back short of editing defaults.
        item.setVisible_(True)
        button = item.button()
        # Set a unicode-fallback title up front so the status item is visible
        # even if SF Symbol image loading fails later (image-only buttons with
        # a missing image collapse to zero width).
        button.setTitle_("●")
        button.setImagePosition_(0)  # NSNoImage — overridden when image loads

        menu = NSMenu.alloc().init()

        label = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Typlus — {STATE_TO_LABEL['idle']}", None, ""
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

        if self._on_set_api_key is not None:
            api_key_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Set API Key\u2026", "setAPIKeyAction:", ""
            )
            api_key_item.setTarget_(_make_action_target(self._on_set_api_key_action))
            menu.addItem_(api_key_item)
        menu.addItem_(NSMenuItem.separatorItem())

        if self._presets:
            model_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Model", None, "")
            submenu = NSMenu.alloc().initWithTitle_("Model")
            for name in self._presets:
                entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    name, "selectModelAction:", ""
                )
                entry.setRepresentedObject_(name)
                entry.setTarget_(_make_action_target(self._on_select_model_action))
                submenu.addItem_(entry)
                self._model_items[name] = entry
            model_item.setSubmenu_(submenu)
            menu.addItem_(model_item)
            menu.addItem_(NSMenuItem.separatorItem())
            self._apply_active_preset()

        if self._input_devices:
            # "" is the system default, so the menu always offers a way back to it.
            self._add_device_submenu(
                menu,
                title="Input",
                names=[SYSTEM_DEFAULT_LABEL, *self._input_devices],
                selector="selectInputAction:",
                handler=self._on_select_input_action,
                items=self._input_items,
            )
            self._apply_active_input()
        if self._output_devices:
            self._add_device_submenu(
                menu,
                title="Output",
                names=self._output_devices,
                selector="selectOutputAction:",
                handler=self._on_select_output_action,
                items=self._output_items,
            )
            self._apply_active_output()
        if self._input_devices or self._output_devices:
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

    def set_active_preset(self, name: str) -> None:
        """Thread-safe checkmark update for the Model submenu."""

        self.active_preset = name
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._apply_active_preset)
        except Exception:
            LOGGER.debug("set_active_preset called without AppKit available", exc_info=True)

    def _add_device_submenu(self, menu, *, title, names, selector, handler, items) -> None:
        """Attach one checkmarked submenu of device names to ``menu``."""

        from AppKit import NSMenu, NSMenuItem

        parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        submenu = NSMenu.alloc().initWithTitle_(title)
        for name in names:
            entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(name, selector, "")
            entry.setRepresentedObject_(name)
            entry.setTarget_(_make_action_target(handler))
            submenu.addItem_(entry)
            items[name] = entry
        parent.setSubmenu_(submenu)
        menu.addItem_(parent)

    def set_active_input(self, name: str) -> None:
        """Thread-safe checkmark update for the Input submenu."""

        self.active_input = name
        self._call_after(self._apply_active_input)

    def set_active_output(self, name: str) -> None:
        """Thread-safe checkmark update for the Output submenu."""

        self.active_output = name
        self._call_after(self._apply_active_output)

    def _call_after(self, callback) -> None:
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(callback)
        except Exception:
            LOGGER.debug("Menu update requested without AppKit available", exc_info=True)

    def _apply_active_input(self) -> None:
        active = self.active_input or SYSTEM_DEFAULT_LABEL
        for name, item in self._input_items.items():
            item.setState_(1 if name == active else 0)

    def _apply_active_output(self) -> None:
        for name, item in self._output_items.items():
            item.setState_(1 if name == self.active_output else 0)

    def _on_select_input_action(self, sender) -> None:
        try:
            name = str(sender.representedObject())
            if self._on_select_input is not None:
                self._on_select_input("" if name == SYSTEM_DEFAULT_LABEL else name)
        except Exception:
            LOGGER.warning("Select-input callback failed", exc_info=True)

    def _on_select_output_action(self, sender) -> None:
        try:
            name = str(sender.representedObject())
            if self._on_select_output is not None:
                self._on_select_output(name)
        except Exception:
            LOGGER.warning("Select-output callback failed", exc_info=True)

    def _apply_active_preset(self) -> None:
        for name, item in self._model_items.items():
            item.setState_(1 if name == self.active_preset else 0)  # NSControlStateValueOn

    def _apply_state(self, state: State) -> None:
        if self._status_item is None:
            return
        button = self._status_item.button()
        # Always set a colored unicode dot as the title so the icon is visible
        # regardless of SF Symbol availability. Mapping per state below.
        title_dot = STATE_TO_TITLE.get(state, "●")
        try:
            button.setTitle_(title_dot)
            button.setImagePosition_(0)  # NSNoImage (no image yet)
        except Exception:
            LOGGER.warning("menubar: failed to set fallback title", exc_info=True)

        try:
            from AppKit import NSImage

            symbol = STATE_TO_SYMBOL.get(state, "mic")
            image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                symbol, f"Typlus {state}"
            )
            if image is not None:
                try:
                    from AppKit import NSImageSymbolConfiguration

                    tint = _state_color(state)
                    config = NSImageSymbolConfiguration.configurationWithHierarchicalColor_(tint)
                    tinted = image.imageWithSymbolConfiguration_(config) or image
                except Exception:
                    LOGGER.info("menubar: hierarchical color unavailable; using template image")
                    tinted = image
                    tinted.setTemplate_(True)
                button.setImage_(tinted)
                # Once we have an image, hide the text and show image only.
                button.setTitle_("")
                button.setImagePosition_(2)  # NSImageOnly
        except Exception:
            LOGGER.warning("menubar: SF Symbol load failed; keeping text dot", exc_info=True)

        if self._status_label_item is not None:
            try:
                self._status_label_item.setTitle_(
                    f"Typlus — {STATE_TO_LABEL.get(state, state)}"
                )
            except Exception:
                LOGGER.debug("menubar: failed to update label", exc_info=True)

    def _on_reload_action(self, sender) -> None:
        try:
            self._on_reload_vocab()
        except Exception:
            LOGGER.warning("Reload-vocab callback failed", exc_info=True)

    def _on_set_api_key_action(self, sender) -> None:
        try:
            if self._on_set_api_key is not None:
                self._on_set_api_key()
        except Exception:
            LOGGER.warning("Set-API-key callback failed", exc_info=True)

    def _on_select_model_action(self, sender) -> None:
        try:
            name = str(sender.representedObject())
            if self._on_select_model is not None:
                self._on_select_model(name)
        except Exception:
            LOGGER.warning("Select-model callback failed", exc_info=True)

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


_ACTION_TARGETS: list = []
_ActionTarget = None  # lazy-defined NSObject subclass (one global ObjC class)


def _ensure_action_target_class():
    """Define the NSObject subclass once (PyObjC classes are global)."""

    global _ActionTarget
    if _ActionTarget is not None:
        return _ActionTarget

    import objc
    from Foundation import NSObject

    class ActionTarget(NSObject):
        def init(self):
            # PyObjC requires `objc.super(...).init()`; calling
            # `NSObject.init(self)` directly raises "Need 0 arguments, got 1".
            self = objc.super(ActionTarget, self).init()
            if self is None:
                return None
            self._handler = None
            return self

        def setHandler_(self, h):
            self._handler = h

        def reloadVocabAction_(self, sender):
            if self._handler is not None:
                self._handler(sender)

        def quitAction_(self, sender):
            if self._handler is not None:
                self._handler(sender)

        def selectModelAction_(self, sender):
            if self._handler is not None:
                self._handler(sender)

        def selectInputAction_(self, sender):
            if self._handler is not None:
                self._handler(sender)

        def selectOutputAction_(self, sender):
            if self._handler is not None:
                self._handler(sender)

        def openTraceAction_(self, sender):
            if self._handler is not None:
                self._handler(sender)

        def showLogAction_(self, sender):
            if self._handler is not None:
                self._handler(sender)

    _ActionTarget = ActionTarget
    return _ActionTarget


def _make_action_target(handler: Callable):
    """Wrap a Python callable as an NSObject responding to the menu selectors."""

    cls = _ensure_action_target_class()
    target = cls.alloc().init()
    target.setHandler_(handler)
    # Keep a strong reference; ObjC retains weakly here.
    _ACTION_TARGETS.append(target)
    return target
