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
# Optional gallery tools use the system Python, never the printer venv.
# A gallery package failure must not prevent the existing printer update.
if ! "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y --no-install-recommends --no-upgrade \
  python3-opencv python3-pil poppler-utils tesseract-ocr tesseract-ocr-eng; then
  echo 'Gallery tools could not be installed; printing will still update. Retry Update before enabling gallery imports.' >&2
fi
# Full-access phone Offline uses a local HTTPS adapter. Failure is optional:
# normal printing, HTTP Gallery and temporary guest QR access still work.
if ! "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y --no-install-recommends --no-upgrade \
  caddy openssl; then
  echo 'Secure Gallery tools could not be installed; full-device offline relaunch will remain unavailable.' >&2
fi
command -v libreoffice >/dev/null
command -v lp >/dev/null
lpstat -p konicaa >/dev/null || { echo 'Existing queue konicaa was not found. No printer settings were changed.' >&2; exit 1; }
python3 "$HERE/deploy.py" "$ACTION" "$@"
