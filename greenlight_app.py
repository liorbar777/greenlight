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
import time
import traceback

import objc
from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSStatusBar,
    NSVariableStatusItemLength, NSImage, NSColor, NSBezierPath, NSMenu,
    NSMenuItem, NSFont, NSFontAttributeName, NSForegroundColorAttributeName,
    NSBitmapImageRep, NSGraphicsContext, NSDeviceRGBColorSpace,
)
from Foundation import (
    NSObject, NSTimer, NSMakeRect, NSMakeSize, NSMakePoint, NSString,
)

# Code lives wherever this file is; runtime (lock/state/config/pid) is pinned to
# ONE canonical dir so any copy of the app shares a single lock -> single instance.
# Override with GREENLIGHT_DIR (e.g. for isolated dev).
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.environ.get("GREENLIGHT_DIR") or os.path.expanduser(
    "~/Library/Application Support/Greenlight")
os.makedirs(RUNTIME_DIR, exist_ok=True)
STATE_FILE = os.path.join(RUNTIME_DIR, "state.json")
CONFIG_FILE = os.path.join(RUNTIME_DIR, "config.json")
PID_FILE = os.path.join(RUNTIME_DIR, "app.pid")
LOCK_FILE = os.path.join(RUNTIME_DIR, "app.lock")
CONTROL_FILE = os.path.join(RUNTIME_DIR, "control.json")   # {"visible": bool}
WIX_IMG = os.path.join(CODE_DIR, "wix_white.png")

# Icon geometry (points)
# Menu-bar item: the full horizontal 3-lamp traffic light.
IW, IH = 78, 24
R = 11
CY = IH / 2.0
CX = [13, 39, 65]          # red, amber, green centres
GREEN_CX = CX[2]

BULB_ON = {"red": (1.00, 0.27, 0.23), "amber": (1.00, 0.70, 0.25),
           "green": (0.20, 0.84, 0.29)}
