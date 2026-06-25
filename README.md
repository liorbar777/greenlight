# 🚦 Greenlight — a menu-bar traffic light for Claude Code

**Stop babysitting the terminal.** Greenlight puts a tiny traffic light in your
macOS menu bar that mirrors what Claude Code is doing — working, waiting on you,
done, or stopped on a bad outcome — so you can look away, do other work, and
glance up only when the colour changes. No tokens, no LLM calls, no network: it
just reads a tiny state file Claude Code's hooks write, and redraws.

A native macOS **menu-bar** item (`NSStatusItem`, via PyObjC) that sits beside
your system icons. Click it for a menu (Enable/Disable, Quit).

**Claude Code only** — hooks are wired into `~/.claude/settings.json`. Cursor
agent sessions do not update the light (unless you add similar hooks yourself).

## Install (no clone needed)

```bash
curl -fsSL https://raw.githubusercontent.com/liorbar777/greenlight/main/install.sh | bash
```

This downloads the app into `~/Library/Application Support/Greenlight`, builds a
PyObjC venv, creates **`Greenlight.app`** in your Applications folder (and
Launchpad), wires the Claude Code hooks, and installs a login LaunchAgent. The
light appears in your menu bar right away.

### Install from a clone

```bash
git clone https://github.com/liorbar777/greenlight.git
cd greenlight
./install.sh        # builds venv + PyObjC, the .app, wires hooks, installs the LaunchAgent
```

Re-run any time (idempotent). To remove: `./uninstall.sh` (or
`~/Library/Application\ Support/Greenlight/uninstall.sh` after a clone-free install).
Need a specific Python to build the venv? `GREENLIGHT_PY=/path/to/python3 ./install.sh`.

## States

| Lamp | Meaning | Hook that triggers it |
|------|---------|-----------------------|
| ⚪ all gray | idle / no active turn | `SessionStart` |
| 🟡 solid amber | Claude is working / thinking | `UserPromptSubmit`, `PreToolUse`, `PostToolUse` |
| 🟡 blinking amber | Claude is **waiting on you** (a question / plan approval) | `PreToolUse` (AskUserQuestion / ExitPlanMode) |
| 🟢 green (Wix mark shown) | finished OK, or a positive verdict | `Stop` |
| 🔴 red | a negative go/no-go verdict | `Stop` |

Only the active lamp is coloured; the other two are light gray.

The **Wix mark** is drawn inside the green lamp only while the light is green.
Supply `wix_white.png` (white logo, transparent bg) in this folder and it
replaces the placeholder "W"; otherwise a bold white "W" is drawn.

## Getting a red / green verdict

By default every finished turn is **green**. The `Stop` hook turns the
light **red** only if Claude's final message contains a marker:

```
GREENLIGHT: NO-GO  -> red    (also: RED, FAIL[ED]/FAILURE, BAD, BLOCK[ED], STOP[PED], ERROR, REJECT[ED], ABORT[ED])
GREENLIGHT: GO     -> green  (also: GREEN, GOOD, PASS[ED], OK[AY], SUCCESS, DONE, SHIP[PED], APPROVED, LGTM; green is the default anyway)
```

The marker can appear anywhere in the final message and is case-insensitive.

**Auto-red:** add a standing rule to `~/.claude/CLAUDE.md`:

```markdown
## Greenlight Verdict Marker

At the end of every turn, if the outcome is bad — negative verdict, failed
tests/build, blocked or incomplete task, unresolved error, or flagged risk —
append a final line:

    GREENLIGHT: NO-GO — <one-line reason>

Good turns emit nothing (the light stays green). You can also ask Claude to
"end with a GREENLIGHT verdict" explicitly.
```

## Controls

- **Click the menu-bar icon** → menu with **Enabled** (toggle; greys the light
  out / "unplugs" it), **Hide Icon** (removes the dot but keeps running — click
  the app icon to bring it back), and **Quit Greenlight**.
- **Applications / Launchpad:** launch **Greenlight** like any app. Clicking it
  while it's already running does nothing (it won't restart or duplicate).
- Manual control: `./greenlight.sh {start|stop|restart|status}`

## Files

| File | Role |
|------|------|
| `greenlight_app.py` | the menu-bar app (PyObjC `NSStatusItem`); polls `state.json` |
| `greenlight_hook.py` | called by Claude Code hooks; writes `state.json`, parses verdicts, ensures the app is running |
| `greenlight.sh` | manual control: `start` / `stop` / `restart` / `status` (launchd-aware) |
| `install.sh` / `uninstall.sh` | set up / tear down venv, hooks, LaunchAgent |
| `requirements.txt` | `pyobjc-framework-Cocoa` |
| `.venv/` | virtualenv with PyObjC (gitignored; created by install) |
| `state.json` | current state (written by the hook; gitignored) |
| `config.json` | persisted enabled/disabled choice (gitignored) |
| `app.pid` / `app.lock` / `app.log` | process id / single-instance lock / log (gitignored) |

## How it's wired

Hooks in `~/.claude/settings.json` call `greenlight_hook.py` with an intent on
each event (run by the install's venv Python — it only writes `state.json`).
The hook ensures the app is running (via `launchctl kickstart`, else a detached
spawn). The menu-bar app polls `state.json` and redraws. Code, venv, and runtime
files all live in `~/Library/Application Support/Greenlight`.

A backup of the pre-Greenlight settings is at
`~/.claude/settings.json.bak.greenlight`.

## Auto-start at login (LaunchAgent)

A LaunchAgent at `~/Library/LaunchAgents/com.greenlight.menubar.plist` runs the
app **directly** (`python greenlight_app.py`) at login and relaunches it on
crash. (Launching via the `.app` bundle is avoided here — a bundle `exec python`
launch leaves the menu-bar item invisible; a plain process draws it correctly.
The `.app` icon just kickstarts this agent.) A clean Quit is respected — not
relaunched until next login. `greenlight.sh` is launchd-aware.

If the icon is missing after login, run `./greenlight.sh start` or
`./install.sh`. Claude Code hooks will also start the app on the next session
even when launchd is unloaded.

## Troubleshooting

- **Icon missing entirely** — make sure it's launched as a plain process, not via
  the `.app` bundle's `exec` (the installer's LaunchAgent does this). `./greenlight.sh
  start` or re-running `./install.sh` fixes it.
- **Two traffic-light icons** — only one instance should run (`flock` lock).
  Run `./greenlight.sh stop && ./greenlight.sh start` to reset.
- **Light stopped updating** — re-run `./install.sh` to repoint hook paths if
  you moved the install or upgraded Python.

## Removing it

Run `./uninstall.sh` (removes the LaunchAgent + hook groups), then optionally
`rm -rf` this folder and delete the "Greenlight Verdict Marker" section from
`~/.claude/CLAUDE.md`.

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
- **Hook Python path is written at install time** into `~/.claude/settings.json`.
  If that interpreter is removed, hooks silently no-op (Claude keeps working,
  the light just stops updating). Re-run `./install.sh` to repoint.
- Single instance is enforced via `app.lock` (`flock`); duplicate launches exit
  immediately.
