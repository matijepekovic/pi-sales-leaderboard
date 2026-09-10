#!/bin/bash
set -euo pipefail
umask 077
if [[ $(id -un) != scoreboard || $EUID -eq 0 ]]; then
  echo "Run this script as scoreboard, not root." >&2
  exit 1
fi
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
SUDO=(sudo)
ACTION=install
for argument in "$@"; do
  if [[ "$argument" == --unattended ]]; then
    SUDO+=(-n)
    ACTION=update
  fi
done
# Do not allow package-maintenance helpers to restart unrelated services.
"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get update
# CUPS client/development headers only. No driver, queue, filter or Account Track changes.
"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y --no-install-recommends --no-upgrade python3-venv python3-dev build-essential libcups2-dev cups-client \
  libreoffice-calc fonts-liberation fonts-dejavu-core
command -v libreoffice >/dev/null
command -v lp >/dev/null
lpstat -p konicaa >/dev/null || { echo 'Existing queue konicaa was not found. No printer settings were changed.' >&2; exit 1; }
python3 "$HERE/deploy.py" "$ACTION" "$@"
