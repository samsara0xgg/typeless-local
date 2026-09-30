"""Native glass under the capsule page.

WebKit's backdrop-filter only blurs what is inside the web view, and the
capsule's panel is transparent, so CSS alone cannot show the desktop through
the glass. The glass is therefore drawn by AppKit: one view per shape, sitting
under the transparent web view and moved every frame to the rectangle the page
reports. The page owns the animation; this module only follows it.

NSGlassEffectView (macOS 26) is the real Liquid Glass and, inside an
NSGlassEffectContainerView, merges shapes that come close, which is what makes
the undo and edit buttons read as budding off the capsule. Older systems get
NSVisualEffectView, and if neither can be made the page falls back to its own
CSS fill.
"""

from __future__ import annotations

import logging

import objc
from AppKit import NSView
from Foundation import NSMakeRect

LOGGER = logging.getLogger(__name__)

# NSVisualEffectView constants, spelled out so an older PyObjC still works.
_MATERIAL_POPOVER = 6
_BLENDING_BEHIND_WINDOW = 0
_STATE_ACTIVE = 1
# Shapes closer than this merge into one piece of glass.
MERGE_SPACING = 14.0


class FlippedView(NSView):
    """Top-left origin, so page coordinates can be used as they come."""

    def isFlipped(self) -> bool:  # noqa: N802 - Cocoa selector
        return True


def _lookup(name: str):
    try:
        return objc.lookUpClass(name)
    except Exception:
        return None


def _begin_transaction():
    """A Core Animation transaction with implicit animations off, or None."""

    try:
        from Quartz import CATransaction  # noqa: PLC0415

        CATransaction.begin()
    except Exception:
        return None
    try:
        CATransaction.setDisableActions_(True)
    except Exception:
        pass
    return CATransaction


class GlassLayer:
    """Glass shapes placed at the rectangles the page reports."""

    def __init__(self, host: NSView) -> None:
        self.host = host
        self.kind = ""
        self._views: dict[str, object] = {}
        self._suppressed = False
        bounds = host.bounds()
        glass_cls = _lookup("NSGlassEffectView")
        container_cls = _lookup("NSGlassEffectContainerView")
        self._glass_cls = glass_cls
        self._effect_cls = None
        self.content = None
        try:
            if glass_cls is not None:
                self.content = FlippedView.alloc().initWithFrame_(bounds)
                if container_cls is not None:
                    container = container_cls.alloc().initWithFrame_(bounds)
                    container.setSpacing_(MERGE_SPACING)
                    container.setContentView_(self.content)
                    self.root = container
                else:
                    self.root = self.content
                self.kind = "glass"
            else:
                self._effect_cls = _lookup("NSVisualEffectView")
                if self._effect_cls is None:
                    raise RuntimeError("no NSVisualEffectView")
                self.content = FlippedView.alloc().initWithFrame_(bounds)
                self.root = self.content
                self.kind = "vibrancy"
            self.root.setAutoresizingMask_(18)  # width + height sizable
            host.addSubview_(self.root)
        except Exception:
            LOGGER.warning("Native glass unavailable; the capsule draws its own fill", exc_info=True)
            self.kind = ""
            self.root = None
            self.content = None

    def _make(self, shape: dict):
        rect = NSMakeRect(0, 0, float(shape["w"]), float(shape["h"]))
        if self.kind == "glass":
            view = self._glass_cls.alloc().initWithFrame_(rect)
        else:
            view = self._effect_cls.alloc().initWithFrame_(rect)
            view.setMaterial_(_MATERIAL_POPOVER)
            view.setBlendingMode_(_BLENDING_BEHIND_WINDOW)
            view.setState_(_STATE_ACTIVE)
            view.setWantsLayer_(True)
            layer = view.layer()
            if layer is not None:
                layer.setMasksToBounds_(True)
                try:
                    layer.setCornerCurve_("continuous")
                except Exception:
                    pass
        self.content.addSubview_(view)
        return view

    def set_suppressed(self, suppressed: bool) -> None:
        """Hide every glass view (Reduce Transparency: the page draws solid fills)."""

        self._suppressed = bool(suppressed)
        if self._suppressed:
            for view in self._views.values():
                view.setHidden_(True)

    def apply(self, shapes: list[dict]) -> None:
        if not self.kind or self.content is None:
            return
        seen = set()
        transaction = _begin_transaction()
        try:
            for shape in shapes:
                if not shape.get("glass"):
                    continue
                key = str(shape.get("id"))
                seen.add(key)
                alpha = float(shape.get("a", 1.0))
                view = self._views.get(key)
                if view is None:
                    if alpha < 0.01:
                        continue
                    view = self._make(shape)
                    self._views[key] = view
                width, height = max(0.0, float(shape["w"])), max(0.0, float(shape["h"]))
                view.setFrame_(NSMakeRect(float(shape["x"]), float(shape["y"]), width, height))
                radius = min(float(shape.get("r", 0.0)), width / 2.0, height / 2.0)
                if self.kind == "glass":
                    view.setCornerRadius_(radius)
                else:
                    layer = view.layer()
                    if layer is not None:
                        layer.setCornerRadius_(radius)
                view.setAlphaValue_(max(0.0, min(1.0, alpha)))
                view.setHidden_(self._suppressed or alpha < 0.01 or width < 1 or height < 1)
            for key in list(self._views):
                if key not in seen:
                    view = self._views.pop(key)
                    view.removeFromSuperview()
        finally:
            if transaction is not None:
                transaction.commit()

    def clear(self) -> None:
        self.apply([])
