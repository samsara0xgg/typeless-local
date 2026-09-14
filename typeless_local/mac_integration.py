"""macOS focus, hotkey, and insertion helpers."""

from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass
import logging
import time
from typing import Callable

import ApplicationServices
from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString, NSWorkspace
from Foundation import NSData
import Quartz

LOGGER = logging.getLogger(__name__)

# nspasteboard.org convention: a pasteboard carrying this type is a means to an
# end, not something the user copied, so clipboard managers skip it. Without it
# every dictation leaves an entry in the clipboard history even though the real
# clipboard is restored a moment later. Raycast, the manager running here,
# advertises the type in its binary.
TRANSIENT_TYPE = "org.nspasteboard.TransientType"


class _MachTimebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


def _load_mach_timebase() -> tuple[int, int]:
    """Read the system's mach_absolute_time -> nanoseconds ratio once at import.

    On Apple Silicon this is 125/3 (mach ticks are ~41.67ns each); on Intel
    it is 1/1 (ticks are nanoseconds). NSEvent.timestamp via PyObjC does not
    apply this conversion correctly on Apple Silicon, so we read CGEvent
    timestamps directly and convert here.
    """

    try:
        libsystem = ctypes.CDLL(ctypes.util.find_library("System"))
        libsystem.mach_timebase_info.argtypes = [ctypes.POINTER(_MachTimebase)]
        libsystem.mach_timebase_info.restype = ctypes.c_int
        info = _MachTimebase()
        libsystem.mach_timebase_info(ctypes.byref(info))
        numer = int(info.numer) or 1
        denom = int(info.denom) or 1
        return numer, denom
    except Exception:
        LOGGER.exception("Failed to read mach_timebase_info; falling back to 1:1")
        return 1, 1


_TIMEBASE_NUMER, _TIMEBASE_DENOM = _load_mach_timebase()


def _mach_ticks_to_seconds(ticks: int) -> float:
    return ticks * _TIMEBASE_NUMER / _TIMEBASE_DENOM / 1e9

F5_KEYCODE = 96
# On Apple Silicon Macs the dictation key (F5) reports virtual keycode 176
# instead of the standard F5 keycode 96. We accept both so external keyboards
# with a real F5 also work.
DICTATION_KEYCODE = 176
PRIMARY_KEYCODES = frozenset({F5_KEYCODE, DICTATION_KEYCODE})
RIGHT_OPTION_KEYCODE = 61
SPACE_KEYCODE = 49
ESCAPE_KEYCODE = 53
# Return and the keypad's Enter, so sending a message is noticed either way.
RETURN_KEYCODES = frozenset({36, 76})
V_KEYCODE = 9
OPTION_FLAG_MASK = getattr(Quartz, "kCGEventFlagMaskAlternate", 1 << 19)
# Right Command arrives as a FlagsChanged event with keycode 54 (kVK_RightCommand).
RIGHT_COMMAND_KEYCODE = 54
COMMAND_FLAG_MASK = getattr(Quartz, "kCGEventFlagMaskCommand", 1 << 20)
HOTKEY_EVENT_TAP_LOCATION = getattr(Quartz, "kCGHIDEventTap", Quartz.kCGSessionEventTap)
TEXT_INPUT_ROLES = {
    "AXTextArea",
    "AXTextField",
    "AXComboBox",
    "AXSearchField",
}
SURROUNDING_TEXT_RADIUS = 500
# ponytail: size heuristic, because role cannot tell these apart — Ghostty's
# scrollback and Codex's input box both report AXTextArea. Above this many
# characters, an undecodable caret means the end of the value is almost
# certainly not where the user is. Drop the guard if a real caret decode lands.
UNANCHORED_TEXT_LIMIT = 2000


@dataclass(frozen=True)
class FocusContext:
    """Best-effort context for the currently focused target."""

    app_name: str
    window_title: str
    selected_text: str = ""
    focused_role: str = ""
    can_insert_text: bool = False
    surrounding_text: str = ""


def capture_focus_context() -> FocusContext:
    """Capture focused app/window metadata without reading document contents."""

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    app_name = str(app.localizedName() if app else "")
    pid = app.processIdentifier() if app else 0
    window_title = ""
    selected_text = ""
    focused_role = ""
    can_insert_text = False
    surrounding_text = ""

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
                surrounding_text = _extract_surrounding_text(
                    focused_element, SURROUNDING_TEXT_RADIUS
                )
            else:
                # Some apps publish no focused element at all: ChatGPT's
                # composer is one, and no amount of AXManualAccessibility or
                # AXEnhancedUserInterface coaxes a text role out of it. Silence
                # is not evidence that the caret is somewhere unpastable, and
                # the hotkey was pressed while that window held it, so paste.
                # A paste that lands nowhere costs one Cmd+V; refusing to paste
                # strands the whole dictation in the panel. Apps that really
                # have no text target answer with a role and are unaffected.
                can_insert_text = True
        except Exception as exc:
            LOGGER.debug("Unable to read focused AX context: %s", exc)

    return FocusContext(
        app_name=app_name,
        window_title=window_title,
        selected_text=selected_text,
        focused_role=focused_role,
        can_insert_text=can_insert_text,
        surrounding_text=surrounding_text,
    )


