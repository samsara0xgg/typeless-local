"""Draw the disk image window's background: where to drag the app, in both languages.

Drawn with AppKit rather than checked in as a picture, so the words and the
layout live next to the icon positions in build_app.make_dmg. Writes a TIFF
holding the 1x and 2x images, which Finder picks between by display.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

# Finder window content size and where the two icons sit (their centres,
# from the top left); build_app.make_dmg places the icons at these points.
WIDTH, HEIGHT = 640, 400
APP_AT = (170, 175)
APPLICATIONS_AT = (470, 175)
ZH = "把言字拖到「应用程序」文件夹，就装好了"
EN = "Drag Yana onto Applications to install it"


def _draw(scale: int, path: Path) -> None:
    from AppKit import (
        NSBezierPath,
        NSBitmapImageRep,
        NSCalibratedRGBColorSpace,
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSFontWeightMedium,
        NSForegroundColorAttributeName,
        NSGradient,
        NSGraphicsContext,
        NSLineCapStyleRound,
        NSLineJoinStyleRound,
        NSMakePoint,
        NSMakeRect,
        NSPNGFileType,
        NSString,
    )

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, WIDTH * scale, HEIGHT * scale, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0
    )
    rep.setSize_((WIDTH, HEIGHT))  # points, so 2x draws sharper rather than bigger
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))

    def rgb(r, g, b, a=1.0):
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(r / 255, g / 255, b / 255, a)

    def flip(y: float) -> float:  # AppKit counts from the bottom
        return HEIGHT - y

    # A pale sheet with two soft washes of colour, like the app's glass.
    NSGradient.alloc().initWithStartingColor_endingColor_(rgb(250, 251, 253), rgb(236, 240, 247)).drawInRect_angle_(
        NSMakeRect(0, 0, WIDTH, HEIGHT), 270
    )
    for (x, y, r), colour in (((90, 60, 260), rgb(10, 132, 255, 0.10)), ((560, 360, 280), rgb(175, 82, 222, 0.08))):
        NSGradient.alloc().initWithStartingColor_endingColor_(colour, rgb(255, 255, 255, 0)).drawFromCenter_radius_toCenter_radius_options_(
            NSMakePoint(x, flip(y)), 0, NSMakePoint(x, flip(y)), r, 0
        )

    # The arrow between the icons, a gentle arc.
    start, end = APP_AT[0] + 92, APPLICATIONS_AT[0] - 92
    y = APP_AT[1]
    arrow = NSBezierPath.bezierPath()
    arrow.moveToPoint_(NSMakePoint(start, flip(y)))
    arrow.curveToPoint_controlPoint1_controlPoint2_(
        NSMakePoint(end, flip(y)), NSMakePoint(start + 40, flip(y - 26)), NSMakePoint(end - 40, flip(y - 26))
    )
    arrow.moveToPoint_(NSMakePoint(end - 13, flip(y - 12)))
    arrow.lineToPoint_(NSMakePoint(end, flip(y)))
    arrow.lineToPoint_(NSMakePoint(end - 15, flip(y + 8)))
    arrow.setLineWidth_(4)
    arrow.setLineCapStyle_(NSLineCapStyleRound)
    arrow.setLineJoinStyle_(NSLineJoinStyleRound)
    rgb(10, 132, 255, 0.55).setStroke()
    arrow.stroke()

    def centred(text: str, size: float, weight: float, colour, top: float) -> None:
        attrs = {NSFontAttributeName: NSFont.systemFontOfSize_weight_(size, weight), NSForegroundColorAttributeName: colour}
        line = NSString.stringWithString_(text)
        w, h = line.sizeWithAttributes_(attrs)
        line.drawAtPoint_withAttributes_(NSMakePoint((WIDTH - w) / 2, flip(top) - h), attrs)

    centred(ZH, 16, NSFontWeightMedium, rgb(29, 29, 31), 300)
    centred(EN, 13, 0.0, rgb(110, 110, 115), 328)

    NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(str(path), True)


def make_background(out: Path) -> Path:
    """Write the background to ``out`` (a .tiff) and return it."""

    with tempfile.TemporaryDirectory() as tmp:
        one, two = Path(tmp) / "bg.png", Path(tmp) / "bg@2x.png"
        _draw(1, one)
        _draw(2, two)
        subprocess.check_call(["tiffutil", "-cathidpicheck", str(one), str(two), "-out", str(out)])
    return out


if __name__ == "__main__":
    print(make_background(Path("dmg-background.tiff")))
