from __future__ import annotations

from types import SimpleNamespace

from typeless_local import keyboard_layout, mac_integration


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
    assert mac_integration._focused_element_accepts_text(object(), "AXWebArea") is True








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


def test_paste_text_leaves_the_text_on_the_clipboard(monkeypatch) -> None:
    events = []

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
    monkeypatch.setattr(mac_integration.Quartz, "CGEventSourceCreate", lambda state: object())
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventCreateKeyboardEvent",
        lambda source, keycode, down: {"keycode": keycode, "down": down},
    )
    monkeypatch.setattr(mac_integration.Quartz, "CGEventSetFlags", lambda event, flags: None)
    monkeypatch.setattr(mac_integration.Quartz, "CGEventPost", lambda tap, event: events.append(("post", event)))

    mac_integration.paste_text("Hello")

    # Nothing is put back after the Cmd+V: an app slower than the restore
    # used to paste the old clipboard instead of the dictation.
    assert events[:2] == ["clear", ("set", "Hello", mac_integration.NSPasteboardTypeString)]
    assert events[2][0] == "post" and events[2][1]["keycode"] == keyboard_layout.QWERTY["v"]
    assert "clear" not in events[2:]


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
    def __init__(self, keycode: int, flags: int = 0, at: float = 0.0) -> None:
        self.keycode = keycode
        self.flags = flags
        self.at = at


def _rcmd_monitor(monkeypatch, events, **kwargs):
    monitor = mac_integration.GlobalHotkeyMonitor(events.append, **kwargs)
    # The hold timer only fires when a test says the time has passed.
    monitor.pending = []
    monkeypatch.setattr(monitor, "_after", lambda delay, fn: monitor.pending.append(fn))
    monkeypatch.setattr(
        mac_integration.Quartz, "CGEventGetIntegerValueField", lambda event, field: event.keycode
    )
    monkeypatch.setattr(mac_integration.Quartz, "CGEventGetFlags", lambda event: event.flags)
    monkeypatch.setattr(monitor, "_event_time", lambda event: event.at)
    monkeypatch.setattr(mac_integration, "secure_input_enabled", lambda: False)
    return monitor


RCMD_DOWN = mac_integration.COMMAND_FLAG_MASK | mac_integration.RIGHT_COMMAND_DEVICE_MASK


def _rcmd(monitor, down: bool, at: float = 0.0, extra: int = 0):
    event = _KeyEvent(mac_integration.RIGHT_COMMAND_KEYCODE, (RCMD_DOWN if down else 0) | extra, at)
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


def _hold_time_passes(monitor) -> None:
    for fn in monitor.pending:
        fn()
    monitor.pending.clear()


def test_right_cmd_held_alone_is_hold_to_talk(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events)

    _rcmd(monitor, True, at=10.0)
    _hold_time_passes(monitor)
    assert events == ["hold_start"] and monitor.last_primary_down_at == 10.0
    _rcmd(monitor, False, at=12.5)

    assert events == ["hold_start", "hold_end"]
    assert monitor.last_primary_up_at == 12.5


def test_a_key_during_a_right_cmd_hold_makes_it_a_modifier(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events)
    c_key = _KeyEvent(8, mac_integration.COMMAND_FLAG_MASK)  # a slow Cmd+C

    _rcmd(monitor, True, at=10.0)
    _hold_time_passes(monitor)
    result = monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, c_key, None)
    _rcmd(monitor, False, at=11.0)

    assert result is c_key
    assert events == ["hold_start", "hold_abort"]  # the app drops the recording this hold started


def test_a_stale_hold_timer_does_nothing(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events)

    _rcmd(monitor, True, at=10.0)
    _rcmd(monitor, False, at=10.1)  # a tap
    _rcmd(monitor, True, at=10.3)
    stale = monitor.pending.pop(0)
    stale()  # the first press's timer, firing during the second press

    assert events == ["primary_down", "primary_up"]


