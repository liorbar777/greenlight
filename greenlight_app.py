#!/usr/bin/env python3
"""Greenlight — a floating horizontal traffic light for Claude Code.

A borderless, always-on-top panel docked near the top of the screen (below
the menu bar). It reflects Claude Code's state by reading a small JSON state
file that the hook (greenlight_hook.py) writes:

    idle     -> all bulbs dim
    working  -> solid amber
    waiting  -> blinking amber (Claude is waiting on you)
    go       -> green   (finished OK / positive verdict)
    nogo     -> red     (negative verdict)

Layout (left -> right):  [ red  amber  green(Wix inside) ] [ power toggle ]

The power toggle "unplugs" the light: it greys everything out (like a disabled
IDE control) and stops reacting to Claude until you click it again. This
enabled/disabled choice is remembered across restarts.

Drag the panel (away from the button) to move it; position is remembered.
Double-click or Esc to quit.
"""
import fcntl
import json
import os
import sys
import tkinter as tk

HOME = os.path.expanduser("~")
BASE_DIR = os.path.join(HOME, "Documents", "all_projects", "greenlight")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
POS_FILE = os.path.join(BASE_DIR, "pos.json")
PID_FILE = os.path.join(BASE_DIR, "app.pid")
LOCK_FILE = os.path.join(BASE_DIR, "app.lock")
WIX_IMG = os.path.join(BASE_DIR, "wix_white.png")   # white logo, if supplied

# Geometry (horizontal)
W, H = 170, 58
PAD = 6
CYC = H // 2                       # vertical center for everything
R = 12                             # bulb radius
BULB_CX = [30, 66, 102]            # red, amber, green centers (left -> right)
GREEN_CX = BULB_CX[2]              # the Wix mark lives inside the green bulb
BTN_CX, BTN_R = 146, 11            # power-button center x / radius

# Colors
HOUSING = "#161618"
HOUSING_EDGE = "#3a3a3c"
BG = "#0b0b0c"
DISABLED_BULB = "#3a3a3d"          # flat grey when "unplugged"
DISABLED_EDGE = "#27272a"
BTN_ON = "#e6e6e6"
BTN_OFF = "#5a5a5e"

BULB = {
    "red":   {"on": "#ff453a", "off": "#3a1512", "glow": "#7a241c"},
    "amber": {"on": "#ffb340", "off": "#3a2c10", "glow": "#7a5410"},
    "green": {"on": "#32d74b", "off": "#103a18", "glow": "#1c6e2c"},
}

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


