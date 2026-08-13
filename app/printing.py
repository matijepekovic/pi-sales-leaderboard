"""Raw network printing, stdlib only.

Port 9100 (JetDirect / AppSocket): open a socket, write the bytes, close.
Most office printers accept plain text this way, and it needs nothing
installed on the Pi -- which matters, because the auto-updater replaces app
code and never runs apt.

If a printer ignores this, CUPS and `lp` are the next step.
"""
import concurrent.futures
import socket
import time

RAW_PORT = 9100
IPP_PORT = 631
PORTS = (RAW_PORT, IPP_PORT)

CONNECT_TIMEOUT = 0.35     # per host during a scan
SEND_TIMEOUT = 8.0         # a real print job deserves longer
SCAN_WORKERS = 64


def local_ip():
    """This Pi's address on the office network.

    Opening a UDP socket toward a public address makes the OS pick the
    outbound interface. Nothing is actually sent.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return ""
    finally:
        sock.close()


def _port_open(host, port, timeout=CONNECT_TIMEOUT):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def scan(subnet=None):
    """Look for printers on the Pi's own /24. Returns [{host, ports}]."""
    base = subnet or local_ip()
    if not base:
        return {"ok": False, "error": "Could not work out this Pi's network address.",
                "printers": [], "subnet": ""}

    prefix = base.rsplit(".", 1)[0]
    hosts = [f"{prefix}.{n}" for n in range(1, 255)]

    found = {}
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        jobs = {
            pool.submit(_port_open, host, port): (host, port)
            for host in hosts for port in PORTS
        }
        for job in concurrent.futures.as_completed(jobs):
            host, port = jobs[job]
            try:
                if job.result():
                    found.setdefault(host, []).append(port)
            except Exception:
                pass

    printers = [
        {"host": host, "ports": sorted(ports), "raw": RAW_PORT in ports}
        for host, ports in sorted(found.items(),
                                  key=lambda kv: [int(p) for p in kv[0].split(".")])
    ]
    return {
        "ok": True,
        "subnet": f"{prefix}.0/24",
        "self": base,
        "printers": printers,
        "seconds": round(time.time() - started, 1),
    }


def test_page(version=""):
    """A plain-text page. The trailing form feed is what ejects it."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "",
        "  SALES LEADERBOARD - PRINTER TEST",
        "  " + "-" * 38,
        "",
        f"  If you are reading this, the Pi can print.",
        "",
        f"  Printed at : {stamp}",
        f"  App version: {version or 'unknown'}",
        "",
    ]
    return ("\r\n".join(lines) + "\r\n\f").encode("ascii", errors="replace")


def print_raw(host, port, data, timeout=SEND_TIMEOUT):
    """Send bytes to a printer. Returns (ok, message)."""
    host = str(host or "").strip()
    if not host:
        return False, "Enter the printer's IP address first."
    try:
        port = int(port or RAW_PORT)
    except Exception:
        port = RAW_PORT

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(data)
            # Some printers only start the job once the sender goes away.
            sock.shutdown(socket.SHUT_WR)
        return True, (f"Sent {len(data)} bytes to {host}:{port}. "
                      "If nothing comes out, the printer accepted the job and "
                      "discarded it — that usually means it wants PostScript or "
                      "PCL rather than plain text, and CUPS is the next step.")
    except socket.timeout:
        return False, f"{host}:{port} did not answer in time."
    except ConnectionRefusedError:
        return False, (f"{host} refused port {port}. Raw printing is probably "
                       "switched off on it — try port 631, or install CUPS.")
    except OSError as exc:
        return False, f"Could not reach {host}:{port} — {exc}"


def print_test(host, port, version=""):
    return print_raw(host, port, test_page(version))
