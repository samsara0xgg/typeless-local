"""The menu-bar item: the 言 glyph and the app's menu.

The glyph is drawn at runtime as a template image, so macOS tints it for light
and dark menu bars like its own icons. It has four looks: idle, recording (a
blinking dot under the mouth), working (the glyph breathes) and needs
attention (an orange badge, for what only the user can fix). A failed
dictation does not change the icon: the capsule already said so.

The menu is rebuilt from ``build_menu`` every time it opens, so the devices,
the last dictation and which models lack a key are always current. Building it
is plain Python and tested; only ``_fill`` touches AppKit.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import threading
import time
from typing import Callable, Literal

from typeless_local import brand

LOGGER = logging.getLogger(__name__)

State = Literal["idle", "starting", "recording", "processing"]

# How the icon looks in each app state.
LOOK: dict[str, str] = {"idle": "idle", "starting": "rec", "recording": "rec", "processing": "busy"}
STATE_LABEL: dict[str, str] = {
    "idle": "就绪",
    "starting": "正在打开麦克风…",
    "recording": "正在听写",
    "processing": "正在转写和润色…",
}
HINT = "按 F5 或右 ⌘ 开始 · 连按两下锁定"

# What needs the user, most blocking first: (what is wrong, the menu item that fixes it).
ISSUES: dict[str, tuple[str, str]] = {
    "perm": ("没有辅助功能权限，快捷键不起作用", "授予辅助功能权限…"),
    "mic": ("不能使用麦克风", "允许使用麦克风…"),
    "key": ("缺少 API Key，只能贴原文", "填写 API Key…"),
}
SYSTEM_DEFAULT = "系统默认"
RECENT_CHARS = 40

# ---------------------------------------------------------------- the glyph
# Drawn in a flipped 18 x 22 pt image: the 18 pt glyph box sits 2 pt down, so
# it stays centred like any other menu-bar icon and the recording dot has room
# under it. Shapes are (kind, x, y, w, h[, radius[, line width]]).
GLYPH_SIZE = (18.0, 22.0)
_TOP = 2.0
_GLYPH = (
    ("oval", 7.8, 1.2 + _TOP, 2.4, 2.4),  # the dot
    ("fill", 2.6, 4.4 + _TOP, 12.8, 1.6, 0.8),  # three strokes of text
    ("fill", 4.4, 7.2 + _TOP, 9.2, 1.5, 0.75),
    ("fill", 4.4, 9.8 + _TOP, 9.2, 1.5, 0.75),
    ("stroke", 4.9, 12.6 + _TOP, 8.2, 4.2, 1.5, 1.4),  # the mouth
)
_REC_DOT = ("oval", 8.0, 20.0, 2.0, 2.0)
# The orange badge, in the same coordinates: above the top stroke, clear of the dot.
BADGE_RECT = (13.7, 1.1, 5.0, 5.0)


def glyph_shapes(dot: bool = False) -> tuple:
    return _GLYPH + ((_REC_DOT,) if dot else ())


def frame(look: str, t: float, reduce_motion: bool = False) -> tuple[float, bool]:
    """(icon opacity, recording dot shown) for ``look`` at ``t`` seconds."""

    if look == "busy":
        if reduce_motion:
            return 0.6, False
        return 0.4 + 0.6 * (0.5 + 0.5 * math.cos(2 * math.pi * t / 1.2)), False
    if look == "rec":
        return 1.0, reduce_motion or (t % 1.0) < 0.5
    return 1.0, False


# ----------------------------------------------------------------- the menu


@dataclass(frozen=True)
class Item:
    title: str = ""
    key: str = ""  # what choosing it does; "" is not clickable
    kind: str = "item"  # item | header | hint | section | separator
    shortcut: str = ""  # "F5", "⌘Y", "⌘,", "⌘Q"
    badge: str = ""  # secondary text at the trailing edge
    subtitle: str = ""
    checked: bool = False
    enabled: bool = True
    children: tuple = ()
    symbol: str = ""  # SF Symbol shown before the title


SEPARATOR = Item(kind="separator")


@dataclass(frozen=True)
class Recent:
    text: str
    app: str = ""
    at: float = 0.0


@dataclass(frozen=True)
class Preset:
    name: str
    needs_key: bool = False
    median_ms: int | None = None


@dataclass(frozen=True)
class Snapshot:
    state: str = "idle"
    issues: tuple[str, ...] = ()
    recent: Recent | None = None
    presets: tuple[Preset, ...] = ()
    active_preset: str = ""
    inputs: tuple[str, ...] = ()
    active_input: str = ""
    refine: bool = True
    usage: str = ""  # "今天 23 次 · 约 $0.04"; "" when history is off


def ago(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)} 分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)} 小时前"
    return f"{int(seconds // 86400)} 天前"


def clip(text: str, limit: int = RECENT_CHARS) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def ordered_issues(issues) -> tuple[str, ...]:
    return tuple(name for name in ISSUES if name in set(issues or ()))


def build_menu(snap: Snapshot, now: float | None = None) -> list[Item]:
    now = time.time() if now is None else now
    issues = ordered_issues(snap.issues)
    status = ISSUES[issues[0]][0] if issues and snap.state == "idle" else STATE_LABEL.get(snap.state, "")
    items = [Item(brand.DISPLAY_NAME, kind="header", subtitle=status), Item(HINT, kind="hint"), SEPARATOR]
    if issues:
        items += [Item(ISSUES[name][1], key=f"fix:{name}", symbol="exclamationmark.triangle") for name in issues]
        items.append(SEPARATOR)

    idle = snap.state == "idle"
    if snap.state in ("starting", "recording"):
        items.append(Item("结束听写", key="toggle", shortcut="F5", symbol="stop.circle"))
    else:
        items.append(Item("开始听写", key="toggle", shortcut="F5", enabled=idle, symbol="mic"))
    items += [Item("锁定听写", key="latch", badge="右⌘ Space", enabled=idle, symbol="lock"), SEPARATOR]

    items.append(Item("最近一次", kind="section"))
    if snap.recent and snap.recent.text.strip():
        meta = [ago(now - snap.recent.at)] if snap.recent.at else []
        if snap.recent.app:
            meta.append(snap.recent.app)
        meta.append("点按复制")
        items.append(Item(clip(snap.recent.text), key="copy", subtitle=" · ".join(meta)))
    else:
        items.append(Item("还没有听写", enabled=False))
    items.append(SEPARATOR)

    if snap.presets:
        models = tuple(
            Item(
                preset.name,
                key=f"preset:{preset.name}",
                checked=preset.name == snap.active_preset,
                badge="需要 Key" if preset.needs_key else _seconds(preset.median_ms),
            )
            for preset in snap.presets
        ) + (SEPARATOR, Item("管理模型与 Key…", key="settings:model"))
        active = snap.active_preset if snap.refine else "关闭"
        items.append(Item("润色模型", badge=active, children=models, symbol="sparkles"))
    active_input = snap.active_input if snap.active_input in snap.inputs else ""
    inputs = (Item(SYSTEM_DEFAULT, key="input:", checked=not active_input),) + tuple(
        Item(name, key=f"input:{name}", checked=name == active_input) for name in snap.inputs
    )
    items += [
        Item("输入设备", badge=active_input or SYSTEM_DEFAULT, children=inputs, symbol="waveform"),
        Item("词库…", key="settings:vocab", symbol="book"),
        Item("历史记录…", key="history", shortcut="⌘Y", symbol="clock"),
    ]
    if snap.usage:
        items.append(Item(snap.usage, key="settings:usage", symbol="chart.bar"))
    items += [
        SEPARATOR,
        Item("设置…", key="settings:", shortcut="⌘,", symbol="gearshape"),
        Item(brand.quit_label(), key="quit", shortcut="⌘Q", symbol="power"),
    ]
    return items


def _seconds(ms: int | None) -> str:
    return f"{ms / 1000:.1f} 秒" if ms else ""


# --------------------------------------------------------------- the item


class MenuBarIcon:
    """The status item. ``set_state`` and ``set_issues`` are safe from any thread."""

    def __init__(
        self,
        on_action: Callable[[str], None],
        snapshot: Callable[[], Snapshot] | None = None,
    ) -> None:
        self._on_action = on_action
        self._snapshot = snapshot or Snapshot
        self.current_state: State = "idle"
        self.issues: tuple[str, ...] = ()
        self._lock = threading.Lock()
        self._status_item = None
        self._menu = None
        self._target = None
        self._badge = None
        self._images: dict[bool, object] = {}
        self._timer = None
        self._look = ""
        self._look_since = 0.0
        self._dot_shown = None

    # -------------------------------------------------------- public API

    def set_state(self, state: str) -> None:
        with self._lock:
            self.current_state = state if state in LOOK else "idle"
        self._call_after(self._apply)

    def set_issues(self, issues) -> None:
        with self._lock:
            self.issues = ordered_issues(issues)
        self._call_after(self._apply)

    def perform(self, key: str) -> None:
        """Run a menu item's action; exceptions are logged, never raised into AppKit."""

        if not key:
            return
        try:
            self._on_action(key)
        except Exception:
            LOGGER.warning("Menu action %s failed", key, exc_info=True)

    def items(self) -> list[Item]:
        try:
            snap = self._snapshot()
        except Exception:
            LOGGER.warning("Could not read the menu's state", exc_info=True)
            snap = Snapshot(state=self.current_state, issues=self.issues)
        return build_menu(snap)

    # ----------------------------------------------------------- AppKit

    def setup(self) -> None:
        """Create the status item. Main thread only."""

        from AppKit import NSMenu, NSStatusBar  # noqa: PLC0415

        item = NSStatusBar.systemStatusBar().statusItemWithLength_(-2)  # NSSquareStatusItemLength
        # Dragging the icon off the menu bar persists isVisible = false and
        # AppKit restores that on every launch; this is the only way back.
        item.setVisible_(True)
        self._target = _target(self)
        menu = NSMenu.alloc().initWithTitle_(brand.DISPLAY_NAME)
        menu.setAutoenablesItems_(False)
        menu.setDelegate_(self._target)
        item.setMenu_(menu)
        self._status_item = item
        self._menu = menu
        self._images = {dot: _glyph_image(dot) for dot in (False, True)}
        self._badge = _badge_view(item.button())
        self._apply()

    def rebuild(self, menu=None) -> None:
        """Refill the menu from the current state (menuNeedsUpdate:)."""

        menu = menu or self._menu
        if menu is None:
            return
        menu.removeAllItems()
        _fill(menu, self.items(), self._target)

    def _apply(self) -> None:
        if self._status_item is None:
            return
        button = self._status_item.button()
        look = LOOK.get(self.current_state, "idle")
        label = STATE_LABEL.get(self.current_state, "")
        issues = self.issues
        if issues and self.current_state == "idle":
            label = ISSUES[issues[0]][0]
        if look != self._look:
            self._look = look
            self._look_since = time.monotonic()
            self._dot_shown = None
            self._restart_timer(look)
        self._draw_frame()
        try:
            button.setToolTip_(f"{brand.DISPLAY_NAME} · {label}")
            button.setAccessibilityLabel_(f"{brand.DISPLAY_NAME}，{label}")
        except Exception:
            pass
        if self._badge is not None:
            _place_badge(self._badge, button)
            self._badge.setHidden_(not issues)

    def _draw_frame(self) -> None:
        if self._status_item is None:
            return
        button = self._status_item.button()
        alpha, dot = frame(self._look, time.monotonic() - self._look_since, _reduce_motion())
        if dot != self._dot_shown:
            self._dot_shown = dot
            image = self._images.get(dot)
            if image is not None:
                button.setImage_(image)
                button.setTitle_("")
            else:
                button.setTitle_("言")
        button.setAlphaValue_(alpha)

    def _restart_timer(self, look: str) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        if look == "idle" or _reduce_motion():
            return
        try:
            from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer  # noqa: PLC0415

            interval = 1 / 15 if look == "busy" else 0.5
            timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                interval, self._target, "tick:", None, True
            )
            # Common modes: the icon keeps moving while its menu is open.
            NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
            self._timer = timer
        except Exception:
            LOGGER.debug("Menu-bar animation unavailable", exc_info=True)

    @staticmethod
    def _call_after(callback) -> None:
        try:
            from PyObjCTools import AppHelper  # noqa: PLC0415

            AppHelper.callAfter(callback)
        except Exception:
            LOGGER.debug("Menu-bar update without AppKit", exc_info=True)