def test_f5_passes_through_when_turned_off(monkeypatch) -> None:
    events = []
    use_f5 = [False]
    monitor = _rcmd_monitor(monkeypatch, events, use_f5_fn=lambda: use_f5[0])

    for keycode in mac_integration.PRIMARY_KEYCODES:
        down, up = _KeyEvent(keycode), _KeyEvent(keycode)
        assert monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, down, None) is down
        assert monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyUp, up, None) is up
    assert events == []

    use_f5[0] = True
    assert monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, _KeyEvent(96), None) is None
    assert events == ["primary_down"]


def test_right_cmd_with_another_modifier_or_a_click_does_not_fire(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events)
    shift = _KeyEvent(60, mac_integration.COMMAND_FLAG_MASK | mac_integration.SHIFT_FLAG_MASK)

    _rcmd(monitor, True)
    assert monitor._handle_event(None, mac_integration.Quartz.kCGEventFlagsChanged, shift, None) is shift
    _rcmd(monitor, False)
    _rcmd(monitor, True)
    monitor._disarm_right_command()  # what the mouse monitor does on a Cmd-click
    _rcmd(monitor, False)

    assert events == []


def test_right_cmd_space_locks_a_recording(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events, is_active_fn=lambda: True)
    space = _KeyEvent(mac_integration.SPACE_KEYCODE, mac_integration.COMMAND_FLAG_MASK)

    _rcmd(monitor, True)
    result = monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, space, None)
    _rcmd(monitor, False)

    assert result is None
    assert events == ["hands_free"]


def test_right_cmd_space_from_idle_stays_cmd_space(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events, is_active_fn=lambda: False)
    space = _KeyEvent(mac_integration.SPACE_KEYCODE, mac_integration.COMMAND_FLAG_MASK)

    _rcmd(monitor, True)
    assert monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, space, None) is space  # Spotlight
    _rcmd(monitor, False)

    assert events == []


def test_releasing_after_the_hold_time_but_before_its_timer_is_still_a_tap(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events)

    _rcmd(monitor, True, at=10.0)
    _rcmd(monitor, False, at=10.5)  # the main thread was busy; the timer has not run

    assert events == ["primary_down", "primary_up"]


def test_right_cmd_is_not_armed_with_left_cmd_down_or_under_secure_input(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events)

    _rcmd(monitor, True, extra=0x08)  # left Cmd already down
    _rcmd(monitor, False, extra=mac_integration.COMMAND_FLAG_MASK | 0x08)
    monkeypatch.setattr(mac_integration, "secure_input_enabled", lambda: True)
    _rcmd(monitor, True)
    _rcmd(monitor, False)

    assert events == []


def test_right_cmd_released_while_left_cmd_stays_down_is_not_a_new_press(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events)

    _rcmd(monitor, True)
    _rcmd(monitor, False)  # a tap
    # Left Cmd still down: the Command bit stays set, the right-Cmd bit does not.
    _rcmd(monitor, False, extra=mac_integration.COMMAND_FLAG_MASK | 0x08)

    assert events == ["primary_down", "primary_up"]


def test_right_cmd_can_be_turned_off(monkeypatch) -> None:
    events = []
    monitor = _rcmd_monitor(monkeypatch, events, use_right_command_fn=lambda: False)

    _rcmd(monitor, True)
    _hold_time_passes(monitor)
    _rcmd(monitor, False)

    assert events == []


def test_f5_turned_off_mid_press_still_releases_it(monkeypatch) -> None:
    events = []
    use_f5 = [True]
    monitor = _rcmd_monitor(monkeypatch, events, use_f5_fn=lambda: use_f5[0])
    space = _KeyEvent(mac_integration.SPACE_KEYCODE)

    monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, _KeyEvent(96), None)
    use_f5[0] = False
    monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyUp, _KeyEvent(96), None)

    assert events == ["primary_down", "primary_up"]
    assert monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, space, None) is space


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


class _TypedEvent:
    def __init__(self, keycode: int, flags: int = 0, user_data: int = 0) -> None:
        self.keycode = keycode
        self.flags = flags
        self.user_data = user_data


