"""v109 TV remote QR overlay support.

Generate a small, local QR asset that points phones at this Pi's Settings page.
The kiosk itself opens the board through 127.0.0.1, so the QR must use the
Pi's LAN address instead of the browser's current host.
"""
from io import BytesIO
from pathlib import Path
import socket
import subprocess

import qrcode
import qrcode.image.svg

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


def generate():
    """Write the current remote QR atomically and return the encoded URL."""
    url = remote_url()
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buffer = BytesIO()
    image.save(buffer)

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".svg.tmp")
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(OUTPUT)
    return url