DISABLED = (0.42, 0.42, 0.44)
OFF_LAMP = (0.60, 0.60, 0.63)   # inactive lamp = light gray (only the lit one is coloured)

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
        self.visible = bool(read_json(CONTROL_FILE, {}).get("visible", True))
        self.blink_on = True
        self.mtime = 0
        self.ctl_mtime = 0
        self.wix = None
        if os.path.exists(WIX_IMG):
            img = NSImage.alloc().initWithContentsOfFile_(WIX_IMG)
            if img is not None:
                self.wix = img
        return self

    # ---- app delegate ----
    def applicationDidFinishLaunching_(self, notification):
        # Status item is created in main() BEFORE the run loop — creating it here
        # (after the app finishes launching) leaves it invisible. Nothing to do.
        pass

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
        # "Hide" just removes the dot (process stays alive); clicking the
        # Greenlight app icon again brings it back. This avoids ever creating a
        # second status item in the session, which macOS won't draw.
        hide_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Hide Icon", "hideIcon:", "")
        hide_item.setTarget_(self)
        menu.addItem_(hide_item)
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
        # Render into an offscreen bitmap (NOT lockFocus): lockFocus draws nothing
        # when the app runs as a background agent with no window/screen focus, which
        # left the menu-bar item blank/invisible. A bitmap context works headless.
        rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, IW, IH, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0)
        ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.setCurrentContext_(ctx)

        cfg = STATE_MAP.get(self.state, STATE_MAP["idle"])
        active = cfg["bulb"]
        for i, name in enumerate(ORDER):
            if not self.enabled:
                rgb = DISABLED
            else:
                lit = (name == active) and (self.blink_on or not cfg["blink"])
                rgb = BULB_ON[name] if lit else OFF_LAMP
            nscolor(rgb).set()
            rect = NSMakeRect(CX[i] - R, CY - R, 2 * R, 2 * R)
            NSBezierPath.bezierPathWithOvalInRect_(rect).fill()
        if self.enabled and self.state == "go":
            self._draw_wix()

        NSGraphicsContext.restoreGraphicsState()
        img = NSImage.alloc().initWithSize_(NSMakeSize(IW, IH))
        img.addRepresentation_(rep)
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

    # ---- visibility (single persistent item, toggled not recreated) ----
    def apply_visibility(self):
        try:
            self.item.setVisible_(bool(self.visible))
        except Exception:
            pass

    def _write_control(self):
        try:
            with open(CONTROL_FILE, "w") as f:
                json.dump({"visible": bool(self.visible)}, f)
        except Exception:
            pass

    # ---- loops (selectors) ----
    def poll_(self, timer):
        # state.json -> lamp colour
        try:
            m = os.path.getmtime(STATE_FILE)
            if m != self.mtime:
                self.mtime = m
                new = read_json(STATE_FILE, {}).get("state", "idle")
                if new != self.state:
                    self.state = new
                    self.blink_on = True
                    if self.enabled:
                        self.redraw()
        except OSError:
            pass
        # control.json -> show/hide (a 2nd launch writes visible=true to re-show)
        try:
            cm = os.path.getmtime(CONTROL_FILE)
            if cm != self.ctl_mtime:
                self.ctl_mtime = cm
                v = bool(read_json(CONTROL_FILE, {}).get("visible", True))
                if v != self.visible:
                    self.visible = v
                    self.apply_visibility()
        except OSError:
            pass

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

    def hideIcon_(self, sender):
        # Hide the dot but keep the process alive — clicking the app icon again
        # re-shows it (no second status item is ever created).
        self.visible = False
        self._write_control()
        self.apply_visibility()

    def quit_(self, sender):
        # Release the single-instance lock immediately, so an instant relaunch
        # doesn't race a slow NSApplication termination and exit on the lock.
        global _lock_keep
        try:
            if _lock_keep is not None:
                fcntl.flock(_lock_keep, fcntl.LOCK_UN)
                _lock_keep.close()
                _lock_keep = None
        except Exception:
            pass
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        NSApplication.sharedApplication().terminate_(None)


def _dlog(msg):
    try:
        with open(os.path.join(RUNTIME_DIR, "app.log"), "a") as f:
            f.write(f"[greenlight] {msg}\n")
    except Exception:
        pass


_lock_keep = None  # keep the lock fd alive for the process lifetime


def main():
    _dlog(f"=== start pid={os.getpid()} runtime={RUNTIME_DIR}")
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    lock = open(LOCK_FILE, "w")
    # Single instance. On a quick Quit+relaunch the dying instance may still hold
    # the lock for a moment, so wait briefly for it to release before giving up.
    acquired = False
    for _ in range(25):                       # ~2.5s grace
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            break
        except OSError:
            time.sleep(0.1)
    if not acquired:
        # A persistent instance is already running. Don't start a second one
        # (macOS won't draw its status item) — just ask the running one to show
        # itself, so clicking the app icon "reopens" the dot.
        _dlog("daemon already running -> requesting show + exiting")
        try:
            with open(CONTROL_FILE, "w") as f:
                json.dump({"visible": True}, f)
        except Exception:
            pass
        sys.exit(0)
    _dlog("lock acquired")
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    global _lock_keep
    _lock_keep = lock  # don't let the lock fd get garbage-collected
    # A freshly started daemon always shows the icon (don't persist a prior Hide).
    try:
        with open(CONTROL_FILE, "w") as f:
            json.dump({"visible": True}, f)
    except Exception:
        pass

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = GreenlightApp.alloc().init()
    app.setDelegate_(controller)
    try:
        controller.build()              # MUST be before app.run() or the item is invisible
        controller.apply_visibility()
        _dlog(f"build ok visible={controller.visible}")
    except Exception:
        _dlog("build FAILED:\n" + traceback.format_exc())
    global _keepalive
    _keepalive = controller
    _dlog("entering run loop")
    app.run()


if __name__ == "__main__":
    main()
