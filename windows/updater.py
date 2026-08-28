#!/usr/bin/env python3
"""Detached helper that installs a verified Stats update and relaunches Stats."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
DATA_ROOT = Path.home() / ".local" / "share" / "pi-tableau-leaderboard"
KIOSK_PID_FILE = DATA_ROOT / "windows-kiosk-browser.pid"


def _write_log(directory: Path, message: str) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "windows-updater.log").open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + message + "\n")
    except Exception:
        pass


def _write_status(directory: Path, state: str, version: str, message: str, exit_code: int | None = None) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "state": str(state or ""),
            "version": str(version or ""),
            "message": str(message or ""),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if exit_code is not None:
            payload["exit_code"] = int(exit_code)
        (directory / "last-update-status.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _run_taskkill(args: list[str]) -> None:
    try:
        subprocess.run(
            ["taskkill", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def _stop_stats_processes(log_dir: Path) -> None:
    """Stop the running UI/backend before Inno starts replacing files.

    The updater executable is a detached copy living in the update directory,
    so killing StatsLauncher/StatsServer cannot kill this helper. Doing this
    before starting Inno gives Windows/AV time to release the installed files.
    """
    try:
        raw = KIOSK_PID_FILE.read_text(encoding="ascii").strip()
        pid = int(raw)
        if pid > 0:
            _run_taskkill(["/PID", str(pid), "/T", "/F"])
    except Exception:
        pass
    try:
        KIOSK_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    _run_taskkill(["/IM", "StatsLauncher.exe", "/F"])
    _run_taskkill(["/IM", "StatsServer.exe", "/F"])
    time.sleep(1.5)

    # A second pass catches a backend that was still unwinding when the first
    # taskkill returned, and gives antivirus/indexing another moment to release
    # file handles before Inno touches the application directory.
    _run_taskkill(["/IM", "StatsLauncher.exe", "/F"])
    _run_taskkill(["/IM", "StatsServer.exe", "/F"])
    time.sleep(0.8)
    _write_log(log_dir, "Stats processes stopped before installer handoff")


def _relaunch(launcher: Path, log_dir: Path, context: str) -> bool:
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
        _write_log(log_dir, f"Stats relaunched after {context}")
        return True
    except Exception as exc:
        _write_log(log_dir, f"Could not relaunch Stats after {context}: {exc}")
        return False


def _run_installer(installer: Path, inno_log: Path) -> int:
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
    return int(completed.returncode)


def run_update(installer: Path, launcher: Path, version: str) -> int:
    log_dir = installer.parent
    if not installer.is_file():
        _write_log(log_dir, f"Installer missing: {installer}")
        return 2
    if not launcher.is_file():
        _write_log(log_dir, f"Launcher missing: {launcher}")
        return 3

    # Give the HTTP 202 response time to reach the Settings page, then shut down
    # Stats ourselves. This is intentionally earlier than Inno's file-copy stage.
    time.sleep(3)
    _write_log(log_dir, f"Installing Stats {version}: {installer.name}")
    _write_status(log_dir, "installing", version, "Installing verified update")
    inno_log = log_dir / "windows-installer-update.log"

    last_code = 4
    for attempt in (1, 2):
        _stop_stats_processes(log_dir)
        try:
            last_code = _run_installer(installer, inno_log)
        except Exception as exc:
            _write_log(log_dir, f"Installer launch failed on attempt {attempt}: {exc}")
            last_code = 4
        if last_code == 0:
            break
        _write_log(
            log_dir,
            f"Installer attempt {attempt} failed with exit code {last_code}; see {inno_log.name}",
        )
        if attempt == 1:
            time.sleep(2)

    if last_code != 0:
        message = f"Installer failed with exit code {last_code}"
        _write_status(log_dir, "failed", version, message, last_code)
        _relaunch(launcher, log_dir, "failed update")
        return last_code or 5

    # Wait for replacement to settle before starting the new launcher. If the
    # relaunch itself fails, keep the installer and log so the user can recover
    # by opening Stats manually without losing diagnostics.
    time.sleep(2)
    if not _relaunch(launcher, log_dir, "successful update"):
        _write_status(log_dir, "failed", version, "Update installed but Stats could not relaunch", 6)
        return 6

    _write_status(log_dir, "success", version, f"Stats {version} installed and relaunched", 0)
    _write_log(log_dir, f"Stats {version} installed and relaunched")
    try:
        installer.unlink(missing_ok=True)
    except Exception:
        pass
    return 0


def _self_test() -> int:
    # Keep this side-effect free: CI executes it from the freshly built helper.
    assert DATA_ROOT.name == "pi-tableau-leaderboard"
    assert KIOSK_PID_FILE.name == "windows-kiosk-browser.pid"
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer")
    parser.add_argument("--launcher")
    parser.add_argument("--version", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return _self_test()
    if not args.installer or not args.launcher:
        return 1
    return run_update(Path(args.installer), Path(args.launcher), str(args.version or ""))


if __name__ == "__main__":
    raise SystemExit(main())
