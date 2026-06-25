#!/usr/bin/env python3
"""Greenlight — a floating vertical traffic light for Claude Code.

A borderless, always-on-top window docked at the top of the screen.
It reflects Claude Code's current state by reading a small JSON state
file that the hook (greenlight_hook.py) writes:

    idle     -> all bulbs dim
    working  -> solid amber
    waiting  -> blinking amber (Claude is waiting on you)
    go       -> green   (finished OK / positive verdict)
    nogo     -> red     (negative verdict)

Drag to move (position is remembered). Press Esc or double-click to quit.
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

# Geometry
W, H = 74, 196
PAD = 8
R = 20                      # bulb radius
CX = W // 2                 # bulb center x
CY = [44, 98, 152]          # bulb center y: red, amber, green

# Colors
HOUSING = "#161618"
HOUSING_EDGE = "#3a3a3c"
BG = "#0b0b0c"              # window background (acts as the "transparent" frame)

BULB = {
    "red":   {"on": "#ff453a", "off": "#3a1512", "glow": "#7a241c"},
    "amber": {"on": "#ffb340", "off": "#3a2c10", "glow": "#7a5410"},
    "green": {"on": "#32d74b", "off": "#103a18", "glow": "#1c6e2c"},
}

# Which bulb each state lights, and whether it blinks
STATE_MAP = {
    "idle":    {"bulb": None,    "blink": False},
    "working": {"bulb": "amber", "blink": False},
    "waiting": {"bulb": "amber", "blink": True},
    "go":      {"bulb": "green", "blink": False},
    "nogo":    {"bulb": "red",   "blink": False},
}


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
        self.blink_on = True
        self._mtime = 0
        self._drag = (0, 0)

        root.title("Greenlight")
        root.configure(bg=BG)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.wm_attributes("-transparent", True)  # macOS: frame blends to desktop
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(root, width=W, height=H, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack()

        self._place_initial()
        self._build()
        self._bind()

        # macOS borderless windows sometimes need a nudge to draw + float
        root.update_idletasks()
        root.lift()
        root.after(50, lambda: root.attributes("-topmost", True))

        self.poll()
        self.blink()
        self.keep_top()

    # ---- layout / building ----
    def _place_initial(self):
        pos = read_json(POS_FILE, None)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if pos and "x" in pos and "y" in pos:
            x, y = int(pos["x"]), int(pos["y"])
        else:
            x, y = (sw - W) // 2, 8
        # Keep it on-screen — the monitor layout may have changed since we saved.
        x = max(0, min(x, sw - W))
        y = max(0, min(y, sh - H))
        self.root.geometry(f"{W}x{H}+{x}+{y}")

    def _build(self):
        c = self.canvas
        rounded_rect(c, PAD, PAD, W - PAD, H - PAD, 16,
                     fill=HOUSING, outline=HOUSING_EDGE, width=1)
        self.glow_ids, self.bulb_ids = [], []
        for cy in CY:
            glow = c.create_oval(CX - R - 6, cy - R - 6, CX + R + 6, cy + R + 6,
                                 fill=BG, outline="")
            bulb = c.create_oval(CX - R, cy - R, CX + R, cy + R,
                                 fill="#000000", outline="#000000", width=1)
            self.glow_ids.append(glow)
            self.bulb_ids.append(bulb)
        self.render()

    def _bind(self):
        for w in (self.root, self.canvas):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<Double-Button-1>", lambda e: self.quit())
            w.bind("<Escape>", lambda e: self.quit())

    # ---- rendering ----
    def render(self):
        cfg = STATE_MAP.get(self.state, STATE_MAP["idle"])
        active = cfg["bulb"]
        lit = active and (self.blink_on or not cfg["blink"])
        order = ["red", "amber", "green"]
        for i, name in enumerate(order):
            col = BULB[name]
            is_on = lit and name == active
            self.canvas.itemconfig(
                self.bulb_ids[i],
                fill=col["on"] if is_on else col["off"],
                outline=col["glow"] if is_on else "#000000",
            )
            self.canvas.itemconfig(
                self.glow_ids[i],
                fill=col["glow"] if is_on else BG,
            )

    # ---- loops ----
    def poll(self):
        try:
            m = os.path.getmtime(STATE_FILE)
            if m != self._mtime:
                self._mtime = m
                data = read_json(STATE_FILE, {})
                new = data.get("state", "idle")
                if new != self.state:
                    self.state = new
                    self.blink_on = True
                    self.render()
        except FileNotFoundError:
            pass
        self.root.after(150, self.poll)

    def blink(self):
        if STATE_MAP.get(self.state, {}).get("blink"):
            self.blink_on = not self.blink_on
            self.render()
        else:
            self.blink_on = True
        self.root.after(450, self.blink)

    def keep_top(self):
        # Re-assert float level so other always-on-top windows can't bury us.
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.root.after(3000, self.keep_top)

    # ---- drag / quit ----
    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        x = e.x_root - self._drag[0]
        y = e.y_root - self._drag[1]
        self.root.geometry(f"+{x}+{y}")

    def _drag_end(self, e):
        try:
            with open(POS_FILE, "w") as f:
                json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y()}, f)
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
    # Single-instance guard: hold an exclusive lock for our whole lifetime.
    # If another light already owns it, exit quietly (avoids duplicate windows
    # when several hooks fire at once before the first GUI has started).
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
