#!/usr/bin/env bash
# Greenlight installer — venv + PyObjC, Claude Code hooks, login LaunchAgent.
# Idempotent: safe to re-run. Paths are derived from this script's location.
set -euo pipefail

# Python used to (a) create the venv and (b) run the lightweight state hook.
# Override with: GREENLIGHT_PY=/path/to/python3 ./install.sh
PY="${GREENLIGHT_PY:-/Users/liorbar/.local/share/uv/python/cpython-3.11.14-macos-aarch64-none/bin/python3.11}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$PROJECT_DIR/.venv"
APP_PY="$VENV/bin/python"            # runs the menu-bar app (needs PyObjC)
HOOK="$PROJECT_DIR/greenlight_hook.py"
APP="$PROJECT_DIR/greenlight_app.py"
LABEL="com.liorbar.greenlight"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
SETTINGS="$HOME/.claude/settings.json"

echo "==> Creating venv + installing PyObjC"
[ -x "$APP_PY" ] || "$PY" -m venv "$VENV"
"$APP_PY" -m pip install --quiet --upgrade pip
"$APP_PY" -m pip install --quiet -r "$PROJECT_DIR/requirements.txt"
"$APP_PY" -c 'import AppKit' 2>/dev/null || { echo "ERROR: PyObjC import failed in venv"; exit 1; }

echo "==> Merging hooks into $SETTINGS"
cp "$SETTINGS" "$SETTINGS.bak.greenlight"
PY="$PY" HOOK="$HOOK" SETTINGS="$SETTINGS" "$PY" - <<'PYEOF'
import json, os
S, PY, HOOK = os.environ["SETTINGS"], os.environ["PY"], os.environ["HOOK"]
s = json.load(open(S)); hooks = s.setdefault("hooks", {})
def cmd(i): return f"{PY} {HOOK} {i}"
def group(i, m=None):
    g = {"hooks": [{"type": "command", "command": cmd(i)}]}
    if m is not None: g["matcher"] = m
    return g
def is_gl(g): return any("greenlight_hook.py" in h.get("command", "") for h in g.get("hooks", []))
wiring = {"UserPromptSubmit": ("working", None), "PreToolUse": ("pretool", "*"),
          "PostToolUse": ("working", "*"), "Notification": ("waiting", None),
          "Stop": ("stop", None), "SessionStart": ("idle", None)}
for ev, (intent, m) in wiring.items():
    grp = hooks.setdefault(ev, [])
    grp[:] = [g for g in grp if not is_gl(g)]
    grp.append(group(intent, m))
json.dump(s, open(S, "w"), indent=2)
print("   hooks wired:", ", ".join(wiring))
PYEOF

echo "==> Writing LaunchAgent $PLIST"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array><string>$APP_PY</string><string>$APP</string></array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
    <key>LimitLoadToSessionType</key><string>Aqua</string>
    <key>StandardOutPath</key><string>$PROJECT_DIR/app.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/app.log</string>
</dict>
</plist>
PLISTEOF

echo "==> (Re)loading LaunchAgent"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"

echo "==> Done. A 3-lamp traffic light should now be in your menu bar."
echo "    Optional: add the 'Greenlight Verdict Marker' rule to ~/.claude/CLAUDE.md (see README)."
