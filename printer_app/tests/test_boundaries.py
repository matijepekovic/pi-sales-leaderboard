import ast
from dataclasses import replace
from email.message import EmailMessage
import hashlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
import pytest
from printer_app.bootstrap import build_web
from printer_app.deploy import source_hash
from printer_app.files import contained, safe_name
from printer_app.gmail_client import GmailClient
from printer_app.services import ControlService
from .conftest import make_pdf, ingest

PACKAGE = Path(__file__).resolve().parents[1]


def csrf(client):
    with client.session_transaction() as session:
        return session['csrf']


def login(client):
    client.get('/login')
    return client.post('/login', data={'csrf': csrf(client), 'username': 'admin', 'password': 'testing-password-123'})


def test_ui_auth_csrf_preview_and_no_secret_disclosure(setup):
    cfg, repo, _, _, service = setup
    app = build_web(cfg)
    client = app.test_client()
    assert client.get('/').status_code == 302
    assert client.post('/control/test').status_code == 400
    assert login(client).status_code == 302
    assert client.get('/system/print-control').status_code == 200
    assert client.post('/control/run', data={'csrf': 'wrong'}).status_code == 400
    assert client.post('/control/test', data={'csrf': csrf(client)}).status_code == 302
    assert len(repo.commands()) == 1
    path = make_pdf(cfg.data_dir / 'received.pdf')
    ingest(repo, path)
    service.prepare()
    job = repo.recent()[0]
    out = repo.outputs(job['id'])[0]
    response = client.get('/files/' + out['id'])
    assert response.status_code == 200
    assert response.mimetype == 'application/pdf'
    assert client.get('/files/../../etc/passwd').status_code == 404
    page = client.get('/jobs/' + job['id']).get_data(as_text=True)
    assert cfg.session_secret not in page
    assert cfg.ui_password_hash not in page
    client.post('/logout', data={'csrf': csrf(client)})
    assert client.get('/files/' + out['id']).status_code == 302


def test_auth_is_required_at_configuration_time(setup):
    cfg, *_ = setup
    with pytest.raises(RuntimeError, match='authentication'):
        build_web(replace(cfg, ui_password_hash=''))


def test_health_reports_only_booleans_and_database_failure(setup):
    cfg, repo, *_ = setup
    control = ControlService(cfg, repo)
    app = build_web(cfg)
    client = app.test_client()
    response = client.get('/health')
    assert response.status_code == 503
    assert all(type(v) is bool for v in response.json.values())
    repo.put('heartbeat', time.time())
    repo.put('printer', {'known': True})
    assert client.get('/health').status_code == 200
    repo.path = cfg.data_dir / 'missing-directory' / 'missing.db'
    assert not control.health()['database_accessible']


def test_wrong_password_rate_limit(setup):
    cfg, *_ = setup
    client = build_web(cfg).test_client()
    client.get('/login')
    for _ in range(5):
        response = client.post('/login', data={'csrf': csrf(client), 'username': 'admin', 'password': 'wrong'})
        assert response.status_code == 401
    assert client.post('/login', data={'csrf': csrf(client), 'username': 'admin', 'password': 'wrong'}).status_code == 429


def test_untrusted_names_cannot_escape_storage(tmp_path):
    assert '/' not in safe_name('../../evil.pdf')
    assert '\\' not in safe_name('C:\\folder\\evil.pdf')
    with pytest.raises(ValueError):
        contained(tmp_path, '/etc/passwd')
    (tmp_path / 'escape').symlink_to('/etc/passwd')
    with pytest.raises(ValueError):
        contained(tmp_path, tmp_path / 'escape')


def test_no_host_imports_or_database_bypasses_or_shell_true():
    forbidden = {'app', 'stats_core', 'storage', 'tableau', 'database', 'server', 'themes'}
    for path in PACKAGE.glob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [] if node.level else [node.module or '']
            else:
                imports = []
            assert not any(name.split('.')[0] in forbidden for name in imports), path
            if path.name not in {'db.py', 'repository.py'}:
                assert not any(name.startswith('sqlite3') for name in imports), path
            if isinstance(node, ast.Call):
                assert not any(k.arg == 'shell' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords), path
    # Cross-boundary import in the other direction must not silently reappear either.
    root = PACKAGE.parent
    for directory in ('app', 'stats_core'):
        for path in (root / directory).rglob('*.py'):
            assert 'import printer_app' not in path.read_text()
            assert 'from printer_app' not in path.read_text()


