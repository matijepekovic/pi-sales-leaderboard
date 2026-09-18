"""Secure Gallery adapter stays deployment/runtime isolated from Gallery data."""
import json
from pathlib import Path

from printer_app import https_adapter
from printer_app.app import create_app
from printer_app.config import Config


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


def test_secure_offline_setup_and_ca_are_full_gallery_only(tmp_path):
    data = tmp_path / 'data'
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\nEMAIL_MAILBOX=INBOX\n')
    app = create_app(Config(
        data_dir=data,
        env_file=env,
        secret_key='s' * 64,
        email_enabled=False,
    ))
    app.testing = True

    cert = data / 'gallery' / 'https' / 'root-ca.cer'
    cert.parent.mkdir(parents=True, exist_ok=True)
    cert.write_bytes(b'fixture-ca')

    access = app.extensions['gallery_access']

    full = app.test_client()
    full_token = access.issue_full_invite()
    assert full.get('/gallery/access/' + full_token).status_code == 303
    assert full.get('/gallery/offline-setup').status_code == 200
    certificate = full.get('/gallery/offline-setup/root-ca.cer')
    assert certificate.status_code == 200
    assert certificate.data == b'fixture-ca'

    guest = app.test_client()
    guest_token = access.create_guest_share('test-owner', 'Guest')['token']
    assert guest.get('/gallery/access/' + guest_token).status_code == 303
    assert guest.get('/gallery/offline-setup').status_code == 403
    assert guest.get('/gallery/offline-setup/root-ca.cer').status_code == 403


def test_local_https_proxy_scheme_is_accepted_but_spoofed_forwarding_is_not(tmp_path):
    data = tmp_path / 'data'
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\nEMAIL_MAILBOX=INBOX\n')
    app = create_app(Config(
        data_dir=data,
        env_file=env,
        secret_key='s' * 64,
        email_enabled=False,
    ))
    app.testing = True
    access = app.extensions['gallery_access']
    origin = 'https://10.40.80.254'

    client = app.test_client()
    token = access.issue_full_invite()
    assert client.get('/gallery/access/' + token, base_url='http://10.40.80.254').status_code == 303
    info = client.get('/gallery/api/access', base_url='http://10.40.80.254').get_json()
    response = client.post(
        '/gallery/api/share',
        base_url='http://10.40.80.254',
        data={'csrf': info['csrf'], 'name': 'Proxy test'},
        headers={'Origin': origin, 'X-Forwarded-Proto': 'https'},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
    )
    assert response.status_code == 200

    response = client.post(
        '/gallery/api/share',
        base_url='http://10.40.80.254',
        data={'csrf': info['csrf'], 'name': 'Spoofed proxy'},
        headers={'Origin': origin, 'X-Forwarded-Proto': 'https'},
        environ_overrides={'REMOTE_ADDR': '10.40.80.44'},
    )
    assert response.status_code == 403
