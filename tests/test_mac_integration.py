from __future__ import annotations

from typeless_local import mac_integration


def test_copy_ax_attribute_accepts_error_value_tuple(monkeypatch) -> None:
    monkeypatch.setattr(
        mac_integration.ApplicationServices,
        "AXUIElementCopyAttributeValue",
        lambda element, attr, out: (
            mac_integration.ApplicationServices.kAXErrorSuccess,
            "Title",
        ),
    )

    assert mac_integration._copy_ax_attribute(object(), "attr") == "Title"


def test_copy_ax_attribute_accepts_value_error_tuple(monkeypatch) -> None:
    monkeypatch.setattr(
        mac_integration.ApplicationServices,
        "AXUIElementCopyAttributeValue",
        lambda element, attr, out: (
            "Title",
            mac_integration.ApplicationServices.kAXErrorSuccess,
        ),
    )

    assert mac_integration._copy_ax_attribute(object(), "attr") == "Title"


def test_copy_ax_attribute_returns_none_on_error(monkeypatch) -> None:
    monkeypatch.setattr(
        mac_integration.ApplicationServices,
        "AXUIElementCopyAttributeValue",
        lambda element, attr, out: (1, None),
    )

    assert mac_integration._copy_ax_attribute(object(), "attr") is None


def test_focused_element_accepts_text_roles() -> None:
    assert mac_integration._focused_element_accepts_text(object(), "AXTextArea") is True








def test_focused_element_rejects_static_non_text(monkeypatch) -> None:
    monkeypatch.setattr(mac_integration, "_copy_ax_attribute", lambda element, attribute: None)

    assert mac_integration._focused_element_accepts_text(object(), "AXStaticText") is False


def test_event_tap_reenables_when_disabled_without_keyboard_event(monkeypatch) -> None:
    enabled = []
    monitor = mac_integration.GlobalHotkeyMonitor(lambda action: None)
    monitor._tap = object()
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventTapEnable",
        lambda tap, value: enabled.append((tap, value)),
    )

    result = monitor._handle_event(
        None,
        mac_integration.Quartz.kCGEventTapDisabledByTimeout,
        None,
        None,
    )

    assert result is None
    assert enabled == [(monitor._tap, True)]


def test_hotkey_monitor_prefers_hid_event_tap(monkeypatch) -> None:
    calls = []
    monitor = mac_integration.GlobalHotkeyMonitor(lambda action: None)
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventTapCreate",
        lambda location, placement, options, mask, callback, refcon: calls.append(location)
        or "tap",
    )
    monkeypatch.setattr(mac_integration.Quartz, "CFMachPortCreateRunLoopSource", lambda *args: "source")
    monkeypatch.setattr(mac_integration.Quartz, "CFRunLoopAddSource", lambda *args: None)
    monkeypatch.setattr(mac_integration.Quartz, "CGEventTapEnable", lambda *args: None)
    monkeypatch.setattr(mac_integration.Quartz, "CFRunLoopGetCurrent", lambda: "loop")

    monitor.start()

    assert calls == [mac_integration.HOTKEY_EVENT_TAP_LOCATION]


def test_f5_key_down_and_up_emit_primary_events(monkeypatch) -> None:
    events = []
    monitor = mac_integration.GlobalHotkeyMonitor(events.append)
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventGetIntegerValueField",
        lambda event, field: mac_integration.F5_KEYCODE,
    )

    down_result = monitor._handle_event(
        None,
        mac_integration.Quartz.kCGEventKeyDown,
        object(),
        None,
    )
    up_result = monitor._handle_event(
        None,
        mac_integration.Quartz.kCGEventKeyUp,
        object(),
        None,
    )

    assert down_result is None
    assert up_result is None
    assert events == ["primary_down", "primary_up"]


def test_dictation_keycode_emits_primary_events(monkeypatch) -> None:
    events = []
    monitor = mac_integration.GlobalHotkeyMonitor(events.append)
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventGetIntegerValueField",
        lambda event, field: mac_integration.DICTATION_KEYCODE,
    )

    monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, object(), None)
    monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyUp, object(), None)

    assert events == ["primary_down", "primary_up"]


def test_f5_autorepeat_keydown_is_ignored(monkeypatch) -> None:
    events = []
    monitor = mac_integration.GlobalHotkeyMonitor(events.append)
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventGetIntegerValueField",
        lambda event, field: mac_integration.F5_KEYCODE,
    )

    monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, object(), None)
    repeat_result = monitor._handle_event(
        None, mac_integration.Quartz.kCGEventKeyDown, object(), None
    )

    assert repeat_result is None
    assert events == ["primary_down"]


