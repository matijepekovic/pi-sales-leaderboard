#!/bin/bash
set -u

DATA_DIR="$HOME/.local/share/pi-tableau-leaderboard"
PROFILE_DIR="$DATA_DIR/chromium-kiosk-profile"
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
# kiosk flags.
pkill -f "chromium.*chromium-kiosk-profile" >/dev/null 2>&1 || true
sleep 1

rm -f \
  "$PROFILE_DIR/SingletonLock" \
  "$PROFILE_DIR/SingletonCookie" \
  "$PROFILE_DIR/SingletonSocket" \
  >/dev/null 2>&1 || true

exec "$BROWSER" \
  http://127.0.0.1:8765/ \
  --user-data-dir="$PROFILE_DIR" \
  --kiosk \
  --start-maximized \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  --no-default-browser-check \
  --disable-session-crashed-bubble \
  --enable-features=OverlayScrollbar
