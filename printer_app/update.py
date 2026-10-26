"""Standalone printer-app update request and verified installation.

The web endpoint only writes a fixed update request. A separately installed
systemd path/service runs the network, verification, and deployment workflow.
This module never imports, replaces, or restarts Stats.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

from .deploy import fingerprint

REPOSITORY = "matijepekovic/pi-sales-leaderboard"
MAX_SOURCE = 128 * 1024 * 1024
ACTIVE_STATES = frozenset(("QUEUED", "INSTALLING"))


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name("." + path.name + "-" + uuid.uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class PrinterUpdateService:
    """Durable, fixed-source update contract between the web and systemd."""

    def __init__(self, data_dir: Path):
        self.directory = Path(data_dir) / "updates"
        # The systemd PathExists watcher needs a stable parent directory.
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def status(self) -> dict:
        saved = _read_json(self.directory / "status.json")
        state = saved.get("state", "NOT CHECKED")
        message = saved.get("message", "Use Update Printer to check for the latest printer release.")
        if state not in ("NOT CHECKED", "QUEUED", "INSTALLING", "READY", "UP TO DATE", "ERROR"):
            state, message = "ERROR", "The printer updater returned an invalid status."
        updated = saved.get("updated", 0)
        if state in ACTIVE_STATES and (not isinstance(updated, (int, float)) or time.time() - updated > 1800):
            state, message = "ERROR", "Printer update stalled. Check the printer update service log."
        return {"state": state, "message": message}

    def request(self) -> dict:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / "request.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = self.status()
            if current["state"] in ACTIVE_STATES:
                return current
            request_id = uuid.uuid4().hex
            _write_json(self.directory / "status.json", {
                "state": "QUEUED", "message": "Printer update queued. Stats is unchanged.",
                "updated": time.time(), "request_id": request_id,
            })
            # Only this fixed request is accepted; there is no user-supplied
            # repository, branch, path, shell command, or update script.
            _write_json(self.directory / "request.json", {"request_id": request_id})
            return self.status()


def _checkout(destination: Path) -> tuple[Path, dict]:
    """Obtain one verified Git checkout of the fixed public main branch.

    This uses Git's native object integrity checks rather than duplicating the
    existing legacy Stats-to-printer bootstrap ZIP verifier. Only printer_app/
    is passed to the installer; no checked-out Stats code is ever executed.
    """
    repository = destination / "repository"
    source = "https://github.com/" + REPOSITORY + ".git"
    command = [
        "git", "-c", "core.autocrlf=false", "-c", "core.hooksPath=/dev/null",
        "clone", "--quiet", "--depth", "1", "--single-branch",
        "--no-tags", "--branch", "main", "--", source, str(repository),
    ]
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0",
                       GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
    subprocess.run(command, env=environment, stdin=subprocess.DEVNULL,
                   check=True, timeout=180)

    def revision(ref: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--verify", ref],
            env=environment, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, check=True, timeout=15,
        )
        value = result.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("Invalid printer source commit or tree")
        return value

    bundle = {"revision": revision("HEAD"), "tree": revision("HEAD:printer_app")}
    package = repository / "printer_app"
    if not package.is_dir():
        raise ValueError("Printer source not found in verified checkout")
    total = 0
    for entry in package.rglob("*"):
        if entry.is_symlink():
            raise ValueError("Links are not allowed in printer source")
        if entry.is_file():
            total += entry.stat().st_size
            if total > MAX_SOURCE:
                raise ValueError("Printer source exceeds the update size limit")
    return package, bundle


def run_update(data_dir: Path) -> int:
    """Run only from the standalone systemd one-shot service, not Flask."""
    service = PrinterUpdateService(data_dir)
    directory = service.directory
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "installer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        request = _read_json(directory / "request.json")
        receipt = _read_json(directory / "status.json")
        directory.joinpath("request.json").unlink(missing_ok=True)
        if (not re.fullmatch(r"[0-9a-f]{32}", str(request.get("request_id", "")))
                or request["request_id"] != receipt.get("request_id")):
            return 0

        def record(state: str, message: str, **details) -> None:
            _write_json(directory / "status.json", dict(
                state=state, message=message, updated=time.time(),
                request_id=request["request_id"], **details,
            ))

        try:
            record("INSTALLING", "Checking the latest published printer release…")
            with tempfile.TemporaryDirectory(prefix="printer-update-", dir=directory) as temp:
                record("INSTALLING", "Fetching the verified printer source…")
                package, bundle = _checkout(Path(temp))
                if fingerprint(package) == fingerprint(Path(__file__).resolve().parent):
                    record("UP TO DATE", "Printer is already up to date; Stats was not changed.", **bundle)
                    return 0
                record("INSTALLING", "Installing printer update; Stats is not being updated…", **bundle)
                result = subprocess.run(
                    ["bash", str(package / "install.sh"), "--unattended"],
                    stdin=subprocess.DEVNULL, check=False, timeout=1500,
                )
                if result.returncode:
                    raise RuntimeError("Printer installation did not complete; previous release restored when possible.")
            record("READY", "Printer updated successfully. Stats was not changed.", **bundle)
            return 0
        except Exception as exc:
            # Never expose exception details: low-level libraries may include secrets.
            message = ("Printer installation failed. Previous release should remain available."
                       if isinstance(exc, RuntimeError) else
                       "Printer update failed (" + type(exc).__name__ + "). Existing installation preserved.")
            record("ERROR", message + " Check printer-app-update.service logs.")
            return 1


def main() -> None:
    if sys.argv[1:] != ["run"]:
        raise SystemExit("Expected the fixed printer update worker action")
    from .config import Config
    if os.geteuid() == 0:
        raise SystemExit("Printer updater must run as scoreboard, not root")
    raise SystemExit(run_update(Config.from_env().data_dir))


if __name__ == "__main__":
    main()
