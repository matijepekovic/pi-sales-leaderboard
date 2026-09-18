"""Secure Gallery adapter stays deployment/runtime isolated from Gallery data."""
import json
from pathlib import Path

from printer_app import https_adapter
from printer_app.app import create_app, web_server_options
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
    assert 'header_up X-Forwarded-Host {http.request.host}' in config
    assert 'header_up X-Forwarded-Proto https' in config
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


def test_secure_offline_setup_is_owned_by_first_secure_full_device(tmp_path):
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

    owner = app.test_client()
    owner_token = access.issue_full_invite()
    enrolled = owner.get('/gallery/access/' + owner_token, base_url='http://10.40.80.254')
    assert enrolled.status_code == 303
    assert 'SameSite=Lax' in enrolled.headers.get('Set-Cookie', '')

    http_info = owner.get('/gallery/api/access', base_url='http://10.40.80.254').get_json()
    assert 'offline' not in http_info['capabilities']
    assert http_info['offline_owner_set'] is False

    secure_info = owner.get('/gallery/api/access', base_url='https://10.40.80.254').get_json()
    assert 'offline' in secure_info['capabilities']
    assert secure_info['offline_owner_set'] is True
    setup = owner.get('/gallery/offline-setup', base_url='https://10.40.80.254')
    assert setup.status_code == 200
    certificate = owner.get('/gallery/offline-setup/root-ca.cer', base_url='https://10.40.80.254')
    assert certificate.status_code == 200
    assert certificate.data == b'fixture-ca'

    other = app.test_client()
    other_token = access.issue_full_invite()
    assert other.get('/gallery/access/' + other_token, base_url='http://10.40.80.254').status_code == 303
    other_info = other.get('/gallery/api/access', base_url='https://10.40.80.254').get_json()
    assert other_info['role'] == 'full'
    assert 'offline' not in other_info['capabilities']
    assert other_info['offline_owner_set'] is True
    assert other.get('/gallery/offline-setup', base_url='https://10.40.80.254').status_code == 403
    assert other.get('/gallery/offline-setup/root-ca.cer', base_url='https://10.40.80.254').status_code == 403

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
        base_url='http://127.0.0.1:5055',
        data={'csrf': info['csrf'], 'name': 'Proxy test'},
        headers={
            'Origin': origin + ':443',
            'X-Forwarded-Proto': 'https',
            'X-Forwarded-Host': '10.40.80.254',
        },
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
    )
    assert response.status_code == 200

    response = client.post(
        '/gallery/api/share',
        base_url='http://10.40.80.254',
        data={'csrf': info['csrf'], 'name': 'Spoofed proxy'},
        headers={
            'Origin': origin,
            'X-Forwarded-Proto': 'https',
            'X-Forwarded-Host': '10.40.80.254',
        },
        environ_overrides={'REMOTE_ADDR': '10.40.80.44'},
    )
    assert response.status_code == 403

    response = client.post(
        '/gallery/api/share',
        base_url='http://127.0.0.1:5055',
        data={'csrf': info['csrf'], 'name': 'Wrong secure host'},
        headers={
            'Origin': 'https://evil.example',
            'X-Forwarded-Proto': 'https',
            'X-Forwarded-Host': '10.40.80.254',
        },
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
    )
    assert response.status_code == 403



def test_waitress_trusts_only_loopback_gallery_proxy_headers(tmp_path):
    cfg = Config(
        data_dir=tmp_path / 'data',
        secret_key='s' * 64,
        email_enabled=False,
    )
    options = web_server_options(cfg)
    assert options['trusted_proxy'] == '127.0.0.1'
    assert options['trusted_proxy_count'] == 1
    assert options['trusted_proxy_headers'] == {'x-forwarded-host', 'x-forwarded-proto'}
    assert options['clear_untrusted_proxy_headers'] is True
    assert '*' not in options['trusted_proxy_headers']
