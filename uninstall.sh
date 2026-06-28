#!/usr/bin/env bash
# Greenlight uninstaller — removes the LaunchAgent, Claude Code hooks, the
# Greenlight.app bundle, and the App Support runtime. Idempotent.
set -euo pipefail

# A python3 for the settings.json edit (stdlib only; the venv may be deleted).
if [ -z "${GREENLIGHT_PY:-}" ]; then
  for c in python3.11 python3 /usr/bin/python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'pass' 2>/dev/null; then GREENLIGHT_PY="$(command -v "$c")"; break; fi
  done
fi
PY="${GREENLIGHT_PY:?No working python3 found. Set GREENLIGHT_PY=/path/to/python3.}"

APP_DIR="${GREENLIGHT_DIR:-$HOME/Library/Application Support/Greenlight}"
LABEL="com.greenlight.menubar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
SETTINGS="$HOME/.claude/settings.json"

echo "==> Unloading + removing LaunchAgent"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
rm -f "$PLIST"

echo "==> Stopping the app"
pkill -f greenlight_app.py 2>/dev/null || true

echo "==> Removing Greenlight.app"
rm -rf "/Applications/Greenlight.app" "$HOME/Applications/Greenlight.app"

if [ -f "$SETTINGS" ]; then
  echo "==> Removing Greenlight hook groups from $SETTINGS"
  SETTINGS="$SETTINGS" "$PY" - <<'PYEOF'
import json, os
S = os.environ["SETTINGS"]
s = json.load(open(S)); hooks = s.get("hooks", {})
def is_gl(g): return any("greenlight_hook.py" in h.get("command", "") for h in g.get("hooks", []))
for ev in list(hooks):
    hooks[ev][:] = [g for g in hooks[ev] if not is_gl(g)]
    if not hooks[ev]: del hooks[ev]
json.dump(s, open(S, "w"), indent=2)
print("   removed.")
PYEOF
else
  echo "==> No $SETTINGS found; skipping hook cleanup"
fi

# Remove the managed runtime dir (only the default App Support location, never a dev clone).
if [ "$APP_DIR" = "$HOME/Library/Application Support/Greenlight" ] && [ -d "$APP_DIR" ]; then
  echo "==> Removing runtime $APP_DIR"
  rm -rf "$APP_DIR"
else
  echo "==> Leaving $APP_DIR in place (non-default location)."
fi

echo "==> Done."
echo "    Also delete the 'Greenlight Verdict Marker' section from ~/.claude/CLAUDE.md if you added it."
