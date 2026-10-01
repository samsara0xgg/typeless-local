from __future__ import annotations

from unittest.mock import MagicMock

from typeless_local import brand
from typeless_local.menubar import (
    BADGE_RECT,
    GLYPH_SIZE,
    LOOK,
    MenuBarIcon,
    Preset,
    Recent,
    Snapshot,
    ago,
    badge_frame,
    build_menu,
    clip,
    frame,
    glyph_shapes,
)


def _titles(items):
    return [item.title for item in items if item.kind != "separator"]


def _find(items, title):
    return next(item for item in items if item.title == title)


def test_every_app_state_has_a_look() -> None:
    for state in ("idle", "starting", "recording", "processing"):
        assert state in LOOK
    assert LOOK["recording"] == "rec" and LOOK["processing"] == "busy"


def test_set_state_clamps_unknown_states_to_idle() -> None:
    icon = MenuBarIcon(on_action=MagicMock())
    icon.set_state("recording")
    assert icon.current_state == "recording"
    icon.set_state("error")
    assert icon.current_state == "idle"


def test_issues_keep_their_priority_order() -> None:
    icon = MenuBarIcon(on_action=MagicMock())
    icon.set_issues(["key", "perm", "bogus"])
    assert icon.issues == ("perm", "key")


def test_glyph_stays_inside_its_image() -> None:
    width, height = GLYPH_SIZE
    for shape in glyph_shapes(dot=True):
        kind, x, y, w, h = shape[:5]
        pad = shape[6] / 2 if kind == "stroke" else 0.0
        assert x - pad >= 0 and y - pad >= 0
        assert x + w + pad <= width and y + h + pad <= height
    assert len(glyph_shapes(dot=True)) == len(glyph_shapes()) + 1


def test_badge_sits_over_the_glyph_corner_in_either_orientation() -> None:
    x, y, w, h = badge_frame(24.0, 24.0, flipped=True)
    assert (x, y) == (3.0 + BADGE_RECT[0], 1.0 + BADGE_RECT[1])
    _, y_up, _, _ = badge_frame(24.0, 24.0, flipped=False)
    assert y_up == 24.0 - y - h


def test_frames_breathe_blink_and_hold_still_for_reduce_motion() -> None:
    assert frame("idle", 3.3) == (1.0, False)
    assert frame("rec", 0.1) == (1.0, True)
    assert frame("rec", 0.6) == (1.0, False)
    assert frame("rec", 0.6, reduce_motion=True) == (1.0, True)
    peak, _ = frame("busy", 0.0)
    trough, _ = frame("busy", 0.6)
    assert round(peak, 3) == 1.0 and round(trough, 3) == 0.4
    assert frame("busy", 0.6, reduce_motion=True) == (0.6, False)


def test_ago_and_clip() -> None:
    assert ago(5) == "刚刚"
    assert ago(125) == "2 分钟前"
    assert ago(7300) == "2 小时前"
    assert ago(200000) == "2 天前"
    assert clip("短") == "短"
    long = "一" * 50
    assert clip(long) == "一" * 39 + "…"
    assert clip("a\n  b") == "a b"


def test_idle_menu_follows_the_design() -> None:
    items = build_menu(
        Snapshot(
            recent=Recent("明天下午四点开会", app="备忘录", at=1000.0),
            presets=(Preset("gpt-5.6-terra", median_ms=1240), Preset("deepseek", needs_key=True)),
            active_preset="gpt-5.6-terra",
            inputs=("MacBook Pro 麦克风", "AirPods"),
            active_input="AirPods",
        ),
        now=1130.0,
    )
    assert _titles(items) == [
        brand.DISPLAY_NAME,
        "轻点右 ⌘ 开始 · 连点两下锁定",
        "开始听写",
        "锁定听写",
        "最近一次",
        "明天下午四点开会",
        "润色与 API Key…",
        "输入设备",
        "词库…",
        "历史记录…",
        "设置…",
        brand.quit_label(),
    ]
    assert items[0].subtitle == "就绪"
    recent = _find(items, "明天下午四点开会")
    assert recent.key == "copy" and recent.subtitle == "2 分钟前 · 备忘录 · 点按复制"
    # One model for everyone, never named: the row says whose key pays and opens its settings.
    models = _find(items, "润色与 API Key…")
    assert models.badge == "你的 Key" and models.key == "settings:model" and not models.children
    inputs = _find(items, "输入设备")
    assert inputs.badge == "AirPods"
    assert [(i.title, i.key, i.checked) for i in inputs.children] == [
        ("系统默认", "input:", False),
        ("MacBook Pro 麦克风", "input:MacBook Pro 麦克风", False),
        ("AirPods", "input:AirPods", True),
    ]
    assert _find(items, "开始听写").shortcut == ""  # right ⌘ has no menu key equivalent
    assert _find(items, "历史记录…").shortcut == "⌘Y"
    assert _find(items, brand.quit_label()).key == "quit"


