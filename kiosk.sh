#!/bin/bash
set -u

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$HOME/.local/share/pi-tableau-leaderboard"
RESTART_REQUEST="$DATA_DIR/restart-kiosk.request"
LOCK_FILE="$DATA_DIR/kiosk-watchdog.lock"

mkdir -p "$DATA_DIR"

# Prevent duplicate kiosk watchdogs if the desktop session fires autostart twice.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || exit 0
fi

# Keep the TV awake.
xset s off >/dev/null 2>&1 || true
xset -dpms >/dev/null 2>&1 || true
xset s noblank >/dev/null 2>&1 || true

# Wait for the leaderboard server before opening Chromium.
while true; do
  if curl -fsS http://127.0.0.1:8765/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

rm -f "$RESTART_REQUEST" >/dev/null 2>&1 || true

while true; do
  # The launcher lives inside app/, so normal phone software updates replace it.
  bash "$HERE/app/kiosk_browser.sh" &
  BROWSER_PID=$!

  # While Chromium is running, watch for a remote fullscreen/relaunch request.
  while kill -0 "$BROWSER_PID" >/dev/null 2>&1; do
    if [ -f "$RESTART_REQUEST" ]; then
      rm -f "$RESTART_REQUEST" >/dev/null 2>&1 || true

      # First stop the dedicated Chromium process cleanly.
      kill "$BROWSER_PID" >/dev/null 2>&1 || true

      # Give Chromium a moment, then ensure the dedicated kiosk profile process
      # is gone before relaunching.
      sleep 1
      pkill -f "chromium.*chromium-kiosk-profile" >/dev/null 2>&1 || true
      break
    fi
    sleep 1
  done

  wait "$BROWSER_PID" >/dev/null 2>&1 || true

  # If Chromium crashed, was Alt+F4'd, or was deliberately restarted, it comes
  # straight back in true kiosk fullscreen.
  sleep 1

  # If the backend was temporarily restarting, wait for it again.
  until curl -fsS http://127.0.0.1:8765/health >/dev/null 2>&1; do
    sleep 1
  done
done
