#!/usr/bin/env python3
"""Windows LAN-remote helpers for Stats.

The phone remote needs the packaged backend reachable on the current private
network. The launcher uses this module to request one Windows Firewall rule for
StatsServer.exe. The rule is program-scoped, inbound TCP 8765, private profile.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
RULE_NAME = "Stats Phone Remote"
PORT = 8765


def firewall_rule_args(server: Path) -> list[str]:
    return [
        "advfirewall", "firewall", "add", "rule",
        f"name={RULE_NAME}",
        "dir=in",
        "action=allow",
        "protocol=TCP",
        f"localport={PORT}",
        f"program={server}",
        "profile=private",
        "enable=yes",
    ]


def firewall_rule_exists() -> bool:
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE_NAME}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=6,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False


def ensure_firewall_rule(server: Path) -> bool:
    """Request elevation once to allow the phone remote on private networks."""
    if os.name != "nt" or not server.is_file():
        return False
    if firewall_rule_exists():
        return True

    params = subprocess.list2cmdline(firewall_rule_args(server))
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "netsh.exe",
            params,
            None,
            0,
        )
        # ShellExecute returns >32 when the elevated process was launched.
        return int(result) > 32
    except Exception:
        return False