# ------------------------------------------------------------ AppKit helpers


def _reduce_motion() -> bool:
    try:
        from AppKit import NSWorkspace  # noqa: PLC0415

        return bool(NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
    except Exception:
        return False


def _draw_shapes(shapes) -> None:
    from AppKit import NSBezierPath, NSColor  # noqa: PLC0415
    from Foundation import NSMakeRect  # noqa: PLC0415

    NSColor.blackColor().set()
    for shape in shapes:
        kind, x, y, w, h = shape[:5]
        rect = NSMakeRect(x, y, w, h)
        if kind == "oval":
            NSBezierPath.bezierPathWithOvalInRect_(rect).fill()
            continue
        radius = shape[5]
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
        if kind == "stroke":
            path.setLineWidth_(shape[6])
            path.stroke()
        else:
            path.fill()


def _glyph_image(dot: bool):
    """The 言 glyph as a template image, drawn at whatever scale the screen needs."""

    try:
        from AppKit import NSImage  # noqa: PLC0415
        from Foundation import NSMakeSize  # noqa: PLC0415

        shapes = glyph_shapes(dot)
        size = NSMakeSize(*GLYPH_SIZE)

        def draw(_rect) -> bool:
            _draw_shapes(shapes)
            return True

        try:
            image = NSImage.imageWithSize_flipped_drawingHandler_(size, True, draw)
        except Exception:
            image = NSImage.alloc().initWithSize_(size)
            image.lockFocusFlipped_(True)
            _draw_shapes(shapes)
            image.unlockFocus()
        image.setTemplate_(True)
        image.setAccessibilityDescription_(brand.DISPLAY_NAME)
        return image
    except Exception:
        LOGGER.warning("Could not draw the menu-bar glyph; showing 言 as text", exc_info=True)
        return None


def _badge_view(button):
    try:
        from AppKit import NSColor, NSView  # noqa: PLC0415
        from Foundation import NSMakeRect  # noqa: PLC0415

        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, BADGE_RECT[2], BADGE_RECT[3]))
        view.setWantsLayer_(True)
        layer = view.layer()
        layer.setBackgroundColor_(NSColor.systemOrangeColor().CGColor())
        layer.setCornerRadius_(BADGE_RECT[2] / 2)
        view.setHidden_(True)
        button.addSubview_(view)
        return view
    except Exception:
        LOGGER.debug("No badge view", exc_info=True)
        return None


