#!/bin/bash
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/pi-tableau-leaderboard"
VENV="$APP_DIR/.venv"
DATA_DIR="$HOME/.local/share/pi-tableau-leaderboard"
APPLIED_THEME_DIR="$DATA_DIR/applied-theme-assets"
USER_NAME="$(id -un)"

echo "Installing / updating Pi Tableau Leaderboard..."

sudo apt-get update
sudo apt-get install -y python3 python3-venv curl x11-xserver-utils wtype

if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
  sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser
fi

# Persistent data lives OUTSIDE the application folder.
# Updating/reinstalling the software never deletes settings, teams,
# assignments, cached data, or assets already applied to themes.
mkdir -p "$DATA_DIR"
mkdir -p "$APPLIED_THEME_DIR"
if [ -f "$DATA_DIR/leaderboard.db" ]; then
  cp "$DATA_DIR/leaderboard.db" "$DATA_DIR/leaderboard.db.backup-before-update"
  echo "Backed up existing settings/database."
fi

# Only the replaceable application directory is removed. Never rm/copy over
# DATA_DIR or APPLIED_THEME_DIR: those are appliance-owned persistent state.
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -R "$SRC_DIR/app" "$APP_DIR/app"
cp "$SRC_DIR/requirements.txt" "$APP_DIR/requirements.txt"
cp "$SRC_DIR/VERSION" "$APP_DIR/VERSION"
cp "$SRC_DIR/kiosk.sh" "$APP_DIR/kiosk.sh"
chmod +x "$APP_DIR/kiosk.sh"
chmod +x "$APP_DIR/app/kiosk_browser.sh" 2>/dev/null || true

python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"

SERVICE_TMP="$(mktemp)"
sed \
  -e "s|__USER__|$USER_NAME|g" \
  -e "s|__APPDIR__|$APP_DIR|g" \
  -e "s|__VENV__|$VENV|g" \
  "$SRC_DIR/pi-tableau-leaderboard.service" > "$SERVICE_TMP"
sudo cp "$SERVICE_TMP" /etc/systemd/system/pi-tableau-leaderboard.service
rm -f "$SERVICE_TMP"
sudo systemctl daemon-reload
sudo systemctl enable --now pi-tableau-leaderboard.service

mkdir -p "$HOME/.config/autostart"
sed "s|__KIOSK__|$APP_DIR/kiosk.sh|g" "$SRC_DIR/pi-tableau-leaderboard.desktop" \
  > "$HOME/.config/autostart/pi-tableau-leaderboard.desktop"

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')

echo
echo "============================================="
echo " Pi Tableau Leaderboard installed"
echo "============================================="
echo
echo "Your persistent appliance data remains in:"
echo "  $DATA_DIR"
echo "Applied theme assets remain in:"
echo "  $APPLIED_THEME_DIR"
echo
echo "TV display:"
echo "  http://${IP_ADDR:-PI-IP}:8765/"
echo
echo "Settings:"
echo "  http://${IP_ADDR:-PI-IP}:8765/settings"
echo
echo "Tableau is NOT connected yet."
echo
echo "Reboot when ready:"

# Raspberry Pi OS Bookworm+ uses labwc. Configure the supported graphical autostart.
mkdir -p "$HOME/.config/labwc"
LABWC_AUTOSTART="$HOME/.config/labwc/autostart"
BEGIN_MARKER="# >>> PI TABLEAU LEADERBOARD KIOSK >>>"
END_MARKER="# <<< PI TABLEAU LEADERBOARD KIOSK <<<"

python3 - "$LABWC_AUTOSTART" "$APP_DIR/kiosk.sh" <<'PY'
from pathlib import Path
import re, sys
path = Path(sys.argv[1])
kiosk = sys.argv[2]
begin = "# >>> PI TABLEAU LEADERBOARD KIOSK >>>"
end = "# <<< PI TABLEAU LEADERBOARD KIOSK <<<"
existing = path.read_text() if path.exists() else ""
existing = re.sub(re.escape(begin)+r".*?"+re.escape(end)+r"\n?", "", existing, flags=re.S).rstrip()
managed = f"{begin}\nbash {kiosk} &\n{end}\n"
path.write_text((existing + "\n\n" if existing else "") + managed)
PY

# Remove only our legacy generic autostart entry to avoid duplicate Chromium windows.
rm -f "$HOME/.config/autostart/pi-tableau-leaderboard.desktop" 2>/dev/null || true

echo "  sudo reboot"
