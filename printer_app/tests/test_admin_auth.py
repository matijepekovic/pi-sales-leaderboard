"""Printer-admin authentication is separate from Gallery access and printer workflows."""
from pathlib import Path

from printer_app.app import create_app
from printer_app.config import Config


def app_with_temp_password(tmp_path):
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\nEMAIL_MAILBOX=INBOX\n')
    app = create_app(Config(
        data_dir=tmp_path / 'data',
        env_file=env,
        secret_key='s' * 64,
        email_enabled=False,
    ))
    app.testing = True
    password = app.extensions['printer_admin_auth'].ensure_temporary_password()
    return app, password


def csrf(client):
    with client.session_transaction() as session:
        return session['csrf']


def test_admin_login_forces_password_change_and_protects_menu(tmp_path):
    app, temporary = app_with_temp_password(tmp_path)
    client = app.test_client()

    response = client.get('/')
    assert response.status_code == 302
    assert '/login?' in response.headers['Location']
    assert client.get('/login').status_code == 200

    response = client.post('/login', data={
        'csrf': csrf(client),
        'username': 'admin',
        'password': temporary,
        'next': '/system/print-control',
    })
    assert response.status_code == 303
    assert '/change-password?' in response.headers['Location']

    new_password = 'new-private-password-123'
    response = client.post('/change-password', data={
        'csrf': csrf(client),
        'current_password': temporary,
        'new_password': new_password,
        'confirmation': new_password,
        'next': '/system/print-control',
    })
    assert response.status_code == 303
    assert client.get('/system/print-control').status_code == 200
    assert client.get('/settings').status_code == 200

    response = client.post('/logout', data={'csrf': csrf(client)})
    assert response.status_code == 303
    assert client.get('/system/print-control').status_code == 302


def test_gallery_full_access_does_not_grant_printer_admin(tmp_path):
    app, _ = app_with_temp_password(tmp_path)
    client = app.test_client()
    gallery_access = app.extensions['gallery_access']
    token = gallery_access.issue_full_invite()

    assert client.get('/gallery/access/' + token).status_code == 303
    assert client.get('/gallery/').status_code == 200
    assert client.get('/').status_code == 302
    queue = client.get('/gallery/queue')
    assert queue.status_code == 302
    assert '/login?' in queue.headers['Location']


def test_authentication_owners_stay_separate():
    root = Path(__file__).resolve().parents[1]
    service = (root / 'admin_auth.py').read_text()
    repository = (root / 'admin_auth_repository.py').read_text()
    gallery = (root / 'gallery/access_service.py').read_text()
    assert 'SELECT ' not in service and 'INSERT ' not in service and 'UPDATE ' not in service
    assert 'SELECT ' in repository and 'admin_auth' in repository
    assert "'manage'" not in gallery
