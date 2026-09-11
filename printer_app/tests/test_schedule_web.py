"""Browser schedule fields normalize once; all mutations keep CSRF/origin checks."""
import pytest
pytest.importorskip('flask')
from werkzeug.datastructures import MultiDict

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.print_schedule import PrintSchedule
from printer_app.settings import SettingsService
from printer_app.settings_repository import SettingsRepository


@pytest.fixture
def ui(tmp_path):
    env = tmp_path/'env'; env.write_text('EMAIL_USER=fixture@example.test\nEMAIL_APP_PASSWORD=kept-secret\n')
    cfg = Config(data_dir=tmp_path/'data', env_file=env, secret_key='s'*64)
    app = create_app(cfg); app.testing = True
    client = app.test_client(); client.get('/settings')
    with client.session_transaction() as session: token = session['csrf']
    return app, client, token, env, cfg


def form(ui, **changes):
    app, _, token, _, _ = ui
    service = app.extensions['printer_settings']; cfg, revision = service.read()
    result = dict(service.public_values(cfg), csrf=token, revision=revision)
    result.pop('PRINT_SCHEDULE_DAYS')
    result.update(schedule_days_present='1', schedule_day_mon='1', schedule_day_wed='1',
                  PRINT_SCHEDULE_MODE='weekly', PRINT_SCHEDULE_TIME='17:15')
    result.update(changes)
    return result


def test_schedule_form_saves_days_and_time_without_stopping_gmail(ui):
    _, client, _, env, cfg = ui
    response = client.post('/settings', data=form(ui), follow_redirects=True)
    assert response.status_code == 200 and b'Settings saved' in response.data
    current, _ = SettingsService(SettingsRepository(env), cfg).read()
    assert current.print_schedule == PrintSchedule('weekly', ('mon','wed'), '17:15')
    assert current.email_enabled and current.email_password == 'kept-secret'
    assert b'kept-secret' not in response.data
    assert client.get('/api/status').json['print_schedule']['mode'] == 'weekly'
    assert b'Print schedule &amp; waiting queue' in client.get('/').data


def test_no_days_selected_is_visible_error_not_old_days_reused(ui):
    _, client, _, env, _ = ui
    values = form(ui); values.pop('schedule_day_mon'); values.pop('schedule_day_wed')
    before = env.read_bytes()
    assert client.post('/settings', data=values).status_code == 400
    assert env.read_bytes() == before


def test_duplicate_or_forged_schedule_save_is_rejected(ui):
    _, client, _, env, _ = ui
    values = form(ui); before = env.read_bytes()
    assert client.post('/settings', data=values, headers={'Origin':'http://evil.example'}).status_code == 403
    dup = MultiDict(values); dup.add('schedule_day_mon','1')
    assert client.post('/settings', data=dup).status_code == 400
    assert env.read_bytes() == before


def test_manual_release_is_explicit_post_not_check_email_or_get(ui):
    app, client, token, _, _ = ui
    db = app.extensions['printer_db']
    assert client.get('/control/print-queued-now').status_code == 405
    assert client.post('/control/print-queued-now').status_code == 400
    assert client.post('/control/print-queued-now', data={'csrf':token}, headers={'Origin':'null'}).status_code == 403
    assert not db.rows('SELECT * FROM commands')
    assert client.post('/control/run-now', data={'csrf':token}).status_code == 302
    assert [row['name'] for row in db.rows('SELECT * FROM commands')] == ['run-now']
    client.post('/control/print-queued-now', data={'csrf':token})
    assert {row['name'] for row in db.rows('SELECT * FROM commands')} == {'run-now','print-queued-now'}
    assert not db.rows('SELECT * FROM print_queue_releases')  # Worker, never HTTP, releases batches.