def badge_frame(width: float, height: float, flipped: bool) -> tuple[float, float, float, float]:
    """Where the badge goes in a button of this size, with the glyph centred in it."""

    x0 = (width - GLYPH_SIZE[0]) / 2
    y0 = (height - GLYPH_SIZE[1]) / 2
    x, y, w, h = BADGE_RECT
    top = y0 + y
    return (x0 + x, top if flipped else height - top - h, w, h)


def _place_badge(view, button) -> None:
    try:
        from Foundation import NSMakeRect  # noqa: PLC0415

        bounds = button.bounds()
        view.setFrame_(NSMakeRect(*badge_frame(bounds.size.width, bounds.size.height, bool(button.isFlipped()))))
    except Exception:
        LOGGER.debug("Could not place the badge", exc_info=True)


_SHORTCUTS = {"F5": ("", 0), "⌘Y": ("y", 1 << 20), "⌘,": (",", 1 << 20), "⌘Q": ("q", 1 << 20)}


def _fill(menu, items: list[Item], target) -> None:
    """Add ``items`` to an NSMenu, using the newer menu features where macOS has them."""

    from AppKit import NSMenu, NSMenuItem  # noqa: PLC0415

    for spec in items:
        if spec.kind == "separator":
            menu.addItem_(NSMenuItem.separatorItem())
            continue
        if spec.kind == "section":
            menu.addItem_(_section(spec.title))
            continue
        key_equivalent, modifiers = _SHORTCUTS.get(spec.shortcut, ("", None))
        title = spec.title
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, "menuAction:" if spec.key else None, key_equivalent
        )
        if modifiers is not None:
            item.setKeyEquivalentModifierMask_(modifiers)
        if spec.key:
            item.setTarget_(target)
            item.setRepresentedObject_(spec.key)
        item.setEnabled_(bool(spec.enabled and (spec.key or spec.children or spec.kind == "header")))
        if spec.checked:
            item.setState_(1)
        if spec.symbol:
            _set_symbol(item, spec.symbol)
        if spec.badge:
            _set_badge(item, title, spec.badge)
        if spec.kind == "header":
            _style_header(item, spec)
        elif spec.kind == "hint":
            _style_hint(item, spec.title)
        elif spec.subtitle:
            _set_subtitle(item, title, spec.subtitle)
        if spec.children:
            submenu = NSMenu.alloc().initWithTitle_(title)
            submenu.setAutoenablesItems_(False)
            _fill(submenu, list(spec.children), target)
            item.setSubmenu_(submenu)
        menu.addItem_(item)


