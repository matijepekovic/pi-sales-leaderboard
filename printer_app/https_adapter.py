"""Local HTTPS adapter for trusted full-access Gallery devices.

Deployment owns Caddy/certificates. Runtime consumers receive only normalized
availability/certificate metadata; Gallery code never depends on Caddy paths.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time


SYSTEM_DIR = Path('/etc/printer-app-https')
ROOT_KEY = SYSTEM_DIR / 'root-ca.key'
ROOT_CERT = SYSTEM_DIR / 'root-ca.crt'
SERVER_KEY = SYSTEM_DIR / 'server.key'
SERVER_CERT = SYSTEM_DIR / 'server.crt'
CADDYFILE = SYSTEM_DIR / 'Caddyfile'


def _run(command, *, unattended=False, **kwargs):
    if command[0] == 'sudo' and unattended:
        command = ['sudo', '-n', *command[1:]]
        kwargs.setdefault('stdin', subprocess.DEVNULL)
    return subprocess.run(command, check=True, **kwargs)


def _local_hosts():
    addresses = []
    try:
        result = subprocess.run(
            ['hostname', '-I'], capture_output=True, text=True, timeout=5, check=False
        )
        for value in result.stdout.split():
            try:
                parsed = ipaddress.ip_address(value.split('%', 1)[0])
            except ValueError:
                continue
            if parsed.version == 4 and not parsed.is_loopback and not parsed.is_link_local:
                addresses.append(str(parsed))
    except (OSError, subprocess.SubprocessError):
        pass
    hostname = socket.gethostname().strip()
    dns = [hostname] if hostname and all(c.isalnum() or c in '.-' for c in hostname) else []
    if hostname and '.' not in hostname:
        dns.append(hostname + '.local')
    return sorted(set(addresses)), sorted(set(dns))


def _openssl_config(ips, dns):
    lines = [
        '[req]',
        'prompt = no',
        'distinguished_name = dn',
        'req_extensions = req_ext',
        '[dn]',
        'CN = Stats Gallery',
        '[req_ext]',
        'subjectAltName = @alt_names',
        '[alt_names]',
    ]
    for index, value in enumerate(ips, 1):
        lines.append(f'IP.{index} = {value}')
    for index, value in enumerate(dns, 1):
        lines.append(f'DNS.{index} = {value}')
    return '\n'.join(lines) + '\n'


def _caddyfile(port):
    backend = f'127.0.0.1:{int(port)}'
    return f"""{{
    admin off
    auto_https off
}}

http://:80 {{
    handle /gallery* {{
        reverse_proxy {backend}
    }}
    handle /static/gallery* {{
        reverse_proxy {backend}
    }}
    handle {{
        respond "Not found" 404
    }}
}}

