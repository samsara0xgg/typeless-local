"""macOS focus, hotkey, and insertion helpers."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Callable

import ApplicationServices
from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString, NSWorkspace
import Quartz

LOGGER = logging.getLogger(__name__)

F5_KEYCODE = 96
# On Apple Silicon Macs the dictation key (F5) reports virtual keycode 176
# instead of the standard F5 keycode 96. We accept both so external keyboards
# with a real F5 also work.
DICTATION_KEYCODE = 176
PRIMARY_KEYCODES = frozenset({F5_KEYCODE, DICTATION_KEYCODE})
RIGHT_OPTION_KEYCODE = 61
SPACE_KEYCODE = 49
ESCAPE_KEYCODE = 53
V_KEYCODE = 9
OPTION_FLAG_MASK = getattr(Quartz, "kCGEventFlagMaskAlternate", 1 << 19)
HOTKEY_EVENT_TAP_LOCATION = getattr(Quartz, "kCGHIDEventTap", Quartz.kCGSessionEventTap)
TEXT_INPUT_ROLES = {
    "AXTextArea",
    "AXTextField",
    "AXComboBox",
    "AXSearchField",
}


@dataclass(frozen=True)
class FocusContext:
    """Best-effort context for the currently focused target."""

    app_name: str
    window_title: str
    selected_text: str = ""
    focused_role: str = ""
    can_insert_text: bool = False


def capture_focus_context() -> FocusContext:
    """Capture focused app/window metadata without reading document contents."""

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    app_name = str(app.localizedName() if app else "")
    pid = app.processIdentifier() if app else 0
    window_title = ""
    selected_text = ""
    focused_role = ""
    can_insert_text = False

    if pid:
        try:
            app_ref = ApplicationServices.AXUIElementCreateApplication(pid)
            focused_window = _copy_ax_attribute(
                app_ref,
                ApplicationServices.kAXFocusedWindowAttribute,
            )
            if focused_window:
                title = _copy_ax_attribute(
                    focused_window,
                    ApplicationServices.kAXTitleAttribute,
                )
                window_title = str(title or "")
            focused_element = _copy_ax_attribute(
                app_ref,
                ApplicationServices.kAXFocusedUIElementAttribute,
            )
            if focused_element:
                role = _copy_ax_attribute(
                    focused_element,
                    ApplicationServices.kAXRoleAttribute,
                )
                focused_role = str(role or "")
                can_insert_text = _focused_element_accepts_text(
                    focused_element,
                    focused_role,
                )
                selection = _copy_ax_attribute(
                    focused_element,
                    ApplicationServices.kAXSelectedTextAttribute,
                )
                if selection is not None:
                    selected_text = str(selection or "")
        except Exception as exc:
            LOGGER.debug("Unable to read focused AX context: %s", exc)

    return FocusContext(
        app_name=app_name,
        window_title=window_title,
        selected_text=selected_text,
        focused_role=focused_role,
        can_insert_text=can_insert_text,
    )


def _copy_ax_attribute(element, attribute: str):
    """Copy an AX attribute while handling PyObjC tuple ordering."""

    result = ApplicationServices.AXUIElementCopyAttributeValue(element, attribute, None)
    if not isinstance(result, tuple) or len(result) != 2:
        return result

    first, second = result
    if isinstance(first, int):
        error, value = first, second
    else:
        value, error = first, second
    if error != ApplicationServices.kAXErrorSuccess:
        return None
    return value


def _focused_element_accepts_text(element, role: str) -> bool:
    """Return whether the focused AX element is likely to accept pasted text."""

    if role in TEXT_INPUT_ROLES:
        return True
    editable = _copy_ax_attribute(element, "AXEditable")
    if isinstance(editable, bool) and editable:
        return True
    return False


def set_clipboard_text(text: str) -> None:
    """Place text on the general pasteboard without attempting insertion."""

    if not text:
        return
    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    pasteboard.setString_forType_(text, NSPasteboardTypeString)


def paste_text(text: str) -> None:
    """Paste text into the currently focused app via the system pasteboard."""

    if not text:
        return
    pasteboard = NSPasteboard.generalPasteboard()
    snapshot = _snapshot_pasteboard(pasteboard)
    pasteboard.clearContents()
    pasteboard.setString_forType_(text, NSPasteboardTypeString)

    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    down = Quartz.CGEventCreateKeyboardEvent(source, V_KEYCODE, True)
    up = Quartz.CGEventCreateKeyboardEvent(source, V_KEYCODE, False)
    Quartz.CGEventSetFlags(down, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventSetFlags(up, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
    time.sleep(0.12)
    _restore_pasteboard(pasteboard, snapshot)


def _snapshot_pasteboard(pasteboard) -> list[list[tuple[object, object]]]:
    """Capture pasteboard items so dictation paste does not destroy the clipboard."""

    snapshot: list[list[tuple[object, object]]] = []
    try:
        for item in pasteboard.pasteboardItems() or []:
            values = []
            for item_type in item.types() or []:
                data = item.dataForType_(item_type)
                if data is not None:
                    values.append((item_type, data))
            if values:
                snapshot.append(values)
    except Exception as exc:
        LOGGER.debug("Unable to snapshot pasteboard: %s", exc)
    return snapshot


def _restore_pasteboard(pasteboard, snapshot: list[list[tuple[object, object]]]) -> None:
    """Restore a pasteboard snapshot captured before dictation insertion."""

    try:
        pasteboard.clearContents()
        if not snapshot:
            return
        restored_items = []
        for values in snapshot:
            item = NSPasteboardItem.alloc().init()
            for item_type, data in values:
                item.setData_forType_(data, item_type)
            restored_items.append(item)
        pasteboard.writeObjects_(restored_items)
    except Exception as exc:
        LOGGER.debug("Unable to restore pasteboard: %s", exc)


def has_accessibility_trust() -> bool:
    """Return whether Accessibility permission is already granted."""

    try:
        return bool(ApplicationServices.AXIsProcessTrusted())
    except Exception:
        return False


def request_accessibility_trust() -> bool:
    """Ask macOS to show the Accessibility permission prompt when possible."""

    try:
        options = {ApplicationServices.kAXTrustedCheckOptionPrompt: True}
        return bool(ApplicationServices.AXIsProcessTrustedWithOptions(options))
    except Exception:
        return has_accessibility_trust()


HotkeyCallback = Callable[[str], None]


class GlobalHotkeyMonitor:
    """Capture F5, F5+Space, and Esc with a Quartz event tap."""

    def __init__(
        self,
        callback: HotkeyCallback,
        debug_hotkey: bool = False,
        is_active_fn: Callable[[], bool] | None = None,
    ) -> None:
        self.callback = callback
        self.debug_hotkey = debug_hotkey
        # When set, Esc is only swallowed while is_active_fn() is True; otherwise
        # it passes through to the focused app. Without this, the global tap
        # consumed every Esc system-wide, breaking Esc in any app.
        self.is_active_fn = is_active_fn
        self._tap = None
        self._source = None
        self._primary_down: set[int] = set()
        self._debug_down = False

    def start(self) -> None:
        """Install the event tap."""

        mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        )
        self._tap = self._create_event_tap(HOTKEY_EVENT_TAP_LOCATION, mask)
        if self._tap is None and HOTKEY_EVENT_TAP_LOCATION != Quartz.kCGSessionEventTap:
            LOGGER.warning("HID event tap unavailable; falling back to session event tap")
            self._tap = self._create_event_tap(Quartz.kCGSessionEventTap, mask)
        if self._tap is None:
            raise RuntimeError("Could not create global event tap. Grant Accessibility permission.")
        self._source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            self._source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(self._tap, True)
        LOGGER.info("Global hotkey monitor started")

    def _create_event_tap(self, location: int, mask: int):
        return Quartz.CGEventTapCreate(
            location,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            mask,
            self._handle_event,
            None,
        )

    def stop(self) -> None:
        """Disable the event tap."""

        if self._tap is not None:
            Quartz.CGEventTapEnable(self._tap, False)

    def _handle_event(self, proxy, event_type, event, refcon):
        del proxy, refcon
        if (
            event_type
            in {
                Quartz.kCGEventTapDisabledByTimeout,
                Quartz.kCGEventTapDisabledByUserInput,
            }
            and self._tap is not None
        ):
            Quartz.CGEventTapEnable(self._tap, True)
            return event

        keycode = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventKeycode
        )

        if event_type == Quartz.kCGEventFlagsChanged:
            if self.debug_hotkey and keycode == RIGHT_OPTION_KEYCODE:
                flags = Quartz.CGEventGetFlags(event)
                now_down = bool(flags & OPTION_FLAG_MASK)
                if now_down != self._debug_down:
                    self._debug_down = now_down
                    self.callback("primary_down" if now_down else "primary_up")
                return None
            return event

        if event_type == Quartz.kCGEventKeyDown:
            if keycode in PRIMARY_KEYCODES:
                # macOS auto-repeats function keys; only fire once per physical press.
                if keycode not in self._primary_down:
                    self._primary_down.add(keycode)
                    self.callback("primary_down")
                return None
            if keycode == SPACE_KEYCODE and self._primary_down:
                self.callback("hands_free")
                return None
            if keycode == ESCAPE_KEYCODE:
                if self.is_active_fn is not None and not self.is_active_fn():
                    return event
                self.callback("cancel")
                return None
        if event_type == Quartz.kCGEventKeyUp and keycode in PRIMARY_KEYCODES:
            if keycode in self._primary_down:
                self._primary_down.discard(keycode)
                self.callback("primary_up")
            return None
        return event
