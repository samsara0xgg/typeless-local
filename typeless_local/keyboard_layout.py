"""Which key types a letter on the keyboard layout in use.

Cmd+V and Cmd+Z are posted as virtual keycodes, and a keycode names a key's
position, not its letter: keycode 6 is Z on QWERTY but W on AZERTY, so a
fixed Cmd+Z closed the window there, and on Dvorak the fixed Cmd+V typed
Cmd+. instead of pasting. The layout's own table says where each letter is.

Text Input Sources may only be read on the main thread, and the paste is sent
from the processing thread, so the codes are read on the main thread (at start
and whenever the layout changes) and kept here for any thread to use.
"""

from __future__ import annotations

import ctypes
import logging
from typing import Callable

LOGGER = logging.getLogger(__name__)

# Where the letters sit on US QWERTY, and the fallback when a layout has no
# Latin letters at all (macOS then matches shortcuts by these positions too).
QWERTY = {"v": 9, "z": 6}
LETTERS = tuple(QWERTY)

_codes: dict[str, int] = dict(QWERTY)
_observer = None

_CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"
_CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_KEY_ACTION_DOWN = 0
_COMMAND_MODIFIER = 0x0100 >> 8  # cmdKey, shifted the way UCKeyTranslate wants it
_NO_DEAD_KEYS = 1
# Posted by macOS whenever the input source in the menu bar changes.
LAYOUT_CHANGED = "com.apple.Carbon.TISNotifySelectedKeyboardInputSourceChanged"


def keycode(letter: str) -> int:
    """The keycode that types ``letter`` with Command held, on the last layout read."""

    return _codes.get(letter, QWERTY[letter])


def find_letters(translate: Callable[[int], str], letters=LETTERS) -> dict[str, int]:
    """Scan the 128 keycodes for each letter; the first key that types it wins."""

    found: dict[str, int] = {}
    for code in range(128):
        char = (translate(code) or "").lower()
        if char in letters and char not in found:
            found[char] = code
    return found


def refresh() -> dict[str, int]:
    """Read the current layout. Main thread only; keeps the old codes on failure."""

    global _codes
    try:
        found = _read_layout()
    except Exception:
        LOGGER.debug("Could not read the keyboard layout; keeping %s", _codes, exc_info=True)
        return _codes
    if all(letter in found for letter in LETTERS):
        if found != _codes:
            LOGGER.info("Keyboard layout: Cmd+V is keycode %d, Cmd+Z is keycode %d", found["v"], found["z"])
        _codes = found
    else:
        _codes = dict(QWERTY)
    return _codes


def watch() -> None:
    """Re-read the layout whenever the user switches it. Main thread only."""

    global _observer
    refresh()
    if _observer is not None:
        return
    try:
        from Foundation import NSDistributedNotificationCenter, NSOperationQueue  # noqa: PLC0415

        _observer = NSDistributedNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            LAYOUT_CHANGED, None, NSOperationQueue.mainQueue(), lambda _note: refresh()
        )
    except Exception:
        LOGGER.debug("Cannot watch for layout changes; the layout is read once", exc_info=True)


def _read_layout() -> dict[str, int]:
    carbon = ctypes.cdll.LoadLibrary(_CARBON)
    cf = ctypes.cdll.LoadLibrary(_CORE_FOUNDATION)
    carbon.TISCopyCurrentKeyboardLayoutInputSource.restype = ctypes.c_void_p
    carbon.TISCopyCurrentASCIICapableKeyboardLayoutInputSource.restype = ctypes.c_void_p
    carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
    carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    carbon.LMGetKbdType.restype = ctypes.c_uint8
    carbon.UCKeyTranslate.restype = ctypes.c_int32
    carbon.UCKeyTranslate.argtypes = [
        ctypes.c_void_p,  # const UCKeyboardLayout *
        ctypes.c_uint16,  # virtualKeyCode
        ctypes.c_uint16,  # keyAction
        ctypes.c_uint32,  # modifierKeyState
        ctypes.c_uint32,  # keyboardType
        ctypes.c_uint32,  # keyTranslateOptions
        ctypes.POINTER(ctypes.c_uint32),  # deadKeyState
        ctypes.c_ulong,  # maxStringLength
        ctypes.POINTER(ctypes.c_ulong),  # actualStringLength
        ctypes.POINTER(ctypes.c_uint16),  # unicodeString
    ]
    cf.CFDataGetBytePtr.restype = ctypes.c_void_p
    cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    layout_data = ctypes.c_void_p.in_dll(carbon, "kTISPropertyUnicodeKeyLayoutData").value
    keyboard_type = carbon.LMGetKbdType()

    # A layout without Latin letters (Russian, Greek) falls back to the Latin
    # layout macOS itself uses for shortcuts.
    found: dict[str, int] = {}
    for copy in (
        carbon.TISCopyCurrentKeyboardLayoutInputSource,
        carbon.TISCopyCurrentASCIICapableKeyboardLayoutInputSource,
    ):
        source = copy()
        if not source:
            continue
        try:
            data = carbon.TISGetInputSourceProperty(source, layout_data)
            layout = cf.CFDataGetBytePtr(data) if data else None
            if not layout:
                continue

            def translate(code: int) -> str:
                dead = ctypes.c_uint32(0)
                length = ctypes.c_ulong(0)
                chars = (ctypes.c_uint16 * 4)()
                status = carbon.UCKeyTranslate(
                    layout, code, _KEY_ACTION_DOWN, _COMMAND_MODIFIER, keyboard_type,
                    _NO_DEAD_KEYS, ctypes.byref(dead), 4, ctypes.byref(length), chars,
                )
                return chr(chars[0]) if status == 0 and length.value == 1 else ""

            found = find_letters(translate)
        finally:
            cf.CFRelease(source)
        if all(letter in found for letter in LETTERS):
            return found
    return found
