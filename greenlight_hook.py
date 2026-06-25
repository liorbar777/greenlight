#!/usr/bin/env python3
"""Greenlight hook handler — called by Claude Code hooks.

Usage:  greenlight_hook.py <intent>
    working   -> solid amber   (Claude is working/thinking)
    waiting   -> blinking amber (Claude is waiting on you)
    idle      -> all dim
    stop      -> green, unless the final assistant message carries a
                 negative verdict marker, then red.

Verdict marker (case-insensitive, anywhere in Claude's final message):
    GREENLIGHT: GO      / GREEN / PASS / GOOD   -> green
    GREENLIGHT: NO-GO   / RED   / FAIL / BAD    -> red

It also makes sure the floating light (greenlight_app.py) is running,
launching it detached if needed. Hooks must stay fast and never fail the
turn, so every step is best-effort and the script always exits 0.
"""
import json
import os
import re
import subprocess
import sys

PY = "/Users/liorbar/.local/share/uv/python/cpython-3.11.14-macos-aarch64-none/bin/python3.11"
LAUNCHD_LABEL = "com.liorbar.greenlight"
HOME = os.path.expanduser("~")
BASE_DIR = os.path.join(HOME, "Documents", "all_projects", "greenlight")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
PID_FILE = os.path.join(BASE_DIR, "app.pid")
APP = os.path.join(BASE_DIR, "greenlight_app.py")
LOG = os.path.join(BASE_DIR, "app.log")

VERDICT_RE = re.compile(
    r"GREENLIGHT\s*[:=\-]\s*(NO[\s\-_]?GO|NOGO|GO|RED|GREEN|FAIL|PASS|BAD|GOOD)",
    re.IGNORECASE,
)
NEGATIVE = {"no-go", "nogo", "red", "fail", "bad"}
TAIL_BYTES = 262144  # read only the last 256 KB of the transcript (one message)


def write_state(state: str) -> None:
    os.makedirs(BASE_DIR, exist_ok=True)
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
                [PY, APP],
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