def _set_symbol(item, name: str) -> None:
    try:
        from AppKit import NSImage  # noqa: PLC0415

        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if image is not None:
            item.setImage_(image)
    except Exception:
        pass


def _section(title: str):
    from AppKit import NSMenuItem  # noqa: PLC0415

    try:
        return NSMenuItem.sectionHeaderWithTitle_(title)  # macOS 14
    except Exception:
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        item.setEnabled_(False)
        _style_small(item, title)
        return item


def _set_badge(item, title: str, badge: str) -> None:
    try:
        from AppKit import NSMenuItemBadge  # noqa: PLC0415 - macOS 14

        item.setBadge_(NSMenuItemBadge.alloc().initWithString_(badge))
    except Exception:
        item.setTitle_(f"{title}　{badge}")


def _set_subtitle(item, title: str, subtitle: str) -> None:
    try:
        item.setSubtitle_(subtitle)  # macOS 14.4
    except Exception:
        _two_lines(item, title, subtitle)


def _two_lines(item, title: str, second: str, bold: bool = False) -> None:
    try:
        from AppKit import (  # noqa: PLC0415
            NSColor,
            NSFont,
            NSFontAttributeName,
            NSForegroundColorAttributeName,
        )
        from Foundation import NSAttributedString, NSMutableAttributedString  # noqa: PLC0415

        size = NSFont.systemFontSize()
        head_font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.menuFontOfSize_(size)
        text = NSMutableAttributedString.alloc().initWithString_attributes_(title, {NSFontAttributeName: head_font})
        text.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                "\n" + second,
                {
                    NSFontAttributeName: NSFont.menuFontOfSize_(NSFont.smallSystemFontSize()),
                    NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
                },
            )
        )
        item.setAttributedTitle_(text)
    except Exception:
        item.setTitle_(f"{title} · {second}")