def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Greenlight:
    def __init__(self, root):
        self.root = root
        self.state = "idle"
        self.enabled = True
        self.blink_on = True
        self._mtime = 0
        self._drag = (0, 0)
        self._press_on_btn = False
        self._moved = False
        self._wix_img = None

        root.title("Greenlight")
        root.configure(bg=BG)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.wm_attributes("-transparent", True)
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(root, width=W, height=H, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack()

        self._place_initial()
        self._build()
        self._bind()

        root.update_idletasks()
        root.lift()
        root.after(50, lambda: root.attributes("-topmost", True))

        self.poll()
        self.blink()
        self.keep_top()

    # ---- layout ----
    def _place_initial(self):
        pos = read_json(POS_FILE, None) or {}
        self.enabled = bool(pos.get("enabled", True))
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if "x" in pos and "y" in pos:
            x, y = int(pos["x"]), int(pos["y"])
        else:
            x, y = (sw - W) // 2, 34          # centred, just below the menu bar
        x = max(0, min(x, sw - W))
        y = max(0, min(y, sh - H))
        self.root.geometry(f"{W}x{H}+{x}+{y}")

    def _build(self):
        c = self.canvas
        rounded_rect(c, PAD, PAD, W - PAD, H - PAD, 14,
                     fill=HOUSING, outline=HOUSING_EDGE, width=1)

        # Bulbs (glow + bulb per position)
        self.glow_ids, self.bulb_ids = [], []
        for cx in BULB_CX:
            glow = c.create_oval(cx - R - 5, CYC - R - 5, cx + R + 5, CYC + R + 5,
                                 fill=BG, outline="")
            bulb = c.create_oval(cx - R, CYC - R, cx + R, CYC + R,
                                 fill="#000000", outline="#000000", width=1)
            self.glow_ids.append(glow)
            self.bulb_ids.append(bulb)

        # Wix mark INSIDE the green bulb (drawn last so it stays on top) —
        # image if supplied, else a bold white placeholder. Shown only while
        # the light is green (see render()).
        self.wix_id = None
        if os.path.exists(WIX_IMG):
            try:
                self._wix_img = tk.PhotoImage(file=WIX_IMG)
                self.wix_id = c.create_image(GREEN_CX, CYC, image=self._wix_img)
            except Exception:
                self._wix_img = None
        if self._wix_img is None:
            self.wix_id = c.create_text(GREEN_CX, CYC + 1, text="Wix",
                                        font=("Helvetica", 8, "bold"), fill="#ffffff")

        # Power toggle button (arc ring + stem)
        bx, by, br = BTN_CX, CYC, BTN_R
        self.btn_ring = c.create_arc(bx - br, by - br, bx + br, by + br,
                                     start=115, extent=310, style="arc", width=2,
                                     outline=BTN_ON)
        self.btn_stem = c.create_line(bx, by - br - 1, bx, by - 2, width=2, fill=BTN_ON)

        self.render()

    def _bind(self):
        for w in (self.root, self.canvas):
            w.bind("<Button-1>", self._press)
            w.bind("<B1-Motion>", self._move)
            w.bind("<ButtonRelease-1>", self._release)
            w.bind("<Double-Button-1>", lambda e: self.quit())
            w.bind("<Escape>", lambda e: self.quit())

    # ---- rendering ----
    def render(self):
        c = self.canvas
        if not self.enabled:
            for i in range(3):
                c.itemconfig(self.bulb_ids[i], fill=DISABLED_BULB, outline=DISABLED_EDGE)
                c.itemconfig(self.glow_ids[i], fill=BG)
        else:
            cfg = STATE_MAP.get(self.state, STATE_MAP["idle"])
            active = cfg["bulb"]
            lit = active and (self.blink_on or not cfg["blink"])
            for i, name in enumerate(ORDER):
                col = BULB[name]
                is_on = lit and name == active
                c.itemconfig(self.bulb_ids[i],
                             fill=col["on"] if is_on else col["off"],
                             outline=col["glow"] if is_on else "#000000")
                c.itemconfig(self.glow_ids[i],
                             fill=col["glow"] if is_on else BG)
        btn_color = BTN_ON if self.enabled else BTN_OFF
        c.itemconfig(self.btn_ring, outline=btn_color)
        c.itemconfig(self.btn_stem, fill=btn_color)
        # Wix mark shows only when the light is actually green.
        show_wix = self.enabled and self.state == "go"
        c.itemconfig(self.wix_id, state="normal" if show_wix else "hidden")

    # ---- loops ----
    def poll(self):
        try:
            m = os.path.getmtime(STATE_FILE)
            if m != self._mtime:
                self._mtime = m
                new = read_json(STATE_FILE, {}).get("state", "idle")
                if new != self.state:
                    self.state = new
                    self.blink_on = True
                    if self.enabled:
                        self.render()
        except FileNotFoundError:
            pass
        self.root.after(150, self.poll)

    def blink(self):
        if self.enabled and STATE_MAP.get(self.state, {}).get("blink"):
            self.blink_on = not self.blink_on
            self.render()
        else:
            self.blink_on = True
        self.root.after(450, self.blink)

    def keep_top(self):
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.root.after(3000, self.keep_top)

    # ---- interaction (drag vs button click) ----
    def _on_button(self, x, y):
        return (x - BTN_CX) ** 2 + (y - CYC) ** 2 <= (BTN_R + 4) ** 2

    def _press(self, e):
        self._press_on_btn = self._on_button(e.x, e.y)
        self._moved = False
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())

    def _move(self, e):
        self._moved = True
        if self._press_on_btn:
            return                       # don't drag when starting on the button
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _release(self, e):
        if self._press_on_btn and not self._moved:
            self._toggle_enabled()
        elif self._moved:
            self._save_pos()
        self._press_on_btn = False

    def _toggle_enabled(self):
        self.enabled = not self.enabled
        self.blink_on = True
        self.render()
        self._save_pos()

    def _save_pos(self):
        try:
            with open(POS_FILE, "w") as f:
                json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y(),
                           "enabled": self.enabled}, f)
        except Exception:
            pass

    def quit(self):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        self.root.destroy()


def main():
    os.makedirs(BASE_DIR, exist_ok=True)
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    root = tk.Tk()
    Greenlight(root)
    root.mainloop()


if __name__ == "__main__":
    main()
