#!/usr/bin/env python3
"""Greenlight hook handler — called by Claude Code hooks.

Usage:  greenlight_hook.py <intent>
    working   -> solid amber   (Claude is working/thinking)
    waiting   -> blinking red  (Claude is waiting on you)
    idle      -> all dim
    stop      -> green         (turn finished)

It's a pure status light: a finished turn is always green — there is no
error/verdict path.

It also makes sure the floating light (greenlight_app.py) is running,
launching it detached if needed. Hooks must stay fast and never fail the
turn, so every step is best-effort and the script always exits 0.
"""
import json
import os
import subprocess
import sys

LAUNCHD_LABEL = "com.greenlight.menubar"
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
# Runtime files share ONE canonical dir (must match greenlight_app.py) so the
# state the hook writes is the state the app reads. Override with GREENLIGHT_DIR.
RUNTIME_DIR = os.environ.get("GREENLIGHT_DIR") or os.path.expanduser(
    "~/Library/Application Support/Greenlight")
STATE_FILE = os.path.join(RUNTIME_DIR, "state.json")
PID_FILE = os.path.join(RUNTIME_DIR, "app.pid")
LOG = os.path.join(RUNTIME_DIR, "app.log")
APP = os.path.join(CODE_DIR, "greenlight_app.py")
APP_PY = os.path.join(CODE_DIR, ".venv", "bin", "python")  # has PyObjC for the GUI

# Tools that ALWAYS hand control back to the user -> always blink.
ALWAYS_PROMPTS = {"AskUserQuestion", "ExitPlanMode"}
# defaultMode values under which a tool runs without ever prompting.
BLANKET_APPROVE_MODES = {"bypassPermissions"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def write_state(state: str) -> None:
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"state": state}, f)
    os.replace(tmp, STATE_FILE)


def app_running() -> bool:
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        pass
    try:
        return subprocess.run(
            ["pgrep", "-f", "greenlight_app.py"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except Exception:
        return False


def ensure_app() -> None:
    if app_running() or not os.path.exists(APP):
        return
    # Prefer launchd so it owns the lifecycle (and restarts the light on crash).
    # Falls back to a detached spawn if the LaunchAgent isn't loaded.
    target = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
    try:
        loaded = subprocess.run(
            ["launchctl", "print", target],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
        if loaded:
            subprocess.run(
                ["launchctl", "kickstart", target],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
    except Exception:
        pass
    try:
        with open(LOG, "a") as log:
            subprocess.Popen(
                [APP_PY, APP],
                stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception:
        pass


def _settings_files(cwd: str) -> list:
    home = os.path.expanduser("~/.claude")
    paths = [os.path.join(home, "settings.json"),
             os.path.join(home, "settings.local.json")]
    if cwd:
        paths += [os.path.join(cwd, ".claude", "settings.json"),
                  os.path.join(cwd, ".claude", "settings.local.json")]
    return paths


def _load_permissions(cwd: str) -> tuple:
    """Collect permissions.allow rules and the defaultMode across user- and
    project-level settings. Best-effort: unreadable/missing files are skipped."""
    allow, mode = [], None
    for p in _settings_files(cwd):
        try:
            with open(p) as f:
                perms = json.load(f).get("permissions", {})
        except Exception:
            continue
        allow.extend(perms.get("allow", []))
        mode = perms.get("defaultMode", mode)
    return allow, mode


def _rule_allows(rule: str, tool: str, tool_input: dict) -> bool:
    """Does a single allow rule cover this tool call? Mirrors the common Claude
    Code rule shapes; deliberately simple — when unsure we say no (see caller)."""
    if rule == tool:                                  # exact: Read, mcp__s__tool…
        return True
    if (tool.startswith("mcp__") and rule.startswith("mcp__")
            and tool.startswith(rule + "__")):        # whole-server grant
        return True
    if tool == "Bash" and rule.startswith("Bash(") and rule.endswith(")"):
        pat = rule[5:-1]
        cmd = (tool_input or {}).get("command", "")
        if pat in ("", "*"):
            return True
        if pat.endswith(":*"):                         # "git status:*" prefix form
            return cmd.startswith(pat[:-2])
        if pat.endswith("*"):
            return cmd.startswith(pat[:-1])
        return cmd == pat
    if rule.endswith("*") and tool.startswith(rule[:-1]):   # generic wildcard
        return True
    return False


def tool_will_prompt(tool: str, tool_input: dict, cwd: str) -> bool:
    """True if calling `tool` will pop an approve/deny prompt — i.e. it isn't
    already covered by an allow rule (and we're not in a blanket-approve mode).
    Lets us blink the light *before* the user has to click. On ANY uncertainty
    we return False (stay solid): a missed blink is friendlier than a light that
    blinks through routine auto-approved work."""
    try:
        allow, mode = _load_permissions(cwd)
        if mode in BLANKET_APPROVE_MODES:
            return False
        if mode == "acceptEdits" and tool in EDIT_TOOLS:
            return False
        return not any(_rule_allows(r, tool, tool_input) for r in allow)
    except Exception:
        return False


def main() -> None:
    intent = sys.argv[1] if len(sys.argv) > 1 else "idle"
    try:
        hook_input = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        hook_input = {}

    # React to Claude Code ONLY. Other agents (e.g. Cursor's built-in chat) also
    # run ~/.claude hooks. Identify Claude Code positively via the CLAUDECODE=1 env
    # var it always sets (Cursor does not); fall back to a /.claude/ transcript_path
    # when the env is absent. Gating on transcript_path alone is brittle: Claude
    # Code sometimes sends an empty/missing path, which would silently no-op the
    # light, while Cursor may omit it too -> can't distinguish on path alone.
    tp = hook_input.get("transcript_path") or ""
    is_claude_code = os.environ.get("CLAUDECODE") == "1" or "/.claude/" in tp
    if not is_claude_code:
        sys.exit(0)

    if intent == "stop":
        # Pure status light: a finished turn is always green, no verdict parsing.
        state = "go"
    elif intent == "pretool":
        # Blink when the user is about to be asked to act: tools that always
        # prompt, plus any tool that isn't pre-approved (so an approve/deny
        # dialog will pop and block right after this hook). Notification doesn't
        # fire for prompts here, so PreToolUse is our only pre-prompt signal.
        # PostToolUse flips back to solid amber once the tool actually runs.
        tool = hook_input.get("tool_name", "")
        if tool in ALWAYS_PROMPTS or tool_will_prompt(
                tool, hook_input.get("tool_input", {}), hook_input.get("cwd", "")):
            state = "waiting"
        else:
            state = "working"
    elif intent in {"working", "waiting", "idle", "go"}:
        state = intent
    else:
        state = "idle"

    try:
        write_state(state)
        ensure_app()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
