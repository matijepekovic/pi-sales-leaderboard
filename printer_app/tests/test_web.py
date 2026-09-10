import time
from pathlib import Path

import pytest
pytest.importorskip('flask')

from printer_app.app import create_app
from printer_app.config import Config


@pytest.fixture
def web(tmp_path):
    cfg = Config(data_dir=tmp_path, secret_key='a' * 64, email_password='do-not-expose-secret')
    app = create_app(cfg)
    app.testing = True
    return app, app.test_client()


def token(client):
    response = client.get('/system/print-control')
    assert response.status_code == 200
    with client.session_transaction() as session:
        return session['csrf']


def test_ui_opens_directly_without_login(web):
    app, client = web
    assert client.get('/').status_code == 200
    assert client.get('/system/print-control').status_code == 200
    assert client.get('/api/status').status_code == 200
    assert client.get('/login').status_code == 404
    assert app.config['SESSION_COOKIE_NAME'] != 'session'


def test_csrf_required_for_every_write(web):
    _, client = web
    csrf = token(client)
    assert client.post('/control/test-print').status_code == 400
    assert client.post('/control/test-print', data={'csrf': csrf}).status_code == 302


def test_health_no_secrets_and_worker_awareness(web):
    app, client = web
    assert client.get('/health').status_code == 503
    db = app.extensions['printer_db']
    db.set('worker_heartbeat', time.time())
    db.set('printer_status', {'known': True, 'online': True})
    response = client.get('/health')
    assert response.status_code == 200
    assert set(response.json) == {'web', 'database', 'worker_running', 'cups_queue_known'}
    assert b'do-not-expose-secret' not in response.data


def test_controls_persist_in_own_database(web):
    app, client = web
    csrf = token(client)
    db = app.extensions['printer_db']
    client.post('/control/pause', data={'csrf': csrf})
    assert db.get('paused') is True
    client.post('/control/resume', data={'csrf': csrf})
    assert db.get('paused') is False
    for _ in range(2):
        client.post('/control/run-now', data={'csrf': csrf})
    assert len(db.rows('SELECT * FROM commands')) == 1


def test_no_arbitrary_filesystem_preview(web, tmp_path):
    app, client = web
    token(client)
    db = app.extensions['printer_db']
    jid = db.execute("INSERT INTO jobs(group_key,created,updated) VALUES ('x',?,?)", (time.time(), time.time()))
    outside = tmp_path.parent / 'outside.pdf'
    outside.write_bytes(b'private')
    db.output(jid, 'unsafe', outside)
    oid = db.one('SELECT id FROM outputs')['id']
    assert client.get(f'/outputs/{oid}').status_code == 404


def test_job_detail_escapes_untrusted_values(web):
    app, client = web
    token(client)
    db = app.extensions['printer_db']
    jid = db.execute("INSERT INTO jobs(group_key,substatus,created,updated) VALUES ('x','<script>alert(1)</script>',?,?)", (time.time(), time.time()))
    response = client.get(f'/jobs/{jid}')
    assert response.status_code == 200
    assert b'<script>alert(1)</script>' not in response.data
    assert b'&lt;script&gt;' in response.data
