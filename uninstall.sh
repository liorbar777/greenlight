#!/usr/bin/env bash
# Greenlight uninstaller — removes hooks + the LaunchAgent. Leaves the repo files.
set -euo pipefail
PY="${GREENLIGHT_PY:-/Users/liorbar/.local/share/uv/python/cpython-3.11.14-macos-aarch64-none/bin/python3.11}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$PROJECT_DIR/greenlight_hook.py"
LABEL="com.liorbar.greenlight"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
SETTINGS="$HOME/.claude/settings.json"

echo "==> Unloading + removing LaunchAgent"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
rm -f "$PLIST"

echo "==> Removing Greenlight hook groups from $SETTINGS"
HOOK="$HOOK" SETTINGS="$SETTINGS" "$PY" - <<'PYEOF'
import json, os
S, HOOK = os.environ["SETTINGS"], os.environ["HOOK"]
s = json.load(open(S)); hooks = s.get("hooks", {})
def is_gl(g): return any("greenlight_hook.py" in h.get("command", "") for h in g.get("hooks", []))
for ev in list(hooks):
    hooks[ev][:] = [g for g in hooks[ev] if not is_gl(g)]
    if not hooks[ev]: del hooks[ev]
json.dump(s, open(S, "w"), indent=2)
print("   removed.")
PYEOF

pkill -f greenlight_app.py 2>/dev/null || true
echo "==> Done. (Repo files left in place; 'rm -rf' the folder to delete them.)"
echo "    Also remove the 'Greenlight Verdict Marker' section from ~/.claude/CLAUDE.md if you added it."
