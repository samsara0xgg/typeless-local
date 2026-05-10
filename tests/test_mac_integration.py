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


def test_fn_flags_changed_emits_down_and_up(monkeypatch) -> None:
    events = []
    monitor = mac_integration.GlobalHotkeyMonitor(events.append)
    flags = iter([mac_integration.FN_FLAG_MASK, 0])
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventGetIntegerValueField",
        lambda event, field: mac_integration.FN_KEYCODE,
    )
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventGetFlags",
        lambda event: next(flags),
    )

    down_result = monitor._handle_event(
        None,
        mac_integration.Quartz.kCGEventFlagsChanged,
        object(),
        None,
    )
    up_result = monitor._handle_event(
        None,
        mac_integration.Quartz.kCGEventFlagsChanged,
        object(),
        None,
    )

    assert down_result is None
    assert up_result is None
    assert events == ["primary_down", "primary_up"]


def test_fn_key_events_are_swallowed(monkeypatch) -> None:
    monitor = mac_integration.GlobalHotkeyMonitor(lambda action: None)
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventGetIntegerValueField",
        lambda event, field: mac_integration.FN_KEYCODE,
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


def test_paste_text_restores_clipboard_snapshot(monkeypatch) -> None:
    events = []
    restored = []

    class FakePasteboard:
        def clearContents(self):
            events.append("clear")

        def setString_forType_(self, text, item_type):
            events.append(("set", text, item_type))

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
