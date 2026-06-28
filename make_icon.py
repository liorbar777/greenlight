#!/usr/bin/env python3
"""Render the Greenlight app icon — a vertical 3-lamp traffic light — to a PNG.

Usage:  make_icon.py <size_px> <out.png>     (run with the project's .venv python)

build_icns.sh calls this at each iconset size and packs them into icon.icns.
Drawn vectorially at every native size so it stays crisp.
"""
import sys

from AppKit import (
    NSBitmapImageRep, NSGraphicsContext, NSColor, NSBezierPath, NSDeviceRGBColorSpace,
)
from Foundation import NSMakeRect


def color(r, g, b, a=1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


def oval(cx, cy, r):
    return NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(cx - r, cy - r, 2 * r, 2 * r))


def render(size: int, out_path: str) -> None:
    S = float(size)
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0)
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)

    # rounded-square app background (subtle dark gradient feel via two fills)
    bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(S * 0.06, S * 0.06, S * 0.88, S * 0.88), S * 0.22, S * 0.22)
    color(0.16, 0.17, 0.20).set(); bg.fill()
    color(0.0, 0.0, 0.0, 0.18).set(); bg.setLineWidth_(S * 0.012); bg.stroke()

    # traffic-light housing (darker, vertical)
    hw, hh = S * 0.40, S * 0.74
    hx, hy = (S - hw) / 2.0, (S - hh) / 2.0
    housing = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(hx, hy, hw, hh), hw * 0.34, hw * 0.34)
    color(0.07, 0.08, 0.10).set(); housing.fill()

    cx = S / 2.0
    lamp_r = hw * 0.30
    ys = [hy + hh * 0.775, hy + hh * 0.5, hy + hh * 0.225]   # top, middle, bottom
    cols = [(0.96, 0.27, 0.22), (1.00, 0.74, 0.18), (0.20, 0.82, 0.34)]  # red, amber, green
    for y, (r, g, b) in zip(ys, cols):
        color(r, g, b, 0.22).set(); oval(cx, y, lamp_r * 1.25).fill()      # glow
        color(r, g, b, 1.0).set();  oval(cx, y, lamp_r).fill()            # lamp
        color(1, 1, 1, 0.28).set()                                         # top highlight
        oval(cx - lamp_r * 0.28, y + lamp_r * 0.34, lamp_r * 0.34).fill()

    NSGraphicsContext.restoreGraphicsState()
    png = rep.representationUsingType_properties_(4, {})    # 4 = PNG
    if not png.writeToFile_atomically_(out_path, True):
        raise SystemExit(f"failed to write {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: make_icon.py <size_px> <out.png>")
    render(int(sys.argv[1]), sys.argv[2])
