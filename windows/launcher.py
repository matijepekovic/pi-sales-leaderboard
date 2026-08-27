#!/usr/bin/env python3
"""Windows launcher for the packaged Stats server and fullscreen browser."""
from __future__ import annotations

import atexit
import ctypes
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:8765/"
HEALTH_URL = URL + "health"
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
KIOSK_BROWSER_PID_NAME = "windows-kiosk-browser.pid"
_MUTEX_HANDLE = None
_SERVER = None
_BROWSER = None


def data_dir() -> Path:
    path = Path.home() / ".local" / "share" / "pi-tableau-leaderboard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def kiosk_browser_pid_file() -> Path:
    return data_dir() / KIOSK_BROWSER_PID_NAME


def write_kiosk_browser_pid(process) -> None:
    try:
        kiosk_browser_pid_file().write_text(str(int(process.pid)), encoding="ascii")
    except Exception as exc:
        log(f"Could not record kiosk browser PID: {exc}")


def clear_kiosk_browser_pid() -> None:
    try:
        kiosk_browser_pid_file().unlink(missing_ok=True)
    except Exception:
        pass


def log(message: str) -> None:
    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "windows-launcher.log").open("a", encoding="utf-8") as handle:
        handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + message + "\n")


def acquire_single_instance() -> bool:
    global _MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\StatsLauncher")
    if not handle:
        return False
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _MUTEX_HANDLE = handle
    return True


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def server_exe() -> Path:
    return app_dir() / "server" / "StatsServer.exe"


def health_ok(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def start_server():
    exe = server_exe()
    if not exe.is_file():
        raise FileNotFoundError(f"Missing backend: {exe}")
    log(f"Starting backend: {exe}")
    return subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def wait_for_server(seconds: int = 60) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _SERVER is not None and _SERVER.poll() is not None:
            return False
        if health_ok():
            return True
        time.sleep(1)
    return False


def browser_candidates() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(kind: str, value: str | None) -> None:
        if not value:
            return
        path = str(Path(value))
        key = path.lower()
        if key not in seen and Path(path).is_file():
            seen.add(key)
            found.append((kind, path))

    add("edge", shutil.which("msedge.exe") or shutil.which("msedge"))
    add("chrome", shutil.which("chrome.exe") or shutil.which("chrome"))

    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if not base:
            continue
        add("edge", str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
        add("chrome", str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))

    return found


def launch_browser():
    profile = data_dir() / "windows-kiosk-browser"
    profile.mkdir(parents=True, exist_ok=True)

    for kind, exe in browser_candidates():
        args = [
            exe,
            URL,
            f"--user-data-dir={profile}",
            "--kiosk",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--disable-infobars",
        ]
        if kind == "edge":
            args.append("--edge-kiosk-type=fullscreen")
        try:
            log(f"Launching {kind} fullscreen: {exe}")
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            write_kiosk_browser_pid(process)
            return process
        except Exception as exc:
            log(f"Could not launch {kind}: {exc}")

    clear_kiosk_browser_pid()
    log("No supported Edge/Chrome browser was found")
    return None


def kill_process_tree(process) -> None:
    if process is None:
        return
    try:
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                creationflags=CREATE_NO_WINDOW,
            )
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def restart_request_stamp(path: Path):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def cleanup() -> None:
    global _MUTEX_HANDLE
    kill_process_tree(_BROWSER)
    clear_kiosk_browser_pid()
    kill_process_tree(_SERVER)
    if _MUTEX_HANDLE:
        try:
            ctypes.windll.kernel32.CloseHandle(_MUTEX_HANDLE)
        except Exception:
            pass
        _MUTEX_HANDLE = None


def supervise() -> int:
    """Run Stats until the user closes the fullscreen browser."""
    global _SERVER, _BROWSER

    request_file = data_dir() / "restart-kiosk.request"
    try:
        request_file.unlink(missing_ok=True)
    except Exception:
        pass
    last_request = restart_request_stamp(request_file)

    log("Stats Windows launcher started")

    while True:
        if _SERVER is None or _SERVER.poll() is not None:
            if _SERVER is not None:
                log(f"Backend exited with code {_SERVER.returncode}; restarting")
            _SERVER = start_server()
            if not wait_for_server():
                log("Backend failed to become healthy; retrying")
                kill_process_tree(_SERVER)
                _SERVER = None
                time.sleep(3)
                continue
            log("Backend is healthy")

        current_request = restart_request_stamp(request_file)
        requested = current_request is not None and current_request != last_request
        if requested:
            log("Fullscreen relaunch requested by the app")
            last_request = current_request
            kill_process_tree(_BROWSER)
            clear_kiosk_browser_pid()
            _BROWSER = None
            try:
                request_file.unlink(missing_ok=True)
            except Exception:
                pass
            if health_ok():
                _BROWSER = launch_browser()
                if _BROWSER is None:
                    return 1
            continue

        if _BROWSER is None and health_ok():
            _BROWSER = launch_browser()
            if _BROWSER is None:
                return 1
        elif _BROWSER is not None and _BROWSER.poll() is not None:
            clear_kiosk_browser_pid()
            log("Fullscreen browser was closed; shutting down Stats")
            return 0

        time.sleep(2)


def main() -> int:
    if os.name != "nt":
        return 1
    if not acquire_single_instance():
        return 0
    atexit.register(cleanup)
    return supervise()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as exc:
        try:
            log(f"Launcher fatal error: {exc}")
        finally:
            raise
