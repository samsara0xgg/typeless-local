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
V_KEYCODE = 9
Z_KEYCODE = 6
OPTION_FLAG_MASK = getattr(Quartz, "kCGEventFlagMaskAlternate", 1 << 19)
SHIFT_FLAG_MASK = getattr(Quartz, "kCGEventFlagMaskShift", 1 << 17)
# Right Command arrives as a FlagsChanged event with keycode 54 (kVK_RightCommand).
RIGHT_COMMAND_KEYCODE = 54
COMMAND_FLAG_MASK = getattr(Quartz, "kCGEventFlagMaskCommand", 1 << 20)
HOTKEY_EVENT_TAP_LOCATION = getattr(Quartz, "kCGHIDEventTap", Quartz.kCGSessionEventTap)
# The Cmd+V and Cmd+Z this app posts itself carry this in the event's user-data
# field, so the event tap can tell them from the user's own keys.
SYNTHETIC_EVENT_TAG = 0x59414E43
_USER_DATA_FIELD = getattr(Quartz, "kCGEventSourceUserData", 42)
_AX_CGRECT_TYPE = getattr(ApplicationServices, "kAXValueCGRectType", None) or getattr(
    ApplicationServices, "kAXValueTypeCGRect", 3
)
_AX_CFRANGE_TYPE = getattr(ApplicationServices, "kAXValueCFRangeType", None) or getattr(
    ApplicationServices, "kAXValueTypeCFRange", 4
)
# How much of what is already written before the caret refinement gets to see:
# enough for the names and terms of the message being replied to, not the document.
BEFORE_TEXT_CHARS = 300
# A field longer than this is only read through a ranged query, never whole.
_MAX_WHOLE_VALUE_CHARS = 200_000
TEXT_INPUT_ROLES = {
    "AXTextArea",
    "AXTextField",
    "AXComboBox",
    "AXSearchField",
    # Claude's desktop app (Electron) reports its whole page, composer
    # included, as the focused AXWebArea, so a dictation into its message box
    # went to the copy panel. As with apps that publish no focused element, a
    # paste that lands nowhere costs one Cmd+V and the text stays in the panel.
    "AXWebArea",
}

@dataclass(frozen=True)
class FocusContext:
    """Best-effort context for the currently focused target."""

    app_name: str
    window_title: str
    selected_text: str = ""
    focused_role: str = ""
    can_insert_text: bool = False
    # The frontmost app's process, to tell later whether it is still the one in front.
    pid: int = 0
    # What is already written just before the caret, so refinement can spell a
    # name or term the way the text above it does. Empty for password fields.
    before_text: str = ""


# Seconds an AX query may wait on the target app. The default is about six,
# and focus is read on the hotkey path, so a hung app would stall the keyboard.
AX_MESSAGING_TIMEOUT_S = 0.25
_ax_timeout_set = False


def _limit_ax_messaging_timeout() -> None:
    """Set the global AX timeout once (it applies via the system-wide element)."""

    global _ax_timeout_set
    if _ax_timeout_set:
        return
    _ax_timeout_set = True
    try:
        ApplicationServices.AXUIElementSetMessagingTimeout(
            ApplicationServices.AXUIElementCreateSystemWide(), AX_MESSAGING_TIMEOUT_S
        )
    except Exception as exc:
        LOGGER.debug("Unable to limit the AX messaging timeout: %s", exc)


def capture_focus_context(read_before_text: bool = False) -> FocusContext:
    """Capture focused app/window metadata, and the text before the caret if asked."""

    _limit_ax_messaging_timeout()
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    app_name = str(app.localizedName() if app else "")
    pid = app.processIdentifier() if app else 0
    window_title = ""
    selected_text = ""
    focused_role = ""
    can_insert_text = False
    before_text = ""

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
                if read_before_text:
                    before_text = _text_before_caret(focused_element, focused_role)
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
        pid=int(pid or 0),
        before_text=before_text,
    )


