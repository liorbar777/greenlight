#!/usr/bin/env bash
# Greenlight installer. Works two ways:
#   • Clone-free:  curl -fsSL https://raw.githubusercontent.com/liorbar777/greenlight/master/install.sh | bash
#   • From a clone: ./install.sh
#
# It installs the runtime to ~/Library/Application Support/Greenlight, builds a
# PyObjC venv, creates a Greenlight.app in your Applications folder, wires the
# Claude Code hooks, and installs a login LaunchAgent (start at login + relaunch
# on crash). Idempotent: safe to re-run.
set -euo pipefail

# ---- where the app is hosted (for the clone-free path) ----------------------
# Override with: GREENLIGHT_REPO=you/greenlight GREENLIGHT_REF=master curl ... | bash
REPO="${GREENLIGHT_REPO:-liorbar777/greenlight}"     # <-- GitHub owner/repo
REF="${GREENLIGHT_REF:-master}"                    # branch or tag
RAW="https://raw.githubusercontent.com/$REPO/$REF"

# ---- install locations ------------------------------------------------------
APP_DIR="${GREENLIGHT_DIR:-$HOME/Library/Application Support/Greenlight}"   # runtime + code + venv
LABEL="com.greenlight.menubar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
SETTINGS="$HOME/.claude/settings.json"
BUNDLE_NAME="Greenlight.app"

FILES=(greenlight_app.py greenlight_hook.py greenlight.sh uninstall.sh requirements.txt)
OPTIONAL=(wix_white.png icon.icns)

# ---- 1. stage source files into APP_DIR (copy if local clone, else download) -
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
mkdir -p "$APP_DIR"
if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/greenlight_app.py" ]; then
  echo "==> Installing from local clone: $SELF_DIR"
  if [ "$SELF_DIR" != "$APP_DIR" ]; then
    for f in "${FILES[@]}"; do cp "$SELF_DIR/$f" "$APP_DIR/$f"; done
    for f in "${OPTIONAL[@]}"; do [ -f "$SELF_DIR/$f" ] && cp "$SELF_DIR/$f" "$APP_DIR/$f" || true; done
  fi
else
  echo "==> Downloading Greenlight from $REPO@$REF"
  command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required for clone-free install."; exit 1; }
  for f in "${FILES[@]}"; do
    curl -fsSL "$RAW/$f" -o "$APP_DIR/$f" || { echo "ERROR: failed to fetch $f from $RAW"; exit 1; }
  done
  for f in "${OPTIONAL[@]}"; do curl -fsSL "$RAW/$f" -o "$APP_DIR/$f" 2>/dev/null || true; done
fi
chmod +x "$APP_DIR/greenlight.sh" "$APP_DIR/uninstall.sh" 2>/dev/null || true

# ---- 2. build the venv (any python3 bootstraps it; everything else uses venv) -
BOOT_PY="${GREENLIGHT_PY:-}"
if [ -z "$BOOT_PY" ]; then
  # Search PATH names and both arches' Homebrew prefixes (/opt/homebrew = Apple
  # Silicon, /usr/local = Intel) plus the system Python. Needs the venv module.
  for c in python3 python3.13 python3.12 python3.11 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if p="$(command -v "$c" 2>/dev/null)" && "$p" -c 'import venv' 2>/dev/null; then
      BOOT_PY="$p"; break
    fi
  done
fi
if [ -z "$BOOT_PY" ]; then
  echo "ERROR: no usable python3 found to build the venv. Install one of:"
  echo "    • Xcode Command Line Tools:  xcode-select --install"
  echo "    • Homebrew Python:           brew install python"
  echo "  then re-run, or pass GREENLIGHT_PY=/path/to/python3 ./install.sh"
  exit 1
fi

VENV="$APP_DIR/.venv"
APP_PY="$VENV/bin/python"
HOOK="$APP_DIR/greenlight_hook.py"
APP="$APP_DIR/greenlight_app.py"
echo "==> Building venv + PyObjC ($BOOT_PY)"
[ -x "$APP_PY" ] || "$BOOT_PY" -m venv "$VENV"
"$APP_PY" -m pip install --quiet --upgrade pip
"$APP_PY" -m pip install --quiet -r "$APP_DIR/requirements.txt"
"$APP_PY" -c 'import AppKit' 2>/dev/null || { echo "ERROR: PyObjC import failed in venv."; exit 1; }

