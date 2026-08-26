"""TV remote QR overlay support.

Generate a small local QR asset that points phones at this Pi's Settings page.
The kiosk itself opens the board through 127.0.0.1, so the QR must use the
Pi's LAN address instead of the browser's current host.

v113 keeps one permanent appearance: black background, white modules, and
slightly rounded module/outer corners. There is no style selector.
"""
from pathlib import Path
import socket
import subprocess

import qrcode

PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "static"
OUTPUT = STATIC_DIR / "remote-qr-v109.svg"


def _lan_ipv4():
    """Return the address used by the Pi's default LAN route when possible."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect chooses a route without needing to send application data.
        sock.connect(("8.8.8.8", 80))
        address = str(sock.getsockname()[0] or "").strip()
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    finally:
        sock.close()

    try:
        output = subprocess.check_output(
            ["hostname", "-I"], text=True, timeout=2
        )
        for token in output.split():
            token = token.strip()
            if token.count(".") == 3 and not token.startswith("127."):
                return token
    except Exception:
        pass

    return ""


def remote_url():
    address = _lan_ipv4()
    if address:
        return f"http://{address}:{PORT}/settings"

    hostname = str(socket.gethostname() or "raspberrypi").strip() or "raspberrypi"
    return f"http://{hostname}.local:{PORT}/settings"


def _styled_svg(url):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    size = len(matrix)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        'shape-rendering="geometricPrecision">',
        f'<rect width="{size}" height="{size}" rx="1.2" ry="1.2" fill="#000"/>',
    ]
    # No gaps between modules: the QR stays structurally conservative for
    # scanning, while rx/ry softens exposed corners and gives the requested look.
    for y, row in enumerate(matrix):
        for x, enabled in enumerate(row):
            if enabled:
                parts.append(
                    f'<rect x="{x}" y="{y}" width="1" height="1" '
                    'rx=".18" ry=".18" fill="#fff"/>'
                )
    parts.append('</svg>')
    return ''.join(parts).encode('utf-8')


def generate():
    """Write the current remote QR atomically and return the encoded URL."""
    url = remote_url()
    svg = _styled_svg(url)

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".svg.tmp")
    temporary.write_bytes(svg)
    temporary.replace(OUTPUT)
    return url