def _watching_monitor(monkeypatch, events, *, watching=True, active=False):
    monitor = mac_integration.GlobalHotkeyMonitor(
        events.append, is_active_fn=lambda: active, watch_keys_fn=lambda: watching
    )
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventGetIntegerValueField",
        lambda event, field: event.user_data if field == mac_integration._USER_DATA_FIELD else event.keycode,
    )
    monkeypatch.setattr(mac_integration.Quartz, "CGEventGetFlags", lambda event: event.flags)
    return monitor


def _key(monitor, event):
    return monitor._handle_event(None, mac_integration.Quartz.kCGEventKeyDown, event, None)


def test_typing_after_a_paste_is_reported_and_still_reaches_the_app(monkeypatch) -> None:
    events = []
    monitor = _watching_monitor(monkeypatch, events)
    a_key = _TypedEvent(0)

    assert _key(monitor, a_key) is a_key
    assert events == ["typed"]


def test_keys_are_not_reported_when_nothing_is_watching(monkeypatch) -> None:
    events = []
    monitor = _watching_monitor(monkeypatch, events, watching=False)
    assert _key(monitor, _TypedEvent(0)) is not None
    assert events == []


def test_cmd_z_is_reported_as_undo_and_shift_cmd_z_as_typing(monkeypatch) -> None:
    events = []
    monitor = _watching_monitor(monkeypatch, events)
    cmd = mac_integration.COMMAND_FLAG_MASK

    _key(monitor, _TypedEvent(keyboard_layout.QWERTY["z"], cmd))
    _key(monitor, _TypedEvent(keyboard_layout.QWERTY["z"], cmd | mac_integration.SHIFT_FLAG_MASK))

    assert events == ["undo", "typed"]


def test_cmd_z_is_found_where_the_layout_puts_z(monkeypatch) -> None:
    """On AZERTY, Z is the key QWERTY calls W; the key at QWERTY's Z is W there."""
    events = []
    monitor = _watching_monitor(monkeypatch, events)
    monkeypatch.setattr(keyboard_layout, "_codes", {"v": 9, "z": 13})
    cmd = mac_integration.COMMAND_FLAG_MASK

    _key(monitor, _TypedEvent(13, cmd))
    _key(monitor, _TypedEvent(6, cmd))

    assert events == ["undo", "typed"]


def test_paste_and_undo_press_the_layouts_own_v_and_z(monkeypatch) -> None:
    posted = []
    monkeypatch.setattr(keyboard_layout, "_codes", {"v": 47, "z": 44})  # Dvorak
    pasteboard = SimpleNamespace(clearContents=lambda: None, setString_forType_=lambda text, kind: None)
    monkeypatch.setattr(mac_integration, "NSPasteboard", SimpleNamespace(generalPasteboard=lambda: pasteboard))
    monkeypatch.setattr(mac_integration.Quartz, "CGEventSourceCreate", lambda state: object())
    monkeypatch.setattr(
        mac_integration.Quartz, "CGEventCreateKeyboardEvent", lambda source, keycode, down: {"keycode": keycode, "down": down}
    )
    monkeypatch.setattr(mac_integration.Quartz, "CGEventSetFlags", lambda event, flags: None)
    monkeypatch.setattr(mac_integration.Quartz, "CGEventPost", lambda tap, event: posted.append(event["keycode"]))

    mac_integration.paste_text("Hi")
    mac_integration.undo_last_edit()

    assert posted == [47, 47, 44, 44]


def test_the_apps_own_paste_and_undo_are_not_mistaken_for_typing(monkeypatch) -> None:
    events = []
    monitor = _watching_monitor(monkeypatch, events)
    ours = _TypedEvent(
        keyboard_layout.QWERTY["v"], mac_integration.COMMAND_FLAG_MASK, mac_integration.SYNTHETIC_EVENT_TAG
    )

    assert _key(monitor, ours) is ours
    assert events == []


def test_escape_passes_through_when_idle_and_counts_as_typing(monkeypatch) -> None:
    events = []
    monitor = _watching_monitor(monkeypatch, events)
    esc = _TypedEvent(mac_integration.ESCAPE_KEYCODE)

    assert _key(monitor, esc) is esc
    assert events == ["typed"]


