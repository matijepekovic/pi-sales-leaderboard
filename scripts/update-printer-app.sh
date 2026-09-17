#!/bin/bash
set -euo pipefail
if [[ $(id -un) != scoreboard || $EUID -eq 0 ]]; then
  echo 'Run as scoreboard, not root.' >&2
  exit 1
fi
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
[[ $(git branch --show-current) == main ]] || { echo 'Only the main branch is supported.' >&2; exit 1; }
[[ -z $(git status --porcelain --untracked-files=no) ]] || { echo 'Tracked changes found; refusing to overwrite them.' >&2; exit 1; }
exec 9>"$(git rev-parse --git-common-dir)/printer-app-update.lock"
flock 9
git pull --ff-only origin main
# The installer owns system dependencies as well as the private runtime.
# --unattended selects update semantics; an unchanged release is not restarted.
bash "$REPO/printer_app/install.sh" --unattended