def test_paste_text_restores_clipboard_snapshot(monkeypatch) -> None:
    events = []
    restored = []

    class FakePasteboard:
        def clearContents(self):
            events.append("clear")

        def setString_forType_(self, text, item_type):
            events.append(("set", text, item_type))

        def setData_forType_(self, data, item_type):
            events.append(("set-data", item_type))

    pasteboard = FakePasteboard()

    class FakePasteboardFactory:
        @staticmethod
        def generalPasteboard():
            return pasteboard

    monkeypatch.setattr(mac_integration, "NSPasteboard", FakePasteboardFactory)
    monkeypatch.setattr(mac_integration, "_snapshot_pasteboard", lambda pb: [["snapshot"]])
    monkeypatch.setattr(
        mac_integration,
        "_restore_pasteboard",
        lambda pb, snapshot: restored.append((pb, snapshot)),
    )
    monkeypatch.setattr(mac_integration.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(mac_integration.Quartz, "CGEventSourceCreate", lambda state: object())
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventCreateKeyboardEvent",
        lambda source, keycode, down: {"keycode": keycode, "down": down},
    )
    monkeypatch.setattr(mac_integration.Quartz, "CGEventSetFlags", lambda event, flags: None)
    monkeypatch.setattr(mac_integration.Quartz, "CGEventPost", lambda tap, event: events.append(("post", event)))

    mac_integration.paste_text("Hello")

    assert events[0] == "clear"
    assert events[1] == ("set", "Hello", mac_integration.NSPasteboardTypeString)
    # The dictation is a means to an end, not something the user copied. Without
    # this marker every dictation left an entry in the clipboard history even
    # though the real clipboard is restored a moment later.
    assert ("set-data", mac_integration.TRANSIENT_TYPE) in events
    assert mac_integration.TRANSIENT_TYPE == "org.nspasteboard.TransientType"
    assert restored == [(pasteboard, [["snapshot"]])]


def test_set_clipboard_text_does_not_restore_previous_clipboard(monkeypatch) -> None:
    events = []

    class FakePasteboard:
        def clearContents(self):
            events.append("clear")

        def setString_forType_(self, text, item_type):
            events.append(("set", text, item_type))

    class FakePasteboardFactory:
        @staticmethod
        def generalPasteboard():
            return FakePasteboard()

    monkeypatch.setattr(mac_integration, "NSPasteboard", FakePasteboardFactory)

    mac_integration.set_clipboard_text("Hello")

    assert events == [
        "clear",
        ("set", "Hello", mac_integration.NSPasteboardTypeString),
    ]


class _KeyEvent:
    def __init__(self, keycode: int, flags: int = 0) -> None:
        self.keycode = keycode
        self.flags = flags


def _rcmd_monitor(monkeypatch, events):
    monitor = mac_integration.GlobalHotkeyMonitor(events.append)
    monkeypatch.setattr(
        mac_integration.Quartz, "CGEventGetIntegerValueField", lambda event, field: event.keycode
    )
    monkeypatch.setattr(mac_integration.Quartz, "CGEventGetFlags", lambda event: event.flags)
    return monitor


def _rcmd(monitor, down: bool):
    event = _KeyEvent(
        mac_integration.RIGHT_COMMAND_KEYCODE, mac_integration.COMMAND_FLAG_MASK if down else 0
    )
    return monitor._handle_event(None, mac_integration.Quartz.kCGEventFlagsChanged, event, None), event


def test_right_cmd_tap_emits_primary_down_and_up(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events)

    down_result, down_event = _rcmd(monitor, True)
    assert down_result is down_event  # modifier change passes through
    assert events == []
    up_result, up_event = _rcmd(monitor, False)
    assert up_result is up_event
    assert events == ["primary_down", "primary_up"]


def test_right_cmd_used_as_modifier_does_not_fire(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events)
    c_key = _KeyEvent(8, mac_integration.COMMAND_FLAG_MASK)  # Cmd+C

    _rcmd(monitor, True)
    result = monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, c_key, None)
    _rcmd(monitor, False)

    assert result is c_key  # Cmd+C reaches the focused app untouched
    assert events == []


def test_right_cmd_space_enters_hands_free(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events)
    space = _KeyEvent(mac_integration.SPACE_KEYCODE, mac_integration.COMMAND_FLAG_MASK)

    _rcmd(monitor, True)
    result = monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, space, None)
    _rcmd(monitor, False)

    assert result is None
    assert events == ["hands_free"]


def test_focus_context_pastes_when_the_app_exposes_no_focused_element(monkeypatch) -> None:
    """AX silence means paste, not fall back.

    ChatGPT answers kAXFocusedUIElementAttribute with kAXErrorNoValue however
    its composer is focused, so treating "no answer" as "not a text field"
    sends every dictation aimed at it to the overlay instead of the caret.
    """

    class _App:
        def localizedName(self):
            return "ChatGPT"

        def processIdentifier(self):
            return 4242

    class _Workspace:
        @staticmethod
        def sharedWorkspace():
            return _Workspace()

        def frontmostApplication(self):
            return _App()

    monkeypatch.setattr(mac_integration, "NSWorkspace", _Workspace)
    monkeypatch.setattr(
        mac_integration.ApplicationServices,
        "AXUIElementCreateApplication",
        lambda pid: object(),
    )
    monkeypatch.setattr(
        mac_integration.ApplicationServices,
        "AXUIElementCopyAttributeValue",
        lambda element, attribute, placeholder: (-25212, None),
    )

    context = mac_integration.capture_focus_context()

    assert context.app_name == "ChatGPT"
    assert context.focused_role == ""
    assert context.can_insert_text is True