def focused_text_value(pid: int) -> str | None:
    """The text in ``pid``'s focused text field, or None when it has none to read.

    Used only to see what a pasted dictation was sent as; never called unless
    a dictation was just pasted into that app.
    """

    if not pid:
        return None
    _limit_ax_messaging_timeout()
    try:
        app_ref = ApplicationServices.AXUIElementCreateApplication(pid)
        element = _copy_ax_attribute(app_ref, ApplicationServices.kAXFocusedUIElementAttribute)
        if not element:
            return None
        role = str(_copy_ax_attribute(element, ApplicationServices.kAXRoleAttribute) or "")
        if role == "AXSecureTextField" or _copy_ax_attribute(element, "AXSubrole") == "AXSecureTextField":
            return None  # a password is never read
        if not _focused_element_accepts_text(element, role):
            return None
        value = _copy_ax_attribute(element, ApplicationServices.kAXValueAttribute)
    except Exception as exc:
        LOGGER.debug("Focused text unavailable: %s", exc)
        return None
    return value if isinstance(value, str) else (str(value) if value is not None else None)


def _text_before_caret(element, role: str) -> str:
    """Up to BEFORE_TEXT_CHARS of the focused field's text before the caret.

    Asks for just that range, so a long document is never read whole; falls
    back to slicing the field's value when the app does not answer ranged
    queries. Password fields are never read.
    """

    if role == "AXSecureTextField":
        return ""
    try:
        if _copy_ax_attribute(element, "AXSubrole") == "AXSecureTextField":
            return ""
        selection = _copy_ax_attribute(element, ApplicationServices.kAXSelectedTextRangeAttribute)
        caret = _range_location(selection)
        if caret is None or caret <= 0:
            return ""
        start = max(0, caret - BEFORE_TEXT_CHARS)
        text = ""
        wanted = ApplicationServices.AXValueCreate(_AX_CFRANGE_TYPE, (start, caret - start))
        if wanted is not None:
            text = _unpack_ax_result(
                ApplicationServices.AXUIElementCopyParameterizedAttributeValue(
                    element, ApplicationServices.kAXStringForRangeParameterizedAttribute, wanted, None
                )
            )
        if not isinstance(text, str) or not text:
            value = _copy_ax_attribute(element, ApplicationServices.kAXValueAttribute)
            if not isinstance(value, str) or len(value) > _MAX_WHOLE_VALUE_CHARS:
                return ""
            text = value[start:caret]
        return str(text)[-BEFORE_TEXT_CHARS:].strip()
    except Exception as exc:
        LOGGER.debug("Unable to read the text before the caret: %s", exc)
        return ""


def _range_location(value) -> int | None:
    """The location of an AX CFRange value, or None when there is none."""

    if value is None:
        return None
    unpacked = ApplicationServices.AXValueGetValue(value, _AX_CFRANGE_TYPE, None)
    if isinstance(unpacked, tuple) and len(unpacked) == 2 and isinstance(unpacked[0], bool):
        if not unpacked[0]:
            return None
        unpacked = unpacked[1]
    location = getattr(unpacked, "location", None)
    if location is None and isinstance(unpacked, tuple) and unpacked:
        location = unpacked[0]
    try:
        return int(location)
    except (TypeError, ValueError):
        return None


def frontmost_pid() -> int:
    """The process of the app in front, or 0."""

    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app else 0
    except Exception:
        return 0


