#!/usr/bin/env bash
# Greenlight control: start | stop | restart | status
# Cooperates with the LaunchAgent (com.liorbar.greenlight) when it's installed,
# and falls back to a plain background process when it isn't.
set -euo pipefail
DIR="$HOME/Documents/all_projects/greenlight"
PY="$DIR/.venv/bin/python"     # the menu-bar app needs PyObjC from the venv
APP="$DIR/greenlight_app.py"
LABEL="com.liorbar.greenlight"
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchd_loaded() { launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; }

case "${1:-start}" in
  start)
    if launchd_loaded; then
      launchctl kickstart "$DOMAIN/$LABEL" && echo "started (launchd)"
    elif [ -f "$PLIST" ]; then
      launchctl bootstrap "$DOMAIN" "$PLIST" && echo "loaded LaunchAgent (launchd)"
    elif pgrep -f greenlight_app.py >/dev/null; then
      echo "already running (pid $(pgrep -f greenlight_app.py))"
    else
      nohup "$PY" "$APP" >>"$DIR/app.log" 2>&1 &
      echo "started (pid $!)"
    fi
    ;;
  stop)
    if launchd_loaded; then
      launchctl bootout "$DOMAIN/$LABEL" && echo "stopped (launchd job booted out; returns at next login)"
    else
      pkill -f greenlight_app.py && echo "stopped" || echo "not running"
    fi
    rm -f "$DIR/app.pid"
    ;;
  restart)
    if launchd_loaded; then
      launchctl kickstart -k "$DOMAIN/$LABEL" && echo "restarted (launchd)"
    else
      pkill -f greenlight_app.py 2>/dev/null || true
      sleep 0.3
      nohup "$PY" "$APP" >>"$DIR/app.log" 2>&1 &
      echo "restarted (pid $!)"
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
    echo "state: $(cat "$DIR/state.json" 2>/dev/null || echo '(none)')"
    ;;
  *)
    echo "usage: greenlight.sh {start|stop|restart|status}"; exit 1 ;;
esac
