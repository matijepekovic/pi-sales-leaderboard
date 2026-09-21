"""Print activity reports worker receipts truthfully and refreshes without dispatching jobs."""
import os
import re
import threading
import time

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.db import Database
from printer_app.print_dispatch import PrintDispatchService
from printer_app.print_queue_repository import PrintQueueRepository
from printer_app.print_schedule import PrintSchedule
from printer_app.tests.auth_helpers import browser_login, login_admin


def generated_job(db, directory, filename='Morning MOD cards.pdf', *, status='READY',
                  is_error=False, at=100):
    number = db.one('SELECT COUNT(*) AS n FROM jobs')['n'] + 1
    job_id, _ = PrintQueueRepository(db).enqueue_generated_pdf(
        'pdf:activity-' + str(number), directory / filename, 2, {}, at)
    db.execute('UPDATE jobs SET status=?,is_error=?,updated=? WHERE id=?',
               (status, int(is_error), at, job_id))
    return job_id


def email_job(db, directory, filename='Daily report.xlsx', *, at=100):
    message = db.execute("""INSERT INTO processed_messages
        (identity,account,mailbox,uidvalidity,uid,message_id,subject,sender,created)
        VALUES ('activity-email','fixture','INBOX','1','1','activity-email',
                'Daily reporting','office@example.test',?)""", (at,))
    attachment = db.execute("""INSERT INTO attachments
        (message_id,part,filename,path,state,created) VALUES (?,'1',?,?,'DONE',?)""",
        (message, filename, str(directory / filename), at))
    job_id = db.create_job(attachment, 'Daily report', {})
    db.execute("UPDATE jobs SET status='READY',printable=?,updated=? WHERE id=?",
               (str(directory / 'converted.pdf'), at, job_id))
    return job_id


def attempt(db, job_id, request_id, state, at):
    return db.execute("""INSERT INTO print_attempts
        (job_id,token,state,request_id,created,updated) VALUES (?,?,?,?,?,?)""",
        (job_id, f'activity-{job_id}-{at}', state, request_id, at, at))


def queue_snapshot(db):
    return {table: db.rows('SELECT * FROM ' + table + ' ORDER BY id')
            for table in ('jobs', 'commands', 'print_attempts', 'steps', 'outputs')} | {
        'releases': db.rows('SELECT * FROM print_queue_releases ORDER BY attachment_id'),
        'schedule': db.get('print_schedule_state'),
    }


@pytest.fixture
def web(tmp_path):
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\nPRINT_SCHEDULE_MODE=hold\n')
    app = create_app(Config(data_dir=tmp_path / 'data', env_file=env,
                            secret_key='s' * 64, email_enabled=False,
                            print_schedule=PrintSchedule('hold')))
    app.testing = True
    return app, app.extensions['printer_db'], tmp_path


def test_activity_repository_uses_latest_receipt_step_and_updated_order(tmp_path):
    db = Database(tmp_path / 'printer.sqlite')
    repository = PrintQueueRepository(db)
    first = generated_job(db, tmp_path, 'Original generated name.pdf', at=10)
    second = generated_job(db, tmp_path, 'Fallback printable.pdf', at=20)
    db.execute('DELETE FROM outputs WHERE job_id=?', (second,))
    db.execute('UPDATE jobs SET printable=?,updated=50 WHERE id=?',
               (str(tmp_path / 'temporary-output.pdf'), first))
    attempt(db, first, 'konicaa-11', 'FAILED', 21)
    attempt(db, first, 'konicaa-12', 'RELEASED', 22)
    db.execute('INSERT INTO steps(job_id,at,message) VALUES (?,?,?)', (first, 23, 'Old retry'))
    db.execute('INSERT INTO steps(job_id,at,message) VALUES (?,?,?)', (first, 24, 'Waiting for completion'))
    before = queue_snapshot(db)

    rows = repository.recent_activity()

    assert [row['id'] for row in rows] == [first, second]
    assert rows[0]['generated_filename'] == str(tmp_path / 'Original generated name.pdf')
    service = PrintDispatchService(repository, PrintSchedule(), 'UTC')
    assert service.describe_job(rows[0])['display_name'] == 'Original generated name.pdf'
    assert service.describe_job(rows[1])['display_name'] == 'Fallback printable.pdf'
    assert rows[0]['attempt_request_id'] == 'konicaa-12'
    assert rows[0]['attempt_state'] == 'RELEASED'
    assert rows[0]['latest_step'] == 'Waiting for completion'
    assert [row['id'] for row in repository.recent_activity(limit=1)] == [first]
    assert queue_snapshot(db) == before


