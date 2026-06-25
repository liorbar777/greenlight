# 🚦 Greenlight — a menu-bar traffic light for Claude Code

A native macOS **menu-bar** item (`NSStatusItem`, via PyObjC) that sits beside
your system icons and shows Claude Code's state as a mini horizontal 3-lamp
traffic light. Click it for a menu (Enable/Disable, Quit).

## Install

```bash
cd ~/Documents/all_projects/greenlight
./install.sh        # creates .venv + PyObjC, wires hooks, installs the login LaunchAgent
```

Re-run any time (idempotent). To remove: `./uninstall.sh`.
The venv is built with `/Users/liorbar/.local/share/uv/.../python3.11` by
default — override with `GREENLIGHT_PY=/path/to/python3 ./install.sh`.

## States

| Lamp | Meaning | Hook that triggers it |
|------|---------|-----------------------|
| ⚫ all dim | idle / no active turn | `SessionStart` |
| 🟡 solid amber | Claude is working / thinking | `UserPromptSubmit`, `PreToolUse`, `PostToolUse` |
| 🟡 blinking amber | Claude is **waiting on you** (a question / plan approval) | `PreToolUse` (AskUserQuestion / ExitPlanMode) |
| 🟢 green (Wix mark shown) | finished OK, or a positive verdict | `Stop` |
| 🔴 red | a negative go/no-go verdict | `Stop` |

The **Wix mark** is drawn inside the green lamp only while the light is green.
Supply `wix_white.png` (white logo, transparent bg) in this folder and it
replaces the placeholder "W"; otherwise a bold white "W" is drawn.

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

## Controls

- **Click the menu-bar icon** → menu with **Enabled** (toggle; greys the light
  out / "unplugs" it, persisted across restarts) and **Quit Greenlight**.
- Manual control: `./greenlight.sh {start|stop|restart|status}`

## Files

| File | Role |
|------|------|
| `greenlight_app.py` | the menu-bar app (PyObjC `NSStatusItem`); polls `state.json` |
| `greenlight_hook.py` | called by Claude Code hooks; writes `state.json`, parses verdicts, ensures the app is running |
| `greenlight.sh` | manual control: `start` / `stop` / `restart` / `status` (launchd-aware) |
| `install.sh` / `uninstall.sh` | set up / tear down venv, hooks, LaunchAgent |
| `requirements.txt` | `pyobjc-framework-Cocoa` |
| `com.liorbar.greenlight.plist` | LaunchAgent template |
| `.venv/` | virtualenv with PyObjC (gitignored; created by install) |
| `state.json` | current state (written by the hook; gitignored) |
| `config.json` | persisted enabled/disabled choice (gitignored) |
| `app.pid` / `app.lock` / `app.log` | process id / single-instance lock / log (gitignored) |

## How it's wired

Hooks in `~/.claude/settings.json` call `greenlight_hook.py` with an intent on
each event (run by the uv Python — it only writes `state.json`, no deps). The
hook ensures the app is running (via `launchctl kickstart`, else a detached
spawn with the venv Python). The menu-bar app polls `state.json` and redraws.

A backup of the pre-Greenlight settings is at
`~/.claude/settings.json.bak.greenlight`.

## Auto-start at login (LaunchAgent)

A LaunchAgent at `~/Library/LaunchAgents/com.liorbar.greenlight.plist` runs the
app at login (with the venv Python) and relaunches it on crash. A clean Quit
exits 0 and is respected — not relaunched until next login. `greenlight.sh` is
launchd-aware: `stop` boots the job out (returns next login), `restart` uses
`kickstart -k`.

## Removing it

Run `./uninstall.sh` (removes the LaunchAgent + hook groups), then optionally
`rm -rf ~/Documents/all_projects/greenlight` and delete the
"Greenlight Verdict Marker" section from `~/.claude/CLAUDE.md`.

## Notes / limitations

- **Tool-permission prompts ("Allow this command?") do not blink** — they stay
  solid amber. Blinking relies on Claude Code's `Notification` hook, which (at
  least in this setup) does not fire for permission prompts — verified with a
  34-second open prompt that produced zero `Notification` events. Only
  `AskUserQuestion` / `ExitPlanMode` (which ride `PreToolUse`) blink. There is
  no hook-based way to distinguish "waiting on a permission prompt" from "a tool
  is running", so solid amber is the honest signal for both.
- One light is shared across all Claude Code sessions; concurrent sessions will
  fight over the state. Fine for a single active session.
- **Interpreter paths are hardcoded** (uv Python for the hook commands; the
  project `.venv` for the app). If the uv Python is removed/upgraded, the hooks
  silently no-op (Claude keeps working, the light just stops updating). Re-run
  `./install.sh` (optionally with `GREENLIGHT_PY=`) to repoint.
- Single instance is enforced via `app.lock` (`flock`); duplicate launches exit
  immediately.
