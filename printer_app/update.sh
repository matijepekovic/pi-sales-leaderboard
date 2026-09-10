#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
if [[ $(id -un) != scoreboard ]]; then
  echo 'Run as scoreboard.' >&2
  exit 1
fi
if [[ $(git -C "$repo" branch --show-current) != main ]]; then
  echo 'Refusing to update a checkout that is not on main.' >&2
  exit 1
fi
git -C "$repo" diff --quiet
git -C "$repo" diff --cached --quiet
git -C "$repo" pull --ff-only origin main
# No host-application service is stopped or restarted here.
exec python3 "$repo/printer_app/deploy.py" deploy