@pytest.mark.parametrize('status,is_error,label,tone', [
    ('READY', False, 'Ready to print', 'pending'),
    ('SUBMITTED', False, 'Sent to printer', 'pending'),
    ('PRINTED', False, 'Printed', 'good'),
    ('READY', True, 'Error sheet queued', 'error'),
    ('SUBMITTED', True, 'Error sheet sent', 'error'),
    ('ERROR PRINTED', True, 'Error sheet printed', 'error'),
    ('PRINTER ERROR', False, 'Needs attention', 'error'),
    ('PRINT UNKNOWN', False, 'Outcome unknown', 'error'),
])
def test_activity_status_distinguishes_receipt_from_report_success(tmp_path, status, is_error, label, tone):
    db = Database(tmp_path / 'printer.sqlite')
    job_id = generated_job(db, tmp_path, status=status, is_error=is_error)
    attempt(db, job_id, 'konicaa-42', 'COMPLETE' if status.endswith('PRINTED') else 'RELEASED', 101)
    db.execute('INSERT INTO steps(job_id,at,message) VALUES (?,?,?)',
               (job_id, 102, 'Printer unavailable: check the connection'))
    repository = PrintQueueRepository(db)
    service = PrintDispatchService(repository, PrintSchedule(), 'UTC', clock=lambda: 110)
    job = service.describe_job(repository.recent_activity()[0])

    assert job['status_label'] == label
    assert job['status_tone'] == tone
    assert job['queue_status'] == status
    assert job['display_name'] == 'Morning MOD cards.pdf'
    assert job['receipt'] == 'konicaa-42'
    assert job['status_detail']
    if status == 'SUBMITTED':
        assert 'complet' in job['status_detail'].lower()
    if status == 'PRINTER ERROR':
        assert 'check the connection' in job['status_detail']
    if is_error:
        assert job['status_tone'] != 'good'
        assert 'report was not confirmed printed' in job['status_detail'].lower()


def test_activity_counts_only_recent_200_and_keeps_completed_error_sheets_out_of_success(tmp_path):
    db = Database(tmp_path / 'printer.sqlite')
    with db.connect() as conn:
        for number in range(201):
            status = {0:'PRINTED', 1:'PRINTED', 2:'ERROR PRINTED',
                      3:'CANCELLED', 4:'SUBMITTED'}.get(number, 'READY')
            conn.execute('''INSERT INTO jobs
                (group_key,status,is_error,created,updated,completed) VALUES (?,?,?,?,?,?)''',
                ('pdf:count-' + str(number), status, int(status == 'ERROR PRINTED'),
                 number, number, {0:50, 1:60, 2:90}.get(number)))
    db.set('worker_heartbeat', 990)
    service = PrintDispatchService(PrintQueueRepository(db), PrintSchedule(), 'UTC', clock=lambda: 1000)
    before = queue_snapshot(db)

    activity = service.activity()

    assert len(activity['jobs']) == 200
    assert [job['id'] for job in activity['jobs']] == list(range(201, 1, -1))
    assert activity['counts'] == {'printed': 1, 'pending': 197, 'attention': 1, 'cancelled': 1}
    assert activity['last_report_printed'] == 60
    assert activity['worker_alive'] is True
    db.set('worker_heartbeat', 900)
    assert service.activity()['worker_alive'] is False
    assert queue_snapshot(db) == before


def test_activity_keeps_email_filename_and_schedule_waiting_state(web):
    _, db, directory = web
    job_id = email_job(db, directory)
    db.output(job_id, 'Generated PDF', directory / 'converted.pdf')
    repository = PrintQueueRepository(db)
    service = PrintDispatchService(repository, PrintSchedule('hold'), 'UTC', clock=lambda: 110)
    before = queue_snapshot(db)

    job = service.describe_job(repository.recent_activity()[0])

    assert job['display_name'] == 'Daily report.xlsx'
    assert job['waiting_for_schedule'] is True
    assert job['queue_status'] == 'QUEUED'
    assert job['status_label'] == 'Waiting for schedule'
    assert queue_snapshot(db) == before


