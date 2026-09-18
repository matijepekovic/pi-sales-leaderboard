"""Secure Gallery adapter stays deployment/runtime isolated from Gallery data."""
import json
from pathlib import Path

from printer_app import https_adapter


class DummySocket:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_https_config_is_gallery_only_and_keeps_guest_http_port():
    config = https_adapter._caddyfile(5055)
    assert 'https://:443' in config
    assert 'http://:80' not in config
    assert 'reverse_proxy 127.0.0.1:5055' in config
    assert 'handle /gallery*' in config
    assert 'handle /static/gallery*' in config
    assert 'respond "Not found" 404' in config


def test_server_certificate_has_current_ip_san_and_server_usage():
    config = https_adapter._openssl_config(['10.40.80.254'], ['stats-pi.local'])
    assert 'IP.1 = 10.40.80.254' in config
    assert 'DNS.1 = stats-pi.local' in config
    assert 'basicConstraints = critical,CA:FALSE' in config
    assert 'extendedKeyUsage = serverAuth' in config


def test_runtime_status_requires_exported_ca_and_listening_proxy(tmp_path, monkeypatch):
    root = tmp_path / 'gallery' / 'https'
    root.mkdir(parents=True)
    (root / 'status.json').write_text(json.dumps({
        'configured': True,
        'addresses': ['10.40.80.254'],
        'dns': ['stats-pi.local'],
        'fingerprint': 'abc',
    }))
    (root / 'root-ca.cer').write_bytes(b'certificate')
    adapter = https_adapter.GalleryHttpsAdapter(tmp_path)

    monkeypatch.setattr(
        https_adapter.socket, 'create_connection',
        lambda *args, **kwargs: DummySocket(),
    )
    status = adapter.status()
    assert status['configured'] is True
    assert status['addresses'] == ['10.40.80.254']
    assert adapter.root_certificate() == root / 'root-ca.cer'

    def unavailable(*args, **kwargs):
        raise OSError('not listening')

    monkeypatch.setattr(https_adapter.socket, 'create_connection', unavailable)
    assert adapter.status()['configured'] is False


def test_https_adapter_boundary_does_not_enter_gallery_business_modules():
    root = Path(__file__).resolve().parents[1]
    service = (root / 'gallery/service.py').read_text()
    repository = (root / 'gallery/repository.py').read_text()
    adapter = (root / 'https_adapter.py').read_text()
    assert 'caddy' not in service.lower()
    assert 'caddy' not in repository.lower()
    assert 'sqlite3' not in adapter
    assert 'flask' not in adapter
