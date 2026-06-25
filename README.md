<p align="center">
  <img src="icon.png" width="128" alt="Greenlight">
</p>

<h1 align="center">🚦 Greenlight</h1>

<p align="center">
  <b>A tiny traffic light in your menu bar that shows what Claude Code is doing.</b><br>
  Let Claude work while you switch tabs or get other things done — just glance up to catch when it's your turn or it's finished. No more babysitting the terminal.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/macOS-10.13%2B-black?logo=apple&logoColor=white" alt="macOS 10.13+">
  <img src="https://img.shields.io/badge/runs%20on-Apple%20Silicon%20%26%20Intel-brightgreen" alt="Apple Silicon & Intel">
  <img src="https://img.shields.io/badge/tokens-0-informational" alt="0 tokens">
  <img src="https://img.shields.io/badge/network-none-blueviolet" alt="no network">
</p>

---

## ✨ Install — one line

```bash
curl -fsSL https://raw.githubusercontent.com/liorbar777/greenlight/master/install.sh | bash
```

A little traffic light pops into your menu bar. It **auto-starts at login** and adds **Greenlight.app** to your Applications. Done. 🎉

<sub>Prefer a clone? `git clone https://github.com/liorbar777/greenlight.git && cd greenlight && ./install.sh`</sub>

## 🎨 What the colors mean

| | State | What's up |
|---|---|---|
| ⚪ | gray | idle — nothing running, or you've disabled it from the menu |
| 🟠 | orange | Claude is working / thinking |
| ✨🔴 | **blinking red** | **your turn** — a question, a plan, or any approval prompt is waiting on you |
| 🟢 | green | finished |

It's a pure **status** light — orange while Claude works, green when it finishes, blinking red when it needs you. No error/verdict path.

Only the active lamp lights up — the others stay a calm gray. No tokens, no LLM calls, no network: it just reads a tiny state file the hooks write and redraws. 🪶

## 🎛️ Controls

Click the light for a little menu:

- **Enabled** — grey it out / "unplug" it
- **Quit Greenlight**

Clicking the app icon while it's already running does nothing — no restart, no duplicate icons. 👍

## 🧰 What you need

- **macOS 10.13+**, Apple Silicon **or** Intel — the installer builds for your Mac.
- **A `python3`** (to build the tiny PyObjC venv). Don't have one? `xcode-select --install` or `brew install python`.
- **Claude Code** — that's what the light is watching. 🤖

## 🔧 How it works

Claude Code hooks → write a small `state.json` → the menu-bar app polls it and repaints. Everything lives in `~/Library/Application Support/Greenlight` and never leaves your machine.

> 💚 The green lamp shows a little logo. Drop a `wix_white.png` (white, transparent) next to the app to use your own.

## 👋 Uninstall

```bash
~/Library/Application\ Support/Greenlight/uninstall.sh
```

Removes the menu-bar app, the login agent, the hooks, and `Greenlight.app`.

<details>
<summary>🤓 Nerdy notes & troubleshooting</summary>

- **It launches as a plain process, not via the `.app`'s `exec`.** A bundle `exec python` launch leaves the macOS status item *invisible*; a plain process draws it. The LaunchAgent runs the script directly; the `.app` icon just kickstarts that agent.
- **Approval prompts blink red** — permission prompts ("Allow this command?"), `AskUserQuestion`, and `ExitPlanMode` all blink red until you act. Claude Code doesn't fire a `Notification` hook for permission prompts, so the hook keys off `PreToolUse`: any tool that *isn't* already in your allow-list will pop a prompt, so it blinks; allow-listed (auto-approved) tools stay solid orange. It snaps back to solid the instant the tool runs after you approve (instant for quick tools; a genuinely long-running prompted tool keeps blinking until it finishes, since there's no "approval granted" hook to flip on).
- **One light per machine** — it's shared across Claude Code sessions; concurrent sessions fight over the state. Fine for one active session.
- **Icon missing?** Run `~/Library/Application\ Support/Greenlight/greenlight.sh start`, or re-run the installer.
- **Light stopped updating?** Re-run the installer to repoint the hook (e.g. after upgrading Python).
- **Files:** `greenlight_app.py` (the menu-bar app), `greenlight_hook.py` (writes state), `greenlight.sh` (start/stop/restart/status), `install.sh` / `uninstall.sh`, `make_icon.py` + `build_icns.sh` (regenerate the icon).
- A backup of your pre-Greenlight settings is saved to `~/.claude/settings.json.bak.greenlight`.

</details>

<p align="center"><sub>Made with 🚦 for Claude Code.</sub></p>