def test_unit_lifecycle_and_identity_are_independent():
    for path in (PACKAGE / 'systemd').glob('*.service'):
        text = path.read_text()
        assert 'User=scoreboard' in text
        assert 'EnvironmentFile=@HOME@/.config/printer-app/env' in text
        assert 'Restart=on-failure' in text
        assert not any(line.startswith(('Requires=', 'PartOf=', 'BindsTo=')) for line in text.splitlines())
        assert 'leaderboard' not in text.lower()
        assert 'stats' not in text.lower()
    assert '.venv/bin/python -m printer_app worker' in (PACKAGE / 'systemd/printer-app-worker.service').read_text()
    assert '.venv/bin/python -m printer_app web' in (PACKAGE / 'systemd/printer-app-web.service').read_text()


def test_package_runs_when_removed_from_host_repository(tmp_path):
    isolated = tmp_path / 'alone'
    shutil.copytree(PACKAGE, isolated / 'printer_app', ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
    code = """from pathlib import Path
from printer_app.config import Config
from printer_app.bootstrap import build_web
from werkzeug.security import generate_password_hash
import sys
app=build_web(Config(data_dir=Path('data'),ui_password_hash=generate_password_hash('test-password'),session_secret='s'*64))
assert app.test_client().get('/login').status_code == 200
assert 'app' not in sys.modules
assert not any(n.startswith('stats_core') for n in sys.modules)
assert 'printer_app.worker' not in sys.modules
assert 'printer_app.gmail_client' not in sys.modules
"""
    subprocess.run([sys.executable, '-c', code], cwd=isolated, check=True, timeout=30)


def test_deployment_hash_ignores_secrets_runtime_and_caches(tmp_path):
    (tmp_path / 'module.py').write_text('print(1)')
    before = source_hash(tmp_path)
    (tmp_path / '.env').write_text('DO_NOT_SHIP=private')
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'printer_app.db').write_bytes(b'private ledger')
    (tmp_path / '__pycache__').mkdir()
    (tmp_path / '__pycache__' / 'thing.pyc').write_bytes(b'cache')
    assert source_hash(tmp_path) == before
    (tmp_path / 'module.py').write_text('print(2)')
    assert source_hash(tmp_path) != before


def test_oversized_attachment_is_downloaded_in_chunks_not_rejected(setup):
    cfg, repo, *_ = setup
    cfg = replace(cfg, email_user='user@example.test', email_password='never-log-this', attachment_warn_mb=1, disk_reserve_mb=0)
    message = EmailMessage()
    message['Subject'] = 'A report'
    message['From'] = 'sender@example.test'
    message['Message-ID'] = '<oversized-test>'
    message.set_content('Body')
    payload = b'large-but-download-it\n' * 80_000
    message.add_attachment(payload, maintype='application', subtype='octet-stream', filename='oversized.bin')
    raw = message.as_bytes()
    requests = []
    class IMAP:
        def login(self, user, password):
            assert user == cfg.email_user and password == cfg.email_password
        def select(self, mailbox, readonly):
            assert readonly
            return 'OK', []
        def response(self, key):
            return key, [b'123']
        def uid(self, action, *args):
            if action == 'search':
                return 'OK', [b'7']
            fields = args[-1]
            requests.append(fields)
            if 'HEADER.FIELDS' in fields:
                return 'OK', [(b'header', b'Subject: A report\r\nFrom: sender@example.test\r\nMessage-ID: <oversized-test>\r\n\r\n')]
            offset, count = map(int, re.search(r'<(\d+)\.(\d+)>', fields).groups())
            return 'OK', [(b'body', raw[offset:offset + count])]
        def logout(self):
            return 'OK', []
    source = GmailClient(cfg, factory=lambda *a, **k: IMAP())
    found = list(source.messages(repo.seen))
    assert len(found) == 1
    assert found[0].attachments[0].size == len(payload)
    assert found[0].attachments[0].path.read_bytes() == payload
    assert len([r for r in requests if 'BODY.PEEK[]' in r]) > 1
    repo.ingest(found[0])
    assert list(source.messages(repo.seen)) == []
