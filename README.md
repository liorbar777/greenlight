# 🚦 Greenlight — a traffic light for Claude Code

A small, borderless, always-on-top window that docks at the top of your
screen and shows Claude Code's state as a vertical traffic light.

Standalone project — no dependencies beyond a Python with `tkinter`.

## Install

```bash
cd ~/Documents/all_projects/greenlight
./install.sh        # wires Claude Code hooks + installs the login LaunchAgent
```

Re-run any time (idempotent). To remove: `./uninstall.sh`.
Uses `/Users/liorbar/.local/share/uv/.../python3.11` by default — override
with `GREENLIGHT_PY=/path/to/python3 ./install.sh` (any python3 with tkinter).

## States

| Light | Meaning | Hook that triggers it |
|-------|---------|-----------------------|
| ⚫ all dim | idle / no active turn | `SessionStart` |
| 🟡 solid amber | Claude is working / thinking | `UserPromptSubmit`, `PreToolUse`, `PostToolUse` |
| 🟡 blinking amber | Claude is **waiting on you** (a question / plan approval) | `PreToolUse` (AskUserQuestion / ExitPlanMode) |
| 🟢 green | finished OK, or a positive verdict | `Stop` |
| 🔴 red | a negative go/no-go verdict | `Stop` |

## Getting a red / green verdict

By default every finished turn is **green**. The `Stop` hook turns the
light **red** only if Claude's final message contains a marker:

```
GREENLIGHT: NO-GO     -> red    (also: RED, FAIL, BAD)
GREENLIGHT: GO        -> green  (also: GREEN, PASS, GOOD; this is the default anyway)
```

The marker can appear anywhere in the final message and is case-insensitive.

**Auto-red:** a standing rule in `~/.claude/CLAUDE.md` (§ Greenlight
Verdict Marker) tells Claude to append `GREENLIGHT: NO-GO — <reason>` on
its own whenever a turn ends badly — a negative verdict, failed
tests/build/command left failing, a blocked or incomplete task, an
unresolved error, or a flagged risk. Good turns emit nothing and stay
green, so normal replies stay clean. You can still force a verdict any
time by asking Claude to "end with a GREENLIGHT verdict".

## Files

| File | Role |
|------|------|
| `greenlight_app.py` | the floating GUI (tkinter); polls `state.json` |
| `greenlight_hook.py` | called by hooks; writes `state.json`, parses verdicts, auto-launches the GUI |
| `greenlight.sh` | manual control: `start` / `stop` / `restart` / `status` |
| `state.json` | current state (written by the hook) |
| `pos.json` | remembered window position |
| `app.pid` / `app.log` | GUI process id / log |

## Controls

- **Drag** the light to move it (position is remembered).
- **Double-click** or **Esc** (while focused) to close it.
- Manual control: `~/Documents/all_projects/greenlight/greenlight.sh {start|stop|restart|status}`

## How it's wired

Hooks in `~/.claude/settings.json` call `greenlight_hook.py` with an
intent on each event. The hook writes `state.json` and, if the GUI isn't
running, launches it detached. The GUI watches `state.json` and redraws.

A backup of the pre-Greenlight settings is at
`~/.claude/settings.json.bak.greenlight`.

## Auto-start at login (LaunchAgent)

A LaunchAgent at `~/Library/LaunchAgents/com.liorbar.greenlight.plist`
starts the light at login and relaunches it if it crashes. A clean quit
(double-click) exits 0 and is respected — it will NOT be relaunched until
next login. `greenlight.sh` is launchd-aware: `stop` boots the job out
(it returns next login), `restart` uses `kickstart -k`.

- Disable until next login: `~/Documents/all_projects/greenlight/greenlight.sh stop`
- Reload now: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.liorbar.greenlight.plist`

## Removing it

1. Unload + delete the LaunchAgent:
   `launchctl bootout gui/$(id -u)/com.liorbar.greenlight 2>/dev/null;
   rm ~/Library/LaunchAgents/com.liorbar.greenlight.plist`
2. Delete the six Greenlight hook groups from `~/.claude/settings.json`
   (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Notification,
   Stop) — or restore the backup above. Also remove the
   "Greenlight Verdict Marker" section from `~/.claude/CLAUDE.md`.
3. `rm -rf ~/Documents/all_projects/greenlight`

## Notes / limitations

- **Tool-permission prompts ("Allow this command?") do not blink** — they stay
  solid amber. Blinking relies on Claude Code's `Notification` hook, which (at
  least in this setup) does not fire for permission prompts — verified with a
  34-second open prompt that produced zero `Notification` events. Only
  `AskUserQuestion` / `ExitPlanMode` (which ride `PreToolUse`) blink. There is
  no hook-based way to distinguish "waiting on a permission prompt" from "a tool
  is running", so solid amber is the honest signal for both.

- One light is shared across all Claude Code sessions; concurrent
  sessions will fight over the state. Fine for a single active session.
- tkinter windows float above normal windows but not above true
  full-screen-space apps (a macOS limitation).
- **Interpreter path is hardcoded.** Both the hook commands in
  `settings.json` and `greenlight.sh` point at
  `/Users/liorbar/.local/share/uv/python/cpython-3.11.14-.../python3.11`.
  If that uv Python is removed or upgraded, hooks silently no-op (Claude
  keeps working, the light just stops updating). To repoint: edit the
  `PY=` line in `greenlight.sh`, the `PY` constant in `greenlight_hook.py`,
  and the six hook commands in `~/.claude/settings.json`. Any python3 with
  tkinter works (e.g. `/usr/bin/python3`).
- Single instance is enforced via `app.lock` (`flock`); duplicate launches
  exit immediately. `Esc` to quit only works if the borderless window has
  keyboard focus — **double-click** (or `greenlight.sh stop`) is reliable.
