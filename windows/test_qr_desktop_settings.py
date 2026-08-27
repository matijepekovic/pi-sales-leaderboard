#!/usr/bin/env python3
"""Regression check for the desktop QR settings shortcut."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "app" / "static" / "remote-qr-overlay-v110.js"

text = SCRIPT.read_text(encoding="utf-8")
required = (
    "pointer-events:auto",
    "addEventListener('dblclick'",
    "window.location.assign('/settings')",
    "Double-click to open Settings",
)
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit("QR desktop settings shortcut is incomplete: " + ", ".join(missing))

print("QR double-click settings shortcut verified")
