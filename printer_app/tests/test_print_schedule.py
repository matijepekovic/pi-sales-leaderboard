"""Weekly releases use a durable printer-only queue, not the email poll clock."""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import threading
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfWriter

from printer_app.config import Config
from printer_app.db import Database
from printer_app.gmail_client import GmailClient
from printer_app.print_dispatch import PrintDispatchService
from printer_app.print_queue_repository import PrintQueueRepository
from printer_app.print_schedule import PrintSchedule
from printer_app.settings import SettingsService, SettingsError
from printer_app.settings_repository import SettingsRepository
from printer_app.worker import Engine

ZONE = 'America/Los_Angeles'


def stamp(text):
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(ZONE)).timestamp()


@pytest.mark.parametrize('patch', [
    {'PRINT_SCHEDULE_MODE': 'sometimes'}, {'PRINT_SCHEDULE_TIME': '24:00'},
    {'PRINT_SCHEDULE_TIME': '9:00'}, {'PRINT_SCHEDULE_TIME': '09:60'},
    {'PRINT_SCHEDULE_DAYS': 'mon,mon'}, {'PRINT_SCHEDULE_DAYS': 'holiday'},
    {'PRINT_SCHEDULE_DAYS': 'mon;touch file'},
    {'PRINT_SCHEDULE_MODE': 'weekly', 'PRINT_SCHEDULE_DAYS': ''},
])
def test_invalid_schedule_rejected(patch):
    with pytest.raises(ValueError):
        PrintSchedule().apply(patch)


def test_selected_days_and_strict_next_time():
    schedule = PrintSchedule('weekly', ('mon', 'wed', 'fri'), '09:00')
    assert schedule.next_after(stamp('2026-09-07T08:59'), ZONE) == stamp('2026-09-07T09:00')
    assert schedule.next_after(stamp('2026-09-07T09:00'), ZONE) == stamp('2026-09-09T09:00')
    assert schedule.next_after(stamp('2026-09-11T10:00'), ZONE) == stamp('2026-09-14T09:00')
    assert PrintSchedule().next_after(stamp('2026-09-07T09:00'), ZONE) is None


def test_timezone_and_dst_no_duplicate_repeated_time():
    schedule = PrintSchedule('weekly', ('sun',), '01:30')
    first = stamp('2026-11-01T01:30')
    assert schedule.next_after(stamp('2026-11-01T00:00'), ZONE) == first
    assert schedule.next_after(first, ZONE) == stamp('2026-11-08T01:30')
    assert schedule.next_after(first + 3600, ZONE) == stamp('2026-11-08T01:30')
    spring = PrintSchedule('weekly', ('sun',), '02:30')
    assert spring.next_after(stamp('2026-03-08T00:00'), ZONE) == stamp('2026-03-08T03:30')
    assert schedule.next_after(stamp('2026-09-06T00:00'), 'UTC') != schedule.next_after(stamp('2026-09-06T00:00'), ZONE)


class PrinterSink:
    def __init__(self):
        self.jobs = {}; self.printed = []; self.offline = False
    def find(self, token):
        from printer_app.printer import PrinterError
        if self.offline:
            raise PrinterError('offline')
        return [j for j in self.jobs.values() if j['token'] == token]
    def hold(self, path, token, options, **kw):
        jid = len(self.jobs) + 1
        self.jobs[jid] = {'job-id': jid, 'job-state': 4, 'token': token, 'path': path}
        return jid, 'held', ['lp']
    def attributes(self, jid): return self.jobs[jid]
    def release(self, jid):
        if self.jobs[jid]['job-state'] == 4:
            self.printed.append(self.jobs[jid]['path'])
            self.jobs[jid]['job-state'] = 9
        return 'released'


@pytest.fixture
def rig(tmp_path, monkeypatch):
    clock = [stamp('2026-09-07T08:00')]
    monkeypatch.setattr('time.time', lambda: clock[0])
    schedule = PrintSchedule('weekly', ('mon', 'wed', 'fri'), '09:00')
    cfg = Config(data_dir=tmp_path/'data', print_schedule=schedule, email_user='fixture@example.test')
    db = Database(cfg.db_path)
    printer = PrinterSink()
    engine = Engine(cfg, db, printer)
    return clock, cfg, db, printer, engine


def collect(rig, filename='report.pdf', broken=False):
    clock, cfg, db, _, _ = rig
    n = db.one('SELECT COUNT(*) AS n FROM processed_messages')['n'] + 1
    mid = db.execute('''INSERT INTO processed_messages
        (identity,account,mailbox,uidvalidity,uid,message_id,subject,sender,created)
        VALUES (?,'fixture','INBOX','1',?,?,'Fixture report','fixture@example.test',?)''',
        (str(n), str(n), str(n), clock[0]))
    from io import BytesIO
    writer = PdfWriter(); writer.add_blank_page(width=612, height=792)
    payload = BytesIO(); writer.write(payload)
    GmailClient(cfg, db)._store(mid, '1', filename, b'broken' if broken else payload.getvalue())
    return db.one('SELECT * FROM attachments WHERE message_id=?', (mid,))


