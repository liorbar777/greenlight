#!/usr/bin/env bash
# Greenlight control: start | stop | restart | status
# Prefers the LaunchAgent (com.greenlight.menubar). When launchd isn't loaded it
# launches the .app via `open` (LaunchServices) so the menu-bar item shows.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$DIR/.venv/bin/python"     # the menu-bar app needs PyObjC from the venv
APP="$DIR/greenlight_app.py"
LABEL="com.greenlight.menubar"
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
RT_DIR="${GREENLIGHT_DIR:-$HOME/Library/Application Support/Greenlight}"   # state.json lives here

# Greenlight.app location (built by install.sh)
BUNDLE=""
for b in "/Applications/Greenlight.app" "$HOME/Applications/Greenlight.app"; do
  [ -d "$b" ] && BUNDLE="$b" && break
done

launchd_loaded() { launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; }

# Launch the app the reliable way: via the .app bundle (LaunchServices) if we
# have one, else a detached venv-python process.
spawn_app() {
  if [ -n "$BUNDLE" ]; then
    open "$BUNDLE" && echo "started ($BUNDLE)"
  else
    nohup "$PY" "$APP" >>"$RT_DIR/app.log" 2>&1 &
    echo "started (pid $!)"
  fi
}

case "${1:-start}" in
  start)
    if launchd_loaded; then
      launchctl kickstart "$DOMAIN/$LABEL" && echo "started (launchd)"
    elif [ -f "$PLIST" ]; then
      launchctl bootstrap "$DOMAIN" "$PLIST" && echo "loaded LaunchAgent (launchd)"
    elif pgrep -f greenlight_app.py >/dev/null; then
      echo "already running (pid $(pgrep -f greenlight_app.py))"
    else
      spawn_app
    fi
    ;;
  stop)
    if launchd_loaded; then
      launchctl bootout "$DOMAIN/$LABEL" && echo "stopped (launchd job booted out; returns at next login)"
    else
      pkill -f greenlight_app.py && echo "stopped" || echo "not running"
    fi
    rm -f "$RT_DIR/app.pid"
    ;;
  restart)
    if launchd_loaded; then
      launchctl kickstart -k "$DOMAIN/$LABEL" && echo "restarted (launchd)"
    else
      pkill -f greenlight_app.py 2>/dev/null || true
      sleep 0.3
      spawn_app
    fi
    ;;
  status)
    if launchd_loaded; then
      echo "launchd: loaded"
      launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state =|pid =" | sed 's/^[[:space:]]*//'
    else
      echo "launchd: not loaded"
    fi
    if pgrep -fl greenlight_app.py; then :; else echo "process: not running"; fi
    echo "state: $(cat "$RT_DIR/state.json" 2>/dev/null || echo '(none)')"
    ;;
  *)
    echo "usage: greenlight.sh {start|stop|restart|status}"; exit 1 ;;
esac
