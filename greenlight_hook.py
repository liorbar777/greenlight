#!/usr/bin/env python3
"""Greenlight hook handler — called by Claude Code hooks.

Usage:  greenlight_hook.py <intent>
    working   -> solid amber   (Claude is working/thinking)
    waiting   -> blinking red   (Claude is waiting on you — known block)
    idle      -> all dim
    stop      -> green          (turn finished)

It's a pure status light: a finished turn is always green — there is no
error/verdict path.

Blink policy (the hard part): the hook gets PreToolUse / PostToolUse, but Claude
Code fires NO signal for a permission prompt, and "tool is awaiting your approval"
looks identical to "tool is just slow" — both are PreToolUse-with-no-PostToolUse.
So we can't decide at pretool time whether a tool will block. Instead:

  * tools we KNOW always block (AskUserQuestion / ExitPlanMode) -> "waiting"
    (blink immediately).
  * tools that can't prompt (allow-listed, read-only, bypass/plan) -> "working"
    (solid amber).
  * everything else (MCP/Bash/edit not covered by an allow rule) -> "pending":
    solid amber NOW, stamped with `pending_since`. The menu-bar app escalates a
    pending to a red blink only after it has lingered (default 2.5s) with no
    PostToolUse — i.e. it's almost certainly sitting on an approve/deny dialog.
    A fast auto-approved call (incl. session-granted MCP the allow-list can't
    see) fires its PostToolUse well before then, which clears the pending -> it
    never blinks. That's how we blink REAL prompts without strobing routine work.

It also makes sure the floating light (greenlight_app.py) is running, launching
it detached if needed. Hooks must stay fast and never fail the turn, so every
step is best-effort and the script always exits 0.
"""
import json
import os
import subprocess
import sys
import time

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

# Tools that ALWAYS hand control back to the user -> blink immediately (no wait).
ALWAYS_PROMPTS = {"AskUserQuestion", "ExitPlanMode"}
# defaultMode values under which a tool runs without ever prompting.
BLANKET_APPROVE_MODES = {"bypassPermissions"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Auto-approved tools Claude Code runs WITHOUT an allow-rule, so they never
# prompt. Keeps the light solid (no flash / no false escalation). ToolSearch is
# here too: it can block for seconds on connecting MCP servers but never prompts.
SAFE_READONLY_TOOLS = {
    "Read", "Glob", "Grep", "LS", "NotebookRead",
    "TodoWrite", "WebFetch", "WebSearch", "Task", "ToolSearch",
}


def read_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(payload: dict) -> None:
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
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
    # Trailing-* glob: Claude Code honors it ONLY when anchored after a
    # glob-free `mcp__<server>__` prefix (e.g. mcp__srv__tool*). Unanchored
    # globs (mcp__*, B*, *) are skipped by Claude Code, so we must not match
    # them either — else the light stays solid on a real prompt.
    if rule.endswith("*") and rule.startswith("mcp__"):
        prefix = rule[:-1]                            # strip trailing *
        if "__" in prefix[len("mcp__"):]:             # server__ present & glob-free
            return tool.startswith(prefix)
    return False


def tool_might_prompt(tool: str, tool_input: dict, cwd: str, mode: str = "") -> bool:
    """True if calling `tool` is NOT already covered by an allow rule (and we're
    not in a blanket-approve mode) — i.e. it *might* pop an approve/deny prompt.
    Such tools become "pending": solid now, escalating to a blink only if they
    actually linger (the app's job). On ANY uncertainty we return False (treat as
    non-prompting / solid): a missed blink is friendlier than a false one.

    `mode` is the LIVE permission mode from the hook payload; it wins over the
    static `defaultMode` in settings.json (which doesn't reflect the in-session
    plan/acceptEdits/bypass toggle)."""
    try:
        allow, settings_mode = _load_permissions(cwd)
        mode = mode or settings_mode
        if mode in BLANKET_APPROVE_MODES:
            return False
        if mode == "acceptEdits" and tool in EDIT_TOOLS:
            return False
        return not any(_rule_allows(r, tool, tool_input) for r in allow)
    except Exception:
        return False


def compute_pretool_state(hook_input: dict) -> dict:
    """Map a PreToolUse payload to a state payload. See the module docstring for
    the blink policy. Order matters."""
    tool = hook_input.get("tool_name", "")
    pmode = hook_input.get("permission_mode") or ""
    now = time.time()
    if tool in ALWAYS_PROMPTS:                       # known block -> blink now
        return {"state": "waiting", "pending_tool": tool}
    if pmode in BLANKET_APPROVE_MODES:               # nothing ever prompts
        return {"state": "working"}
    if pmode == "plan":                              # reads auto, edits blocked
        return {"state": "working"}
    if tool in SAFE_READONLY_TOOLS:                  # auto-approved, never prompts
        return {"state": "working"}
    if tool_might_prompt(tool, hook_input.get("tool_input", {}),
                         hook_input.get("cwd", ""), pmode):
        # MIGHT prompt: stay solid; the app escalates to a blink if it lingers.
        return {"state": "pending", "pending_tool": tool, "pending_since": now}
    return {"state": "working"}                      # allow-listed -> solid


def main() -> None:
    intent = sys.argv[1] if len(sys.argv) > 1 else "idle"
    try:
        hook_input = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        hook_input = {}

    # React to Claude Code ONLY. Other agents (e.g. Cursor's built-in chat) also
    # run ~/.claude hooks. Identify Claude Code positively via the CLAUDECODE=1 env
    # var it always sets (Cursor does not); fall back to a /.claude/ transcript_path
    # when the env is absent.
    tp = hook_input.get("transcript_path") or ""
    is_claude_code = os.environ.get("CLAUDECODE") == "1" or "/.claude/" in tp
    if not is_claude_code:
        sys.exit(0)

    tool = hook_input.get("tool_name", "")
    if intent == "stop":
        new = {"state": "go"}                        # finished turn is always green
    elif intent == "pretool":
        new = compute_pretool_state(hook_input)
    elif intent == "working":
        # PostToolUse (a tool just finished) or UserPromptSubmit (new turn).
        # PostToolUse carries tool_name; UserPromptSubmit does not.
        new = {"state": "working", "_finished_tool": tool}
    elif intent in {"waiting", "working", "go", "idle"}:
        new = {"state": intent}
    else:
        new = {"state": "idle"}

    # Resolve a "working" against an active prompt so a *sibling* tool finishing
    # (or an allow-listed sibling starting) can't clobber the prompt's state.
    # Tools batched in one turn fire their hooks within milliseconds, racing to
    # write this single file (last write wins). Only these clear an active
    # waiting/pending: the SAME tool's PostToolUse (the prompt was answered), or
    # a UserPromptSubmit (a brand-new user turn). Everything else preserves it.
    if new["state"] == "working":
        cur = read_state()
        if cur.get("state") in ("waiting", "pending"):
            # Only a genuine "working" intent may clear an active prompt/pending:
            #   - PostToolUse of the SAME tool (the prompt was answered / it ran), or
            #   - UserPromptSubmit (no tool_name) = a brand-new user turn.
            # A *sibling* tool's pretool (allow-listed -> "working") or PostToolUse
            # must NOT clobber the prompt — preserve it.
            clears = False
            if intent == "working":
                finished = new.get("_finished_tool", "")
                clears = (finished == "") or (finished == cur.get("pending_tool"))
            if not clears:
                ensure_app()                     # leave the prompt state intact
                sys.exit(0)
    new.pop("_finished_tool", None)

    try:
        write_state(new)
        ensure_app()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
