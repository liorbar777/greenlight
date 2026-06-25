#!/usr/bin/env python3
"""Greenlight hook handler — called by Claude Code hooks.

Usage:  greenlight_hook.py <intent>
    working   -> solid amber   (Claude is working/thinking)
    waiting   -> blinking amber (Claude is waiting on you)
    idle      -> all dim
    stop      -> green, unless the final assistant message CLOSES with a
                 negative verdict marker (its own line, last non-empty line),
                 then red.

Verdict marker (case-insensitive). It only counts as a verdict when it is the
LAST non-empty line of the message (a deliberate footer) — quoting or explaining
the marker mid-message, or ending on a question, does NOT trip the light:
    green: GREENLIGHT: GO / GREEN / GOOD / PASS[ED] / OK[AY] / SUCCESS / DONE /
           SHIP[PED] / APPROVED / LGTM
    red:   GREENLIGHT: NO-GO / RED / FAIL[ED]/FAILURE / BAD / BLOCK[ED] /
           STOP[PED] / ERROR / REJECT[ED] / ABORT[ED]

It also makes sure the floating light (greenlight_app.py) is running,
launching it detached if needed. Hooks must stay fast and never fail the
turn, so every step is best-effort and the script always exits 0.
"""
import json
import os
import re
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

# A verdict only counts when it stands alone as a PLAIN footer line at column 0
# (e.g. "GREENLIGHT: NO-GO — reason"). The marker must START the line with no
# leading whitespace or markdown markup. Combined with resolve_stop_state (which
# checks ONLY the last non-empty line, after stripping fenced code blocks), this
# means a marker that is quoted in prose, wrapped in backticks, indented, inside
# a blockquote, or shown inside a ``` example never trips the light — and a turn
# that ends on a question or any normal sentence stays green. Only a deliberate
# closing verdict does.
VERDICT_LINE_RE = re.compile(
    r"^GREENLIGHT\s*[:=\-]\s*"
    # longer variants first so the full word is captured (PASSED before PASS, etc.)
    r"(NO[\s\-_]?GO|NOGO|GREEN|GO|GOOD|PASSED|PASS|OKAY|OK|SUCCESS|DONE|SHIPPED|SHIP|APPROVED|LGTM|"
    r"RED|FAILED|FAILURE|FAIL|BAD|BLOCKED|BLOCK|STOPPED|STOP|ERROR|REJECTED|REJECT|ABORTED|ABORT)\b",
    re.IGNORECASE,
)
NEGATIVE = {"no-go", "nogo", "red", "fail", "failed", "failure", "bad", "block",
            "blocked", "stop", "stopped", "error", "reject", "rejected",
            "abort", "aborted"}
TAIL_BYTES = 262144  # read only the last 256 KB of the transcript (one message)

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


def last_assistant_text(transcript_path: str) -> str:
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            chunk = f.read().decode("utf-8", "replace")
    except Exception:
        return ""
    # A truncated leading line just fails json.loads and is skipped; the final
    # assistant message is always fully contained in the tail.
    for line in reversed(chunk.splitlines()):
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("type") != "assistant":
            continue
        content = entry.get("message", {}).get("content", [])
        if isinstance(content, str):
            return content
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        text = " ".join(p for p in parts if p)
        if text.strip():
            return text
    return ""


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


def resolve_stop_state(hook_input: dict) -> str:
    # Green by default. Red ONLY when the assistant closes the turn with a
    # deliberate verdict footer: a PLAIN marker line at column 0 that is the
    # last non-empty line of the message, ignoring fenced code blocks. So a real
    # negative verdict (no-go PR, error, failed build, blocked task) turns it
    # red, while quoting/explaining the marker in prose, in backticks, indented,
    # inside a ``` example, or ending the turn on a question stays green.
    # We deliberately do NOT blink just because the message ends with a question:
    # blinking is reserved for real blocking prompts (AskUserQuestion / plan /
    # permission approvals), handled in the pretool branch.
    path = hook_input.get("transcript_path", "")
    text = last_assistant_text(path) if path else ""
    # Drop fenced code blocks so a marker SHOWN as an example never counts.
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    last_line = ""
    for ln in reversed(text.splitlines()):
        if ln.strip():
            last_line = ln.rstrip()  # keep leading indent so indented lines fail ^GREENLIGHT
            break
    m = VERDICT_LINE_RE.match(last_line)
    if m:
        token = m.group(1).lower().replace("_", "-").replace(" ", "-")
        return "nogo" if token in NEGATIVE else "go"
    return "go"


def main() -> None:
    intent = sys.argv[1] if len(sys.argv) > 1 else "idle"
    try:
        hook_input = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        hook_input = {}

    # React to Claude Code ONLY. Other agents (e.g. Cursor's built-in chat) also
    # run ~/.claude hooks, but their transcript lives under ~/.cursor/ instead of
    # ~/.claude/. Ignore anything that isn't a Claude Code transcript.
    tp = hook_input.get("transcript_path") or ""
    if tp and "/.claude/" not in tp:
        sys.exit(0)

    if intent == "stop":
        state = resolve_stop_state(hook_input)
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
    elif intent in {"working", "waiting", "idle", "go", "nogo"}:
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