def finish(rig, engine=None):
    clock, _, _, _, original = rig
    for _ in range(3):
        (engine or original).tick(); clock[0] += 6


def test_collect_and_prepare_while_waiting_then_release_fixed_batch(rig):
    clock, _, db, printer, engine = rig
    for _ in range(3):
        collect(rig); engine.prepare_next()
    engine.tick()
    assert not printer.printed and not db.rows('SELECT * FROM print_attempts')
    assert engine.dispatch.summary()['waiting']['count'] == 3
    assert all(engine.dispatch.describe_job(j)['queue_status'] == 'QUEUED' for j in db.recent())
    clock[0] = stamp('2026-09-07T09:00')
    finish(rig)
    assert len(printer.printed) == 3
    assert engine.dispatch.summary()['next_run'] == stamp('2026-09-09T09:00')
    collect(rig); engine.prepare_next(); finish(rig)
    assert len(printer.printed) == 3  # Not an all-day printing window.
    clock[0] = stamp('2026-09-08T10:00'); finish(rig)
    assert len(printer.printed) == 3  # Tuesday was not selected.
    clock[0] = stamp('2026-09-09T09:00'); finish(rig)
    assert len(printer.printed) == 4


def test_errors_and_received_multipage_pdfs_also_wait(rig):
    clock, _, db, printer, engine = rig
    collect(rig, 'unsupported.doc', broken=True); engine.prepare_next()
    engine.tick()
    assert not printer.printed and db.recent()[0]['is_error']
    clock[0] = stamp('2026-09-07T09:00'); finish(rig)
    assert len(printer.printed) == 1 and db.recent()[0]['status'] == 'ERROR PRINTED'


def test_release_includes_collected_attachment_not_yet_prepared(rig):
    clock, _, _, printer, engine = rig
    collect(rig)
    clock[0] = stamp('2026-09-07T09:00'); engine.tick()
    assert not printer.printed
    clock[0] += 180; engine.prepare_next(); finish(rig)
    assert len(printer.printed) == 1


def test_reboot_retains_schedule_cursor_and_does_not_repeat_batch(rig):
    clock, cfg, db, printer, engine = rig
    collect(rig); engine.prepare_next()
    clock[0] = stamp('2026-09-07T09:00'); finish(rig)
    collect(rig); engine.prepare_next()
    restarted = Engine(cfg, Database(cfg.db_path), printer)
    finish(rig, restarted)
    assert len(printer.printed) == 1
    assert restarted.dispatch.summary()['waiting']['count'] == 1
    assert db.get('print_schedule_state')['last_run']['attachments'] == 1


def test_worker_downtime_coalesces_missed_slots_but_excludes_late_arrivals(rig):
    clock, cfg, _, printer, engine = rig
    collect(rig); engine.prepare_next()
    clock[0] = stamp('2026-09-10T10:00')
    collect(rig); engine.prepare_next()
    restarted = Engine(cfg, Database(cfg.db_path), printer)
    finish(rig, restarted)
    assert len(printer.printed) == 1
    assert restarted.dispatch.summary()['next_run'] == stamp('2026-09-11T09:00')


def test_manual_release_is_one_batch_and_command_is_consumed_atomically(rig):
    clock, cfg, db, printer, engine = rig
    held = Engine(replace(cfg, print_schedule=PrintSchedule('hold')), db, printer)
    collect(rig); held.prepare_next()
    held.dispatch.request_print_now(); held.dispatch.request_print_now()
    assert len(db.rows("SELECT * FROM commands WHERE name='print-queued-now'")) == 1
    clock[0] += 1; collect(rig); held.prepare_next()
    finish(rig, held)
    assert len(printer.printed) == 1
    assert not db.rows("SELECT * FROM commands WHERE name='print-queued-now'")
    assert held.dispatch.summary()['mode'] == 'hold'


def test_changing_time_defers_waiting_jobs_but_not_inflight_receipts(rig):
    clock, cfg, db, printer, engine = rig
    collect(rig); engine.prepare_next()
    later_cfg = replace(cfg, print_schedule=PrintSchedule('weekly', ('mon',), '10:00'))
    later = Engine(later_cfg, db, printer)
    clock[0] = stamp('2026-09-07T09:00'); finish(rig, later)
    assert not printer.printed
    clock[0] = stamp('2026-09-07T10:00'); later.tick()
    assert len(printer.printed) == 1
    held = Engine(replace(cfg, print_schedule=PrintSchedule('hold')), db, printer)
    finish(rig, held)
    assert db.recent()[0]['status'] == 'PRINTED'
    assert len(printer.printed) == 1


