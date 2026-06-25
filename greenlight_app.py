#!/usr/bin/env python3
"""Greenlight — a menu-bar traffic light for Claude Code.

A native macOS status-bar item (NSStatusItem) that sits beside the system
icons. It draws a mini horizontal 3-lamp traffic light reflecting Claude
Code's state, read from a small JSON file the hook writes:

    idle     -> all lamps dim
    working  -> solid amber
    waiting  -> blinking amber (Claude asked you something)
    go       -> green   (finished OK / positive verdict; Wix mark shown)
    nogo     -> red     (negative verdict)

Click the icon for a menu: Enable/Disable (greys it out, persisted) and Quit.

Needs PyObjC (pyobjc-framework-Cocoa); run with the project's .venv python.
"""
import fcntl
import json
import os
import sys

import objc
from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSStatusBar,
    NSVariableStatusItemLength, NSImage, NSColor, NSBezierPath, NSMenu,
    NSMenuItem, NSFont, NSFontAttributeName, NSForegroundColorAttributeName,
)
from Foundation import (
    NSObject, NSTimer, NSMakeRect, NSMakeSize, NSMakePoint, NSString,
)

HOME = os.path.expanduser("~")
BASE_DIR = os.path.join(HOME, "Documents", "all_projects", "greenlight")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
PID_FILE = os.path.join(BASE_DIR, "app.pid")
LOCK_FILE = os.path.join(BASE_DIR, "app.lock")
WIX_IMG = os.path.join(BASE_DIR, "wix_white.png")

# Icon geometry (points)
IW, IH = 46, 18
R = 6
CY = IH / 2.0
CX = [11, 23, 35]          # red, amber, green centres
GREEN_CX = CX[2]

BULB_ON = {"red": (1.00, 0.27, 0.23), "amber": (1.00, 0.70, 0.25),
           "green": (0.20, 0.84, 0.29)}
BULB_OFF = {"red": (0.34, 0.13, 0.11), "amber": (0.34, 0.25, 0.10),
            "green": (0.09, 0.27, 0.14)}
DISABLED = (0.42, 0.42, 0.44)

STATE_MAP = {
    "idle":    {"bulb": None,    "blink": False},
    "working": {"bulb": "amber", "blink": False},
    "waiting": {"bulb": "amber", "blink": True},
    "go":      {"bulb": "green", "blink": False},
    "nogo":    {"bulb": "red",   "blink": False},
}
ORDER = ["red", "amber", "green"]


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def nscolor(rgb):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(rgb[0], rgb[1], rgb[2], 1.0)


class GreenlightApp(NSObject):
    def init(self):
        self = objc.super(GreenlightApp, self).init()
        if self is None:
            return None
        self.state = "idle"
        self.enabled = bool(read_json(CONFIG_FILE, {}).get("enabled", True))
        self.blink_on = True
        self.mtime = 0
        self.wix = None
        if os.path.exists(WIX_IMG):
            img = NSImage.alloc().initWithContentsOfFile_(WIX_IMG)
            if img is not None:
                self.wix = img
        return self

    # ---- setup ----
    def build(self):
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength)

        menu = NSMenu.alloc().init()
        self.toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Enabled", "toggleEnabled:", "")
        self.toggle_item.setTarget_(self)
        self.toggle_item.setState_(1 if self.enabled else 0)
        menu.addItem_(self.toggle_item)
        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Greenlight", "quit:", "q")
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self.item.setMenu_(menu)

        self.redraw()
        self.poll_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.15, self, "poll:", None, True)
        self.blink_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.45, self, "blink:", None, True)

    # ---- drawing ----
    def make_image(self):
        img = NSImage.alloc().initWithSize_(NSMakeSize(IW, IH))
        img.lockFocus()
        cfg = STATE_MAP.get(self.state, STATE_MAP["idle"])
        active = cfg["bulb"]
        for i, name in enumerate(ORDER):
            if not self.enabled:
                rgb = DISABLED
            else:
                lit = (name == active) and (self.blink_on or not cfg["blink"])
                rgb = BULB_ON[name] if lit else BULB_OFF[name]
            nscolor(rgb).set()
            rect = NSMakeRect(CX[i] - R, CY - R, 2 * R, 2 * R)
            NSBezierPath.bezierPathWithOvalInRect_(rect).fill()

        if self.enabled and self.state == "go":
            self._draw_wix()
        img.unlockFocus()
        img.setTemplate_(False)
        return img

    def _draw_wix(self):
        if self.wix is not None:
            side = 2 * R - 2
            self.wix.drawInRect_fromRect_operation_fraction_(
                NSMakeRect(GREEN_CX - side / 2, CY - side / 2, side, side),
                NSMakeRect(0, 0, 0, 0), 2, 1.0)         # 2 = NSCompositeSourceOver
            return
        # placeholder bold white "W"
        attrs = {NSFontAttributeName: NSFont.boldSystemFontOfSize_(9),
                 NSForegroundColorAttributeName: NSColor.whiteColor()}
        s = NSString.stringWithString_("W")
        sz = s.sizeWithAttributes_(attrs)
        s.drawAtPoint_withAttributes_(
            NSMakePoint(GREEN_CX - sz.width / 2.0, CY - sz.height / 2.0), attrs)

    def redraw(self):
        self.item.button().setImage_(self.make_image())

    # ---- loops (selectors) ----
    def poll_(self, timer):
        try:
            m = os.path.getmtime(STATE_FILE)
        except OSError:
            return
        if m != self.mtime:
            self.mtime = m
            new = read_json(STATE_FILE, {}).get("state", "idle")
            if new != self.state:
                self.state = new
                self.blink_on = True
                if self.enabled:
                    self.redraw()

    def blink_(self, timer):
        if self.enabled and STATE_MAP.get(self.state, {}).get("blink"):
            self.blink_on = not self.blink_on
            self.redraw()
        else:
            self.blink_on = True

    # ---- menu actions ----
    def toggleEnabled_(self, sender):
        self.enabled = not self.enabled
        self.blink_on = True
        self.toggle_item.setState_(1 if self.enabled else 0)
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({"enabled": self.enabled}, f)
        except Exception:
            pass
        self.redraw()

    def quit_(self, sender):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        NSApplication.sharedApplication().terminate_(None)


def main():
    os.makedirs(BASE_DIR, exist_ok=True)
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = GreenlightApp.alloc().init()
    controller.build()
    app.setDelegate_(controller)
    global _keepalive
    _keepalive = controller
    app.run()


if __name__ == "__main__":
    main()
