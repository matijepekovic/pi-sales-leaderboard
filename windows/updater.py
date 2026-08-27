#!/usr/bin/env python3
"""Detached helper that installs a verified Stats update and relaunches Stats."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _write_log(directory: Path, message: str) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "windows-updater.log").open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + message + "\n")
    except Exception:
        pass


def run_update(installer: Path, launcher: Path, version: str) -> int:
    log_dir = installer.parent
    if not installer.is_file():
        _write_log(log_dir, f"Installer missing: {installer}")
        return 2
    if not launcher.is_file():
        _write_log(log_dir, f"Launcher missing: {launcher}")
        return 3

    # Give the API response time to reach the browser before Inno Setup stops
    # the Stats processes in PrepareToInstall.
    time.sleep(3)
    _write_log(log_dir, f"Installing Stats {version}: {installer.name}")
    inno_log = log_dir / "windows-installer-update.log"

    try:
        completed = subprocess.run(
            [
                str(installer),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
                f"/LOG={inno_log}",
            ],
            cwd=str(installer.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=600,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as exc:
        _write_log(log_dir, f"Installer launch failed: {exc}")
        return 4

    if completed.returncode != 0:
        _write_log(
            log_dir,
            f"Installer failed with exit code {completed.returncode}; see {inno_log.name}",
        )
        return completed.returncode or 5

    # The installer keeps the same application directory and identity. Wait a
    # moment for file replacement to settle, then start the new launcher.
    time.sleep(2)
    try:
        subprocess.Popen(
            [str(launcher)],
            cwd=str(launcher.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        )
    except Exception as exc:
        _write_log(log_dir, f"Stats updated but relaunch failed: {exc}")
        return 6

    _write_log(log_dir, f"Stats {version} installed and relaunched")
    try:
        installer.unlink(missing_ok=True)
    except Exception:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer")
    parser.add_argument("--launcher")
    parser.add_argument("--version", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return 0
    if not args.installer or not args.launcher:
        return 1
    return run_update(Path(args.installer), Path(args.launcher), str(args.version or ""))


if __name__ == "__main__":
    raise SystemExit(main())