def test_escape_cancels_and_is_swallowed_while_dictating(monkeypatch) -> None:
    events = []
    monitor = _watching_monitor(monkeypatch, events, watching=False, active=True)

    assert _key(monitor, _TypedEvent(mac_integration.ESCAPE_KEYCODE)) is None
    assert events == ["cancel"]


def test_paste_and_undo_events_carry_the_apps_tag(monkeypatch) -> None:
    tagged, posted = [], []
    monkeypatch.setattr(mac_integration.Quartz, "CGEventSourceCreate", lambda state: object())
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventCreateKeyboardEvent",
        lambda source, keycode, down: {"keycode": keycode, "down": down},
    )
    monkeypatch.setattr(mac_integration.Quartz, "CGEventSetFlags", lambda event, flags: None)
    monkeypatch.setattr(
        mac_integration.Quartz,
        "CGEventSetIntegerValueField",
        lambda event, field, value: tagged.append((event["keycode"], field, value)),
    )
    monkeypatch.setattr(mac_integration.Quartz, "CGEventPost", lambda tap, event: posted.append(event))

    mac_integration.undo_last_edit()

    tag = (keyboard_layout.QWERTY["z"], mac_integration._USER_DATA_FIELD, mac_integration.SYNTHETIC_EVENT_TAG)
    assert tagged == [tag, tag]
    assert [event["down"] for event in posted] == [True, False]


def test_caret_rect_turns_ax_coordinates_into_screen_coordinates(monkeypatch) -> None:
    from types import SimpleNamespace

    AS = mac_integration.ApplicationServices
    rect = SimpleNamespace(origin=SimpleNamespace(x=400.0, y=300.0), size=SimpleNamespace(width=2.0, height=18.0))
    monkeypatch.setattr(mac_integration, "frontmost_pid", lambda: 4242)
    monkeypatch.setattr(AS, "AXUIElementCreateApplication", lambda pid: "app")
    monkeypatch.setattr(mac_integration, "_copy_ax_attribute", lambda element, attribute: "value")
    monkeypatch.setattr(AS, "AXUIElementCopyParameterizedAttributeValue", lambda *args: (AS.kAXErrorSuccess, "bounds"))
    monkeypatch.setattr(AS, "AXValueGetValue", lambda value, kind, out: (True, rect))
    screen = SimpleNamespace(frame=lambda: SimpleNamespace(size=SimpleNamespace(width=1440.0, height=900.0)))
    import AppKit

    monkeypatch.setattr(AppKit, "NSScreen", SimpleNamespace(screens=lambda: [screen]), raising=False)

    # 300 from the top of a 900-high display, 18 high: its bottom is 582 up from the bottom.
    assert mac_integration.caret_rect() == (400.0, 582.0, 2.0, 18.0)


def test_caret_rect_ignores_an_empty_answer(monkeypatch) -> None:
    from types import SimpleNamespace

    AS = mac_integration.ApplicationServices
    empty = SimpleNamespace(origin=SimpleNamespace(x=0.0, y=0.0), size=SimpleNamespace(width=0.0, height=0.0))
    monkeypatch.setattr(mac_integration, "frontmost_pid", lambda: 4242)
    monkeypatch.setattr(AS, "AXUIElementCreateApplication", lambda pid: "app")
    monkeypatch.setattr(mac_integration, "_copy_ax_attribute", lambda element, attribute: "value")
    monkeypatch.setattr(AS, "AXUIElementCopyParameterizedAttributeValue", lambda *args: (AS.kAXErrorSuccess, "bounds"))
    monkeypatch.setattr(AS, "AXValueGetValue", lambda value, kind, out: (True, empty))

    assert mac_integration.caret_rect() is None