def test_menu_while_recording_offers_to_stop() -> None:
    items = build_menu(Snapshot(state="recording"))
    assert items[0].subtitle == "正在听写"
    stop = _find(items, "结束听写")
    assert stop.key == "toggle" and stop.enabled
    assert not _find(items, "锁定听写").enabled
    assert not _find(items, "还没有听写").enabled


def test_menu_while_processing_cannot_start_another() -> None:
    items = build_menu(Snapshot(state="processing"))
    assert not _find(items, "开始听写").enabled


def test_issues_put_their_fixes_at_the_top() -> None:
    items = build_menu(Snapshot(issues=("key", "perm")))
    assert items[0].subtitle == "没有辅助功能权限，快捷键不起作用"
    fixes = [item.key for item in items if item.key.startswith("fix:")]
    assert fixes == ["fix:perm", "fix:key"]


def test_an_unplugged_device_falls_back_to_the_system_default() -> None:
    items = build_menu(Snapshot(inputs=("MacBook Pro 麦克风",), active_input="Yeti"))
    inputs = _find(items, "输入设备")
    assert inputs.badge == "系统默认"
    assert inputs.children[0].checked


def test_refine_off_shows_in_the_model_row() -> None:
    items = build_menu(Snapshot(presets=(Preset("a"),), active_preset="a", refine=False))
    assert _find(items, "润色与 API Key…").badge == "关闭"
    assert _find(build_menu(Snapshot(active_preset="free-trial")), "润色与 API Key…").badge == "免费试用"


def test_perform_passes_the_key_and_swallows_errors() -> None:
    action = MagicMock(side_effect=[None, RuntimeError("boom")])
    icon = MenuBarIcon(on_action=action)
    icon.perform("preset:a")
    icon.perform("quit")
    icon.perform("")
    assert [call.args[0] for call in action.call_args_list] == ["preset:a", "quit"]


def test_items_survive_a_failing_snapshot() -> None:
    icon = MenuBarIcon(on_action=MagicMock(), snapshot=MagicMock(side_effect=RuntimeError))
    icon.set_state("recording")
    assert _find(icon.items(), "结束听写")


def test_the_menu_shows_todays_usage_and_opens_the_usage_pane() -> None:
    items = build_menu(Snapshot(usage="今天 23 次 · 约 $0.04"))
    titles = _titles(items)
    assert titles.index("今天 23 次 · 约 $0.04") == titles.index("历史记录…") + 1
    assert _find(items, "今天 23 次 · 约 $0.04").key == "settings:usage"
    assert "今天" not in " ".join(_titles(build_menu(Snapshot())))


def test_the_menu_speaks_english_when_asked() -> None:
    from typeless_local import i18n

    i18n.use("en")
    items = build_menu(Snapshot(issues=("key",), presets=(Preset("mini", needs_key=True),), active_preset="mini"))
    titles = [item.title for item in items]
    assert titles[0] == brand.ENGLISH_NAME
    assert items[0].subtitle == "No API key: raw transcripts only"
    assert "Start Dictation" in titles and "Settings…" in titles and f"Quit {brand.ENGLISH_NAME}" in titles
    model = next(item for item in items if item.title == "Refinement and API Key…")
    assert model.key == "settings:model"
    assert ago(125) == "2 min ago" and ago(200000) == "2 days ago"