def test_activity_partial_requires_admin_escapes_names_and_never_dispatches(web):
    app, db, directory = web
    email_job(db, directory, 'Report <script>alert(1)</script>.xlsx')
    client = app.test_client()
    assert client.get('/api/print-activity').status_code == 401
    login_admin(client)
    before = queue_snapshot(db)

    response = client.get('/api/print-activity')

    assert response.status_code == 200
    assert response.mimetype == 'text/html'
    assert b'&lt;script&gt;alert(1)&lt;/script&gt;' in response.data
    assert b'<script>alert(1)</script>' not in response.data
    assert b'Waiting for schedule' in response.data
    assert b'data-worker-warning' in response.data
    assert b'worker is offline' in response.data
    page = client.get('/system/print-control').data
    assert page.index(b'id="printActivity"') < page.index(b'id="printQueue"')
    assert queue_snapshot(db) == before


@pytest.mark.parametrize('original_state', ['FAILED', 'UNKNOWN'])
def test_pending_error_sheet_does_not_relabel_the_original_report_receipt(web, original_state):
    app, db, directory = web
    job_id = generated_job(db, directory, is_error=True)
    attempt(db, job_id, 'konicaa-55', original_state, 101)
    client = app.test_client()
    login_admin(client)
    before = queue_snapshot(db)

    response = client.get('/api/print-activity')

    assert response.status_code == 200
    assert b'Error sheet queued' in response.data
    assert b'The report was not confirmed printed.' in response.data
    assert b'Printer receipt: konicaa-55' in response.data
    assert b'Error sheet receipt' not in response.data
    assert queue_snapshot(db) == before


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')
@pytest.mark.parametrize('engine', ['chromium', 'webkit'])
def test_activity_updates_from_queued_to_receipted_completion_without_reload(web, engine):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server

    app, db, directory = web
    for number in range(8):
        old_job = generated_job(db, directory, f'Older report {number}.pdf',
                                status='PRINTED', at=number + 1)
        db.execute('UPDATE jobs SET completed=updated WHERE id=?', (old_job,))
    job_id = generated_job(db, directory, 'Morning MOD cards.pdf', at=time.time())
    db.set('worker_heartbeat', time.time())
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = getattr(pw, engine).launch()
            try:
                page = browser.new_page(viewport={'width':1280, 'height':900})
                errors, requests = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: requests.append((request.method, request.url)))
                browser_login(page, app, f'http://127.0.0.1:{server.server_port}')
                activity = page.locator('#printActivity')
                row = activity.locator(f'[data-job-id="{job_id}"]')
                status = row.locator('[data-print-status]')
                title_link = row.get_by_role('link', name='Morning MOD cards.pdf', exact=True)
                expect(activity).to_contain_text('Morning MOD cards.pdf')
                expect(status).to_have_text('Ready to print')

                def assert_activity_layout():
                    expect(title_link).to_be_visible()
                    expect(status).to_be_visible()
                    assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')
                    listing = activity.locator('.print-activity-list')
                    assert 0 < listing.bounding_box()['height'] <= 520
                    assert listing.evaluate('(node) => node.scrollHeight > node.clientHeight')
                    expect(page.locator('#printQueue')).to_be_visible()
                    box = activity.bounding_box()
                    assert page.locator('#printQueue').bounding_box()['y'] >= box['y'] + box['height']

                assert_activity_layout()
                page.set_viewport_size({'width':390, 'height':844})
                assert_activity_layout()
                title_link.focus()
                page.evaluate("() => {window.activityDocument = 'same-document';}")
                requests.clear()

                receipt = attempt(db, job_id, 'konicaa-77', 'RELEASED', time.time())
                db.execute("UPDATE jobs SET status='SUBMITTED',updated=? WHERE id=?", (time.time(), job_id))
                expect(status).to_have_text('Sent to printer', timeout=12000)
                expect(row).to_contain_text('konicaa-77')
                expect(row).to_contain_text(re.compile('complet', re.I))
                expect(title_link).to_be_focused()
                db.execute("UPDATE print_attempts SET state='COMPLETE',updated=? WHERE id=?",
                           (time.time(), receipt))
                db.execute("UPDATE jobs SET status='PRINTED',completed=?,updated=? WHERE id=?",
                           (time.time(), time.time(), job_id))
                expect(status).to_have_text('Printed', timeout=12000)
                expect(row).to_contain_text('Completed')
                expect(row).to_contain_text('konicaa-77')
                expect(title_link).to_be_focused()
                assert page.evaluate('() => window.activityDocument') == 'same-document'
                assert any(url.endswith('/api/print-activity') for _, url in requests)
                assert all(method == 'GET' for method, _ in requests)
                assert not db.rows('SELECT * FROM commands')
                assert not db.rows('SELECT * FROM print_queue_releases')
                assert len(db.rows('SELECT * FROM print_attempts')) == 1
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
