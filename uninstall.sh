#!/bin/bash
set -euo pipefail
sudo systemctl disable --now pi-tableau-leaderboard.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/pi-tableau-leaderboard.service
sudo systemctl daemon-reload
rm -rf "$HOME/pi-tableau-leaderboard"
rm -f "$HOME/.config/autostart/pi-tableau-leaderboard.desktop"
echo "Application removed."
echo "Database remains at ~/.local/share/pi-tableau-leaderboard/"