class _FakeAX:
    """Just enough of ApplicationServices for reading the text before the caret."""

    kAXErrorSuccess = 0
    kAXSelectedTextRangeAttribute = "AXSelectedTextRange"
    kAXValueAttribute = "AXValue"
    kAXStringForRangeParameterizedAttribute = "AXStringForRange"

    def __init__(self, value: str, caret: int, ranged: bool = True, subrole: str = "") -> None:
        self.value, self.caret, self.ranged, self.subrole = value, caret, ranged, subrole
        self.asked: list[tuple[int, int]] = []
        self.read_whole = False

    def AXUIElementCopyAttributeValue(self, element, attribute, _):  # noqa: N802
        if attribute == "AXSubrole":
            return (0, self.subrole or None)
        if attribute == "AXSelectedTextRange":
            return (0, ("range", self.caret, 0))
        if attribute == "AXValue":
            self.read_whole = True
            return (0, self.value)
        return (-25212, None)

    def AXValueCreate(self, kind, value):  # noqa: N802
        return ("range", *value)

    def AXValueGetValue(self, value, kind, _):  # noqa: N802
        return (True, (value[1], value[2]))

    def AXUIElementCopyParameterizedAttributeValue(self, element, attribute, value, _):  # noqa: N802
        if not self.ranged:
            return (-25205, None)
        start, length = value[1], value[2]
        self.asked.append((start, length))
        return (0, self.value[start : start + length])


def test_text_before_caret_asks_only_for_the_last_stretch(monkeypatch) -> None:
    text = "旧" * 1000 + "昨天 Sonnet 限流了。"
    fake = _FakeAX(text, caret=len(text))
    monkeypatch.setattr(mac_integration, "ApplicationServices", fake)

    before = mac_integration._text_before_caret(object(), "AXTextArea")

    assert before.endswith("昨天 Sonnet 限流了。")
    assert len(before) == mac_integration.BEFORE_TEXT_CHARS
    assert fake.asked == [(len(text) - mac_integration.BEFORE_TEXT_CHARS, mac_integration.BEFORE_TEXT_CHARS)]
    assert not fake.read_whole


def test_text_before_caret_stops_at_the_caret_when_apps_lack_ranged_queries(monkeypatch) -> None:
    fake = _FakeAX("回复 Codex 的问题|后面的字", caret=len("回复 Codex 的问题"), ranged=False)
    monkeypatch.setattr(mac_integration, "ApplicationServices", fake)

    assert mac_integration._text_before_caret(object(), "AXTextArea") == "回复 Codex 的问题"


def test_text_before_caret_never_reads_password_fields(monkeypatch) -> None:
    fake = _FakeAX("hunter2", caret=7)
    monkeypatch.setattr(mac_integration, "ApplicationServices", fake)

    assert mac_integration._text_before_caret(object(), "AXSecureTextField") == ""
    fake.subrole = "AXSecureTextField"
    assert mac_integration._text_before_caret(object(), "AXTextField") == ""
    assert fake.asked == [] and not fake.read_whole


def test_text_before_caret_is_empty_at_the_start_of_a_field(monkeypatch) -> None:
    fake = _FakeAX("", caret=0)
    monkeypatch.setattr(mac_integration, "ApplicationServices", fake)

    assert mac_integration._text_before_caret(object(), "AXTextArea") == ""


def test_capture_focus_context_leaves_the_field_unread_unless_asked(monkeypatch) -> None:
    read = []
    monkeypatch.setattr(mac_integration, "_text_before_caret", lambda element, role: read.append(role) or "上文")
    app = SimpleNamespace(localizedName=lambda: "Notes", processIdentifier=lambda: 42)
    workspace = SimpleNamespace(frontmostApplication=lambda: app)
    monkeypatch.setattr(mac_integration, "NSWorkspace", SimpleNamespace(sharedWorkspace=lambda: workspace))
    monkeypatch.setattr(mac_integration.ApplicationServices, "AXUIElementCreateApplication", lambda pid: object())
    monkeypatch.setattr(
        mac_integration,
        "_copy_ax_attribute",
        lambda element, attribute: "AXTextArea" if attribute == mac_integration.ApplicationServices.kAXRoleAttribute else object(),
    )

    assert mac_integration.capture_focus_context().before_text == ""
    assert read == []
    assert mac_integration.capture_focus_context(read_before_text=True).before_text == "上文"
    assert read == ["AXTextArea"]
