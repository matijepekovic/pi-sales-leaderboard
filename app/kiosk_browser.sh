#!/bin/bash
set -u

DATA_DIR="$HOME/.local/share/pi-tableau-leaderboard"
PROFILE_DIR="$DATA_DIR/chromium-kiosk-profile"
FULLSCREEN_DISABLED="$DATA_DIR/fullscreen-disabled.flag"
mkdir -p "$PROFILE_DIR"

BROWSER=""
for candidate in chromium chromium-browser; do
  if command -v "$candidate" >/dev/null 2>&1; then
    BROWSER="$candidate"
    break
  fi
done

if [ -z "$BROWSER" ]; then
  echo "Chromium is not installed." >&2
  exit 127
fi

# Ensure an old kiosk-profile Chromium cannot absorb the new launch and ignore
# the selected fullscreen/windowed mode. Other browser profiles are untouched.
pkill -f "chromium.*chromium-kiosk-profile" >/dev/null 2>&1 || true
sleep 1

rm -f \
  "$PROFILE_DIR/SingletonLock" \
  "$PROFILE_DIR/SingletonCookie" \
  "$PROFILE_DIR/SingletonSocket" \
  >/dev/null 2>&1 || true

# Read the persistent pause on EVERY launch, including an old watchdog's
# crash/restart loop. The remote can change mode without a reboot or reinstall.
MODE_ARGS=(--kiosk)
if [ -f "$FULLSCREEN_DISABLED" ]; then
  MODE_ARGS=(--new-window)
fi

exec "$BROWSER" \
  http://127.0.0.1:8765/ \
  --user-data-dir="$PROFILE_DIR" \
  "${MODE_ARGS[@]}" \
  --start-maximized \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  --no-default-browser-check \
  --disable-session-crashed-bubble \
  --enable-features=OverlayScrollbar