def caret_rect() -> tuple[float, float, float, float] | None:
    """Where the caret is, as (x, y, w, h) in screen coordinates (origin bottom left).

    None when the focused app does not say, which many do not: the capsule then
    stays above the Dock.
    """

    _limit_ax_messaging_timeout()
    pid = frontmost_pid()
    if not pid:
        return None
    try:
        app_ref = ApplicationServices.AXUIElementCreateApplication(pid)
        element = _copy_ax_attribute(app_ref, ApplicationServices.kAXFocusedUIElementAttribute)
        if not element:
            return None
        selection = _copy_ax_attribute(element, ApplicationServices.kAXSelectedTextRangeAttribute)
        if selection is None:
            return None
        result = ApplicationServices.AXUIElementCopyParameterizedAttributeValue(
            element, ApplicationServices.kAXBoundsForRangeParameterizedAttribute, selection, None
        )
        value = _unpack_ax_result(result)
        if value is None:
            return None
        unpacked = ApplicationServices.AXValueGetValue(value, _AX_CGRECT_TYPE, None)
        rect = unpacked[1] if isinstance(unpacked, tuple) else unpacked
        x, y = float(rect.origin.x), float(rect.origin.y)
        width, height = float(rect.size.width), float(rect.size.height)
        # Some apps answer with an empty rectangle or with the whole text area.
        if (width <= 0 and height <= 0) or height > 200:
            return None
        from AppKit import NSScreen  # noqa: PLC0415

        primary_height = float(NSScreen.screens()[0].frame().size.height)
    except Exception as exc:
        LOGGER.debug("Caret position unavailable: %s", exc)
        return None
    # AX measures from the top of the main display, AppKit from its bottom.
    return (x, primary_height - (y + height), max(1.0, width), height)


def _copy_ax_attribute(element, attribute: str):
    """Copy an AX attribute while handling PyObjC tuple ordering."""

    return _unpack_ax_result(ApplicationServices.AXUIElementCopyAttributeValue(element, attribute, None))


def _unpack_ax_result(result):
    """The value from an AX (error, value) pair, whichever order PyObjC returns it in."""

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

    _post_command_key(V_KEYCODE)
    time.sleep(0.12)
    _restore_pasteboard(pasteboard, snapshot)


def undo_last_edit() -> None:
    """Send Cmd+Z to the app in front, to take back the paste just made there."""

    _post_command_key(Z_KEYCODE)


def _post_command_key(keycode: int) -> None:
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    down = Quartz.CGEventCreateKeyboardEvent(source, keycode, True)
    up = Quartz.CGEventCreateKeyboardEvent(source, keycode, False)
    for event in (down, up):
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        try:
            Quartz.CGEventSetIntegerValueField(event, _USER_DATA_FIELD, SYNTHETIC_EVENT_TAG)
        except Exception:
            pass
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


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
        watch_keys_fn: Callable[[], bool] | None = None,
    ) -> None:
        self.callback = callback
        self.debug_hotkey = debug_hotkey
        # When set, Esc is only swallowed while is_active_fn() is True; otherwise
        # it passes through to the focused app. Without this, the global tap
        # consumed every Esc system-wide, breaking Esc in any app.
        self.is_active_fn = is_active_fn
        # Whether the app wants to hear about ordinary typing: after a paste it
        # offers to undo or replace it, which is only right until the user types
        # something else. Asked on every key press, so it must stay a plain
        # attribute read.
        self.watch_keys_fn = watch_keys_fn
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
            if keycode == ESCAPE_KEYCODE and (self.is_active_fn is None or self.is_active_fn()):
                self.callback("cancel")
                return None
            # Never swallowed, and nothing asked of the app unless it is
            # watching: this runs inside a synchronous event tap, where slow
            # work stalls the keyboard.
            if self.watch_keys_fn is not None and self.watch_keys_fn() and not self._is_synthetic(event):
                flags = Quartz.CGEventGetFlags(event)
                undo = keycode == Z_KEYCODE and flags & COMMAND_FLAG_MASK and not flags & SHIFT_FLAG_MASK
                self.callback("undo" if undo else "typed")
            return event
        if event_type == Quartz.kCGEventKeyUp and keycode in PRIMARY_KEYCODES:
            if keycode in self._primary_down:
                self._primary_down.discard(keycode)
                if not self._primary_down:
                    self.last_primary_up_at = self._event_time(event)
                    self.callback("primary_up")
            return None
        return event

    @staticmethod
    def _is_synthetic(event) -> bool:
        return Quartz.CGEventGetIntegerValueField(event, _USER_DATA_FIELD) == SYNTHETIC_EVENT_TAG

    def _event_time(self, event) -> float:
        return _mach_ticks_to_seconds(Quartz.CGEventGetTimestamp(event))