def test_schedule_edit_revokes_unsubmitted_batch_not_cups_attempts(rig):
    clock, cfg, db, printer, engine = rig
    collect(rig); engine.prepare_next()
    clock[0] = stamp('2026-09-07T09:00'); engine.dispatch.release_due()
    held = Engine(replace(cfg, print_schedule=PrintSchedule('hold')), db, printer)
    finish(rig, held)
    assert not printer.printed
    assert held.dispatch.summary()['waiting']['count'] == 1


def test_printer_outage_retries_released_jobs_after_scheduled_minute(rig):
    clock, _, db, printer, engine = rig
    collect(rig); engine.prepare_next(); printer.offline = True
    clock[0] = stamp('2026-09-07T09:00'); engine.tick()
    assert db.recent()[0]['status'] == 'PRINTER ERROR'
    clock[0] += 3600; printer.offline = False; finish(rig)
    assert len(printer.printed) == 1


def test_held_backlog_does_not_starve_test_print_or_submitted_job(rig):
    _, _, _, printer, engine = rig
    for _ in range(25):
        collect(rig); engine.prepare_next()
    engine.test_print(); finish(rig)
    assert len(printer.printed) == 1
    assert engine.dispatch.summary()['waiting']['count'] == 25


def test_busy_preparation_does_not_block_ready_batch(rig):
    clock, _, _, printer, engine = rig
    collect(rig); engine.prepare_next()
    entered, release = threading.Event(), threading.Event()
    def busy():
        entered.set(); release.wait(3)
    with ThreadPoolExecutor(max_workers=1) as background:
        future = background.submit(busy)
        assert entered.wait(1)
        clock[0] = stamp('2026-09-07T09:00'); engine.tick()
        assert not future.done() and len(printer.printed) == 1
        release.set()


def test_schedule_save_persistence_and_invalid_save_is_atomic(tmp_path):
    env = tmp_path/'env'; env.write_text('EMAIL_ENABLED=0\nEMAIL_MAILBOX=INBOX\n')
    cfg = Config(data_dir=tmp_path/'data', env_file=env, email_enabled=False)
    service = SettingsService(SettingsRepository(env), cfg)
    _, revision = service.read()
    service.save(dict(revision=revision, PRINT_SCHEDULE_MODE='weekly',
                      PRINT_SCHEDULE_DAYS='sat,tue', PRINT_SCHEDULE_TIME='16:45'))
    fresh = SettingsService(SettingsRepository(env), cfg)
    saved, revision = fresh.read()
    assert saved.print_schedule == PrintSchedule('weekly', ('tue', 'sat'), '16:45')
    before = env.read_bytes()
    with pytest.raises(SettingsError):
        fresh.save(dict(revision=revision, PRINT_SCHEDULE_MODE='weekly', PRINT_SCHEDULE_DAYS=''))
    assert env.read_bytes() == before


def test_new_schedule_preserves_existing_receipts_and_does_not_touch_stats(tmp_path):
    db = Database(tmp_path/'old.db')
    db.set('old_state', {'keep': True})
    with db.connect() as conn:
        conn.execute('DROP TABLE print_queue_releases')
    fresh = Database(db.path)
    assert fresh.get('old_state') == {'keep': True}
    assert fresh.rows('SELECT * FROM print_queue_releases') == []
    root = Path(__file__).resolve().parents[1]
    for name in ('print_schedule.py', 'print_dispatch.py', 'print_queue_repository.py'):
        source = (root/name).read_text(); tree = ast.parse(source)
        imported = {n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        imported |= {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not imported & {'flask', 'server', 'stats_core', 'update_delivery', 'subprocess', 'gmail_client'}
        if name != 'print_queue_repository.py':
            assert '.execute(' not in source and '.connect(' not in source
    assert not (root/'parser.py').exists()


def test_batch_release_and_next_run_roll_back_together(rig, monkeypatch):
    clock, _, db, _, engine = rig
    collect(rig)
    clock[0] = stamp('2026-09-07T09:00')
    repo = engine.dispatch.repository
    original = repo._save
    def broken(conn, state):
        raise RuntimeError('Simulated crash before checkpoint commit')
    monkeypatch.setattr(repo, '_save', broken)
    with pytest.raises(RuntimeError):
        engine.dispatch.release_due()
    assert db.rows('SELECT * FROM print_queue_releases') == []
    assert repo.state()['next_run'] == stamp('2026-09-07T09:00')
    monkeypatch.setattr(repo, '_save', original)
    engine.dispatch.release_due()
    engine.dispatch.release_due()
    assert len(db.rows('SELECT * FROM print_queue_releases')) == 1
    assert repo.state()['next_run'] == stamp('2026-09-09T09:00')