def _style_header(item, spec: Item) -> None:
    try:
        from AppKit import NSApplication  # noqa: PLC0415
        from Foundation import NSMakeSize  # noqa: PLC0415

        icon = NSApplication.sharedApplication().applicationIconImage()
        if icon is not None:
            icon = icon.copy()
            icon.setSize_(NSMakeSize(28, 28))
            item.setImage_(icon)
    except Exception:
        pass
    _two_lines(item, spec.title, spec.subtitle, bold=True)


def _style_hint(item, title: str) -> None:
    item.setEnabled_(False)
    _style_small(item, title)


def _style_small(item, title: str) -> None:
    try:
        from AppKit import (  # noqa: PLC0415
            NSColor,
            NSFont,
            NSFontAttributeName,
            NSForegroundColorAttributeName,
        )
        from Foundation import NSAttributedString  # noqa: PLC0415

        item.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                title,
                {
                    NSFontAttributeName: NSFont.menuFontOfSize_(NSFont.smallSystemFontSize()),
                    NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
                },
            )
        )
    except Exception:
        pass


_TARGETS: list = []
_TargetClass = None


def _target(owner: MenuBarIcon):
    """One NSObject that receives every menu action, the menu delegate call and the animation tick."""

    global _TargetClass
    if _TargetClass is None:
        import objc  # noqa: PLC0415
        from Foundation import NSObject  # noqa: PLC0415

        class MenuTarget(NSObject):
            def initWithOwner_(self, owner_):  # noqa: N802 - Cocoa selector
                self = objc.super(MenuTarget, self).init()
                if self is None:
                    return None
                self.owner = owner_
                return self

            def menuAction_(self, sender) -> None:  # noqa: N802
                self.owner.perform(str(sender.representedObject() or ""))

            def menuNeedsUpdate_(self, menu) -> None:  # noqa: N802
                try:
                    self.owner.rebuild()
                except Exception:
                    LOGGER.warning("Could not rebuild the menu", exc_info=True)

            def tick_(self, timer) -> None:  # noqa: N802
                self.owner._draw_frame()

        _TargetClass = MenuTarget
    target = _TargetClass.alloc().initWithOwner_(owner)
    # Menus hold their targets and delegate weakly.
    _TARGETS.append(target)
    return target