def _extract_surrounding_text(element, radius: int) -> str:
    """Return ±radius characters of document text around the cursor.

    Returns "" when the element does not expose its document text via
    AXValue, when the selected-range cannot be decoded, or when AX raises.
    The whole value is truncated to a ±radius window so refine prompts
    stay bounded even on large documents.
    """

    full_value = _copy_ax_attribute(element, ApplicationServices.kAXValueAttribute)
    if not isinstance(full_value, str):
        return ""
    full_text = full_value
    if not full_text:
        return ""

    range_value = _copy_ax_attribute(
        element, ApplicationServices.kAXSelectedTextRangeAttribute
    )
    cursor = _coerce_range_location(range_value)
    if cursor is None:
        # No caret. Falling back to the end of the value is right in an input box,
        # where the caret does sit at the end, and wrong in a terminal scrollback,
        # where the end is the status bar. Only guess on small values.
        if len(full_text) > UNANCHORED_TEXT_LIMIT:
            return ""
        cursor = len(full_text)
    cursor = max(0, min(cursor, len(full_text)))

    start = max(0, cursor - radius)
    end = min(len(full_text), cursor + radius)
    return full_text[start:end]


def _coerce_range_location(range_value) -> int | None:
    """Pull the .location out of a kAXSelectedTextRangeAttribute value.

    PyObjC can return this as a CFRange struct, an AXValueRef, a (loc, len)
    tuple, or as some app-specific wrapper. Try each path; return None if
    none work.
    """

    if range_value is None:
        return None
    location = getattr(range_value, "location", None)
    if location is not None:
        try:
            return int(location)
        except (TypeError, ValueError):
            pass
    if isinstance(range_value, tuple) and len(range_value) >= 1:
        try:
            return int(range_value[0])
        except (TypeError, ValueError):
            pass
    try:
        success, info = ApplicationServices.AXValueGetValue(
            range_value, ApplicationServices.kAXValueCFRangeType, None
        )
        if success:
            return int(info.location)
    except Exception:
        pass
    return None


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
    pasteboard.setData_forType_(NSData.data(), TRANSIENT_TYPE)

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
            item.setData_forType_(NSData.data(), TRANSIENT_TYPE)
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
    """Capture F5 / right-Cmd tap, F5+Space / right-Cmd+Space, and Esc with a Quartz event tap."""

    def __init__(
        self,
        callback: HotkeyCallback,
        debug_hotkey: bool = False,
        is_active_fn: Callable[[], bool] | None = None,
        wants_return_fn: Callable[[], bool] | None = None,
    ) -> None:
        self.callback = callback
        self.debug_hotkey = debug_hotkey
        # When set, Esc is only swallowed while is_active_fn() is True; otherwise
        # it passes through to the focused app. Without this, the global tap
        # consumed every Esc system-wide, breaking Esc in any app.
        self.is_active_fn = is_active_fn
        # Asked on every Return press, so it must stay a plain attribute read.
        self.wants_return_fn = wants_return_fn
        self._tap = None
        self._source = None
        self._primary_down: set[int] = set()
        self._debug_down = False
        # Right Cmd is also a modifier (Cmd+C, Cmd+Tab), so a tap only counts
        # if no other key went down while it was held.
        self._rcmd_armed = False
        # Event-time of the most recent primary down/up, in seconds. Captured
        # from NSEvent.timestamp so the value reflects when macOS generated the
        # event, not when our handler picked it up — handler time is unreliable
        # because _start_recording briefly blocks the runloop while opening the
        # microphone, which would otherwise inflate held_for and misfire
        # hold-to-talk on quick taps.
        self.last_primary_down_at = 0.0
        self.last_primary_up_at = 0.0

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
            if keycode == RIGHT_COMMAND_KEYCODE:
                if Quartz.CGEventGetFlags(event) & COMMAND_FLAG_MASK:
                    self._rcmd_armed = True
                elif self._rcmd_armed:
                    self._rcmd_armed = False
                    # A tap toggles: same timestamp for down/up so the app never
                    # reads a long hold as hold-to-talk.
                    now = self._event_time(event)
                    self.last_primary_down_at = now
                    self.callback("primary_down")
                    self.last_primary_up_at = now
                    self.callback("primary_up")
                return event  # never swallow a modifier change
            if self.debug_hotkey and keycode == RIGHT_OPTION_KEYCODE:
                flags = Quartz.CGEventGetFlags(event)
                now_down = bool(flags & OPTION_FLAG_MASK)
                if now_down != self._debug_down:
                    self._debug_down = now_down
                    self.callback("primary_down" if now_down else "primary_up")
                return None
            return event

        if event_type == Quartz.kCGEventKeyDown:
            if self._rcmd_armed:
                self._rcmd_armed = False
                if keycode == SPACE_KEYCODE:
                    self.callback("hands_free")
                    return None
            if keycode in PRIMARY_KEYCODES:
                # macOS 26.4 may deliver KeyDown for both 96 and 176 on a single
                # physical F5 press; only fire primary_down on the first key of
                # the press, and treat further primary keycodes (and auto-repeats)
                # as part of the same hold.
                was_idle = not self._primary_down
                self._primary_down.add(keycode)
                if was_idle:
                    self.last_primary_down_at = self._event_time(event)
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
            if keycode in RETURN_KEYCODES:
                # Sending the dictated message means the overlay has served its
                # purpose. Never swallow the key, and never ask the app anything
                # unless the overlay is actually up: this runs inside a
                # synchronous event tap, where slow work stalls the keyboard.
                if self.wants_return_fn is not None and self.wants_return_fn():
                    self.callback("return_pressed")
                return event
        if event_type == Quartz.kCGEventKeyUp and keycode in PRIMARY_KEYCODES:
            if keycode in self._primary_down:
                self._primary_down.discard(keycode)
                if not self._primary_down:
                    self.last_primary_up_at = self._event_time(event)
                    self.callback("primary_up")
            return None
        return event

    def _event_time(self, event) -> float:
        return _mach_ticks_to_seconds(Quartz.CGEventGetTimestamp(event))
