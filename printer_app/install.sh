#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -un) != scoreboard ]]; then
  echo 'Run this installer as scoreboard, not root. It uses sudo only for system setup.' >&2
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev build-essential libcups2-dev cups-client libreoffice-calc fonts-dejavu-core
command -v libreoffice >/dev/null
command -v lp >/dev/null
lpstat -p konicaa >/dev/null || { echo 'Existing queue konicaa is missing. No driver or queue changes were made.' >&2; exit 1; }
exec python3 "$(dirname "$(readlink -f "$0")")/deploy.py" install
