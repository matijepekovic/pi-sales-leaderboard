"""Standalone printer-app update request and verified installation.

The web endpoint only writes a fixed update request. A separately installed
systemd path/service runs the network, verification, and deployment workflow.
This module never imports, replaces, or restarts Stats.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile

from .deploy import fingerprint

REPOSITORY = "matijepekovic/pi-sales-leaderboard"
MAX_ARCHIVE = 128 * 1024 * 1024
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


def _api_json(path: str) -> dict:
    url = "https://api.github.com/repos/" + REPOSITORY + path
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "printer-app-update",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read(2 * 1024 * 1024))


def _remote_bundle() -> dict:
    revision = _api_json("/git/ref/heads/main")["object"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid upstream commit")
    tree = _api_json("/git/trees/" + revision)
    entries = [item for item in tree.get("tree", ())
               if item.get("path") == "printer_app" and item.get("type") == "tree"]
    if len(entries) != 1 or not re.fullmatch(r"[0-9a-f]{40}", entries[0].get("sha", "")):
        raise ValueError("No verified printer source in upstream commit")
    return {"revision": revision, "tree": entries[0]["sha"]}


def _git_tree(directory: Path) -> str:
    """Use Git's exact tree/hash format, including executable file modes."""
    entries = []
    for path in directory.iterdir():
        if path.is_symlink():
            raise ValueError("Symlink not allowed in printer update")
        name = path.name.encode("utf-8")
        if path.is_dir():
            mode, digest, order = b"40000", _git_tree(path), name + b"/"
        elif path.is_file():
            data = path.read_bytes()
            mode = b"100755" if path.stat().st_mode & 0o111 else b"100644"
            digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            order = name
        else:
            raise ValueError("Unsupported printer update file")
        entries.append((order, mode + b" " + name + b"\0" + bytes.fromhex(digest)))
    payload = b"".join(record for _, record in sorted(entries))
    return hashlib.sha1(b"tree " + str(len(payload)).encode() + b"\0" + payload).hexdigest()


def _download(bundle: dict, directory: Path) -> Path:
    url = ("https://api.github.com/repos/" + REPOSITORY + "/zipball/"
           + bundle["revision"])
    request = urllib.request.Request(url, headers={"User-Agent": "printer-app-update"})
    archive = directory / "upstream.zip"
    with urllib.request.urlopen(request, timeout=60) as response, archive.open("xb") as output:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ARCHIVE:
                raise ValueError("Printer source archive exceeds the size limit")
            output.write(chunk)

    package = directory / "printer_app"
    package.mkdir(mode=0o700)
    total = 0
    selected = set()
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            parts = PurePosixPath(info.filename).parts
            if (PurePosixPath(info.filename).is_absolute() or ".." in parts
                    or "\\" in info.filename):
                raise ValueError("Unsafe path in printer source archive")
            if len(parts) < 2 or parts[1] != "printer_app":
                continue
            if info.is_dir():
                continue
            relative = Path(*parts[2:])
            mode = info.external_attr >> 16
            if (not relative.parts or relative in selected
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise ValueError("Unsupported or duplicate printer source file")
            selected.add(relative)
            total += info.file_size
            if total > MAX_ARCHIVE:
                raise ValueError("Extracted printer source exceeds the size limit")
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with source.open(info) as incoming, target.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            target.chmod(0o755 if mode & 0o111 else 0o644)
    if _git_tree(package) != bundle["tree"]:
        raise ValueError("Printer files did not match the upstream Git tree")
    return package


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
            bundle = _remote_bundle()
            record("INSTALLING", "Downloading and verifying printer files…", **bundle)
            with tempfile.TemporaryDirectory(prefix="printer-update-", dir=directory) as temp:
                package = _download(bundle, Path(temp))
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
