#!/bin/bash
set -euo pipefail
case "${1:-}" in web) MODULE=app ;; worker) MODULE=worker ;; *) exit 2 ;; esac
# Resolve the release before starting Python. A repository pull or symlink switch
# cannot replace modules/templates/venv underneath a running process.
HERE="$(dirname "$(readlink -f "$0")")"
RELEASE="$(dirname "$HERE")"
cd "$RELEASE"
exec "$RELEASE/.venv/bin/python" -m "printer_app.$MODULE"
