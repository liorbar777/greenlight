#!/usr/bin/env python3
"""Greenlight hook handler — called by Claude Code hooks.

Usage:  greenlight_hook.py <intent>
    working   -> solid amber   (Claude is working/thinking)
    waiting   -> blinking amber (Claude is waiting on you)
    idle      -> all dim
    stop      -> green, unless the final assistant message carries a
                 negative verdict marker, then red.

Verdict marker (case-insensitive, anywhere in Claude's final message):
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

VERDICT_RE = re.compile(
    r"GREENLIGHT\s*[:=\-]\s*"
    # longer variants first so the full word is captured (PASSED before PASS, etc.)
    r"(NO[\s\-_]?GO|NOGO|GREEN|GO|GOOD|PASSED|PASS|OKAY|OK|SUCCESS|DONE|SHIPPED|SHIP|APPROVED|LGTM|"
    r"RED|FAILED|FAILURE|FAIL|BAD|BLOCKED|BLOCK|STOPPED|STOP|ERROR|REJECTED|REJECT|ABORTED|ABORT)\b",
    re.IGNORECASE,
)
NEGATIVE = {"no-go", "nogo", "red", "fail", "failed", "failure", "bad", "block",
            "blocked", "stop", "stopped", "error", "reject", "rejected",
            "abort", "aborted"}
TAIL_BYTES = 262144  # read only the last 256 KB of the transcript (one message)


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


def resolve_stop_state(hook_input: dict) -> str:
    path = hook_input.get("transcript_path", "")
    text = last_assistant_text(path) if path else ""
    matches = VERDICT_RE.findall(text)
    if matches:
        # Last marker wins, in case more than one appears in the message.
        token = matches[-1].lower().replace("_", "-").replace(" ", "-")
        if token in NEGATIVE:
            return "nogo"
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
        # Tool-aware: tools that prompt the user mean "waiting on you".
        tool = hook_input.get("tool_name", "")
        state = "waiting" if tool in {"AskUserQuestion", "ExitPlanMode"} else "working"
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