# ---- 3. build Greenlight.app (thin launcher → venv python on the App Support code)
APPS_DIR="/Applications"
[ -w "$APPS_DIR" ] || APPS_DIR="$HOME/Applications"
mkdir -p "$APPS_DIR"
BUNDLE="$APPS_DIR/$BUNDLE_NAME"
echo "==> Creating $BUNDLE"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cat > "$BUNDLE/Contents/Info.plist" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Greenlight</string>
    <key>CFBundleDisplayName</key><string>Greenlight</string>
    <key>CFBundleIdentifier</key><string>$LABEL</string>
    <key>CFBundleExecutable</key><string>Greenlight</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>LSUIElement</key><true/>
    <key>LSMinimumSystemVersion</key><string>10.13</string>
    $( [ -f "$APP_DIR/icon.icns" ] && echo '<key>CFBundleIconFile</key><string>icon</string>' )
</dict>
</plist>
PLISTEOF
[ -f "$APP_DIR/icon.icns" ] && cp "$APP_DIR/icon.icns" "$BUNDLE/Contents/Resources/icon.icns" || true
cat > "$BUNDLE/Contents/MacOS/Greenlight" <<LAUNCHEOF
#!/bin/bash
# Greenlight.app launcher. A bundle 'exec python' launch leaves the menu-bar
# item invisible, so we don't run python here. Behaviour:
#   • already running  -> do nothing (just un-hide if it was hidden); NO restart
#   • not running      -> start the launchd agent (plain process draws correctly)
if pgrep -f greenlight_app.py >/dev/null 2>&1; then
  printf '{"visible": true}' > "$APP_DIR/control.json"
  exit 0
fi
launchctl kickstart "gui/\$(id -u)/$LABEL" 2>/dev/null || nohup "$APP_PY" "$APP" >/dev/null 2>&1 &
LAUNCHEOF
chmod +x "$BUNDLE/Contents/MacOS/Greenlight"

# ---- 4. wire Claude Code hooks (hook runs under the venv python; paths quoted) -
echo "==> Wiring Claude Code hooks into $SETTINGS"
mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] || echo '{}' >"$SETTINGS"
cp "$SETTINGS" "$SETTINGS.bak.greenlight"
PY="$APP_PY" HOOK="$HOOK" SETTINGS="$SETTINGS" "$APP_PY" - <<'PYEOF'
import json, os
S, PY, HOOK = os.environ["SETTINGS"], os.environ["PY"], os.environ["HOOK"]
s = json.load(open(S)); hooks = s.setdefault("hooks", {})
def cmd(i): return f'"{PY}" "{HOOK}" {i}'          # quote paths (App Support has a space)
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

# ---- 5. LaunchAgent: start at login + relaunch on crash (drives the bundle) ---
echo "==> Writing LaunchAgent $PLIST"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <!-- Run the script DIRECTLY (not via the .app bundle). A bundle 'exec python'
         launch leaves the menu-bar status item invisible; a plain process draws
         it correctly. launchd supervises this process for RunAtLoad + KeepAlive. -->
    <key>ProgramArguments</key>
    <array>
        <string>$APP_PY</string>
        <string>$APP</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
    <key>LimitLoadToSessionType</key><string>Aqua</string>
    <key>StandardOutPath</key><string>$APP_DIR/app.log</string>
    <key>StandardErrorPath</key><string>$APP_DIR/app.log</string>
</dict>
</plist>
PLISTEOF

echo "==> (Re)loading LaunchAgent"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
  launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
  launchctl kickstart "$DOMAIN/$LABEL" 2>/dev/null || true
else
  # Older macOS without the modern launchctl verbs.
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load -w "$PLIST" 2>/dev/null || true
fi

echo "==> Done."
echo "    • Menu-bar light: should now be beside your system icons."
echo "    • App: $BUNDLE (Applications / Launchpad)."
echo "    • Auto red/green: add the 'Greenlight Verdict Marker' rule to ~/.claude/CLAUDE.md (see README)."