https://:443 {{
    tls {SERVER_CERT} {SERVER_KEY}
    handle /gallery* {{
        reverse_proxy {backend}
    }}
    handle /static/gallery* {{
        reverse_proxy {backend}
    }}
    handle {{
        respond "Not found" 404
    }}
}}
"""


def _status_dir(data_dir):
    return Path(data_dir) / 'gallery' / 'https'


def _write_status(data_dir, value):
    root = _status_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / 'status.json'
    temporary = target.with_name('.status-' + str(os.getpid()) + '.json')
    temporary.write_text(json.dumps(value, sort_keys=True), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(target)


def prepare(data_dir, port, *, unattended=False):
    """Prepare a stable local CA + current-host server certificate and Caddy config."""
    data_dir = Path(data_dir).resolve()
    ips, dns = _local_hosts()
    if not ips:
        raise RuntimeError('No LAN IPv4 address is available for secure Gallery setup.')
    if shutil.which('openssl') is None or shutil.which('caddy') is None:
        raise RuntimeError('Caddy and OpenSSL are required for secure Gallery setup.')

    with tempfile.TemporaryDirectory(prefix='printer-gallery-https-') as temporary:
        work = Path(temporary)
        os.chmod(work, 0o700)
        root_key = work / 'root-ca.key'
        root_cert = work / 'root-ca.crt'
        server_key = work / 'server.key'
        server_csr = work / 'server.csr'
        server_cert = work / 'server.crt'
        openssl_cfg = work / 'server.cnf'
        openssl_cfg.write_text(_openssl_config(ips, dns), encoding='utf-8')

        _run(['sudo', 'install', '-d', '-m', '0750', '-o', 'root', '-g', 'caddy',
              str(SYSTEM_DIR)], unattended=unattended)

        root_exists = subprocess.run(
            ['sudo', *(['-n'] if unattended else []), 'test', '-s', str(ROOT_KEY)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        ).returncode == 0

        if not root_exists:
            _run([
                'openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-sha256', '-nodes',
                '-days', '3650', '-subj', '/CN=Stats Gallery Local CA',
                '-keyout', str(root_key), '-out', str(root_cert),
            ])
            _run(['sudo', 'install', '-m', '0600', '-o', 'root', '-g', 'root',
                  str(root_key), str(ROOT_KEY)], unattended=unattended)
            _run(['sudo', 'install', '-m', '0644', '-o', 'root', '-g', 'root',
                  str(root_cert), str(ROOT_CERT)], unattended=unattended)

        _run([
            'openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', str(server_key), '-out', str(server_csr),
            '-config', str(openssl_cfg),
        ])
        sign = [
            'sudo', 'openssl', 'x509', '-req', '-sha256', '-days', '365',
            '-in', str(server_csr), '-CA', str(ROOT_CERT), '-CAkey', str(ROOT_KEY),
            '-out', str(server_cert), '-extfile', str(openssl_cfg), '-extensions', 'req_ext',
        ]
        serial = SYSTEM_DIR / 'root-ca.srl'
        exists = subprocess.run(
            ['sudo', *(['-n'] if unattended else []), 'test', '-f', str(serial)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        ).returncode == 0
        sign.extend(['-CAserial', str(serial)] if exists else ['-CAcreateserial'])
        _run(sign, unattended=unattended)

        _run(['sudo', 'install', '-m', '0640', '-o', 'root', '-g', 'caddy',
              str(server_key), str(SERVER_KEY)], unattended=unattended)
        _run(['sudo', 'install', '-m', '0644', '-o', 'root', '-g', 'caddy',
              str(server_cert), str(SERVER_CERT)], unattended=unattended)

        local_caddy = work / 'Caddyfile'
        local_caddy.write_text(_caddyfile(port), encoding='utf-8')
        _run(['sudo', 'install', '-m', '0644', '-o', 'root', '-g', 'root',
              str(local_caddy), str(CADDYFILE)], unattended=unattended)

        root_bytes = subprocess.run(
            ['sudo', *(['-n'] if unattended else []), 'cat', str(ROOT_CERT)],
            capture_output=True, check=True
        ).stdout

    public_root = _status_dir(data_dir)
    public_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    cert_target = public_root / 'root-ca.crt'
    cert_target.write_bytes(root_bytes)
    cert_target.chmod(0o644)
    fingerprint = hashlib.sha256(root_bytes).hexdigest()
    _write_status(data_dir, dict(
        configured=True,
        addresses=ips,
        dns=dns,
        fingerprint=fingerprint,
        updated=time.time(),
    ))
    # The distro caddy.service would otherwise compete for :80/:443. Stats owns
    # a separate, hardened printer-app-https.service instead.
    subprocess.run(
        ['sudo', *(['-n'] if unattended else []), 'systemctl', 'disable', '--now', 'caddy.service'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )


class GalleryHttpsAdapter:
    """Runtime view of secure full-device setup; no web/framework concerns."""

    def __init__(self, data_dir):
        self.root = _status_dir(data_dir)

    def status(self):
        try:
            value = json.loads((self.root / 'status.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return dict(configured=False, addresses=[], dns=[])
        if not isinstance(value, dict):
            return dict(configured=False, addresses=[], dns=[])
        return dict(
            configured=bool(value.get('configured')),
            addresses=[str(v) for v in value.get('addresses', [])],
            dns=[str(v) for v in value.get('dns', [])],
            fingerprint=str(value.get('fingerprint', '')),
        )

    def root_certificate(self):
        path = self.root / 'root-ca.crt'
        return path if path.is_file() else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare'])
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--unattended', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'prepare':
        prepare(args.data_dir, args.port, unattended=args.unattended)


if __name__ == '__main__':
    main()
