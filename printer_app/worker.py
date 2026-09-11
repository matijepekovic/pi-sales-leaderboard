"""The only Gmail scheduler and print submitter. Web requests only enqueue commands."""
from __future__ import annotations

import fcntl
import json
import logging
import signal
import threading
import time
import uuid
from pathlib import Path

from . import converter
from .print_options import PrintOptions
from dataclasses import replace
from .config import Config, clean_text, environment_file
from .settings import SettingsService, SettingsError
from .settings_repository import SettingsRepository, SettingsStorageError
from .db import Database
from .error_pages import error_page
from .gmail_client import GmailClient
from .printer import MissingJob, Printer, PrinterError, SubmissionRejected

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, cfg: Config, db: Database, printer=None, stop=None):
        self.cfg, self.db = cfg, db
        self.printer = printer or Printer(cfg)
        self.stop = stop or threading.Event()

    def make_job(self, attachment_id, key: str) -> dict:
        jid = self.db.create_job(attachment_id, key, self.cfg.print_options.snapshot())
        return self.db.job(jid)

    def job_options(self, job: dict) -> PrintOptions:
        snapshot = self.db.job_print_settings(job['id'])
        if snapshot is not None:
            return PrintOptions(**snapshot)
        # Pending jobs from older releases keep their old physical print choices.
        return PrintOptions(paper='tabloid' if job['tabloid'] else 'source')

    def directory(self, job_id: int) -> Path:
        path = self.cfg.data_dir / 'jobs' / str(job_id)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def fail(self, job_id: int, kind: str, reason: str) -> None:
        job = self.db.job(job_id)
        reason = clean_text(reason, 4000)
        target = error_page(self.directory(job_id) / 'error.pdf', job, reason, self.cfg.timezone)
        if converter.page_count(target) != 1:
            raise RuntimeError('Error sheet must contain exactly one page')
        self.db.output(job_id, 'Physical error sheet', target)
        self.db.execute('''UPDATE jobs SET printable=?,is_error=1,tabloid=0,failure_kind=?,error=?,
          status='READY',next_attempt=0,updated=? WHERE id=?''', (str(target), kind, reason, time.time(), job_id))
        self.db.step(job_id, f'{kind}: {reason}; one-page error sheet prepared')
        log.warning('Job %s: %s: %s', job_id, kind, reason)

    def ready(self, job_id: int, pdf: Path, pages: int, tabloid: bool) -> None:
        self.db.output(job_id, 'Report PDF', pdf)
        self.db.execute('''UPDATE jobs SET printable=?,page_count=?,tabloid=?,status='READY',updated=?
            WHERE id=?''', (str(pdf), pages, int(tabloid), time.time(), job_id))
        self.db.step(job_id, f'PDF preflight: {pages} page(s); ready for automatic printing')

    def process_attachment(self, attachment: dict) -> None:
        aid = attachment['id']
        current = self.db.one('SELECT state FROM attachments WHERE id=?', (aid,))
        if not current or current['state'] == 'DONE':
            return
        self.db.execute("UPDATE attachments SET state='PROCESSING' WHERE id=?", (aid,))
        source = Path(attachment['path']) if attachment['path'] else None
        suffix = Path(attachment['filename']).suffix.lower()
        existing = self.db.rows('SELECT * FROM jobs WHERE attachment_id=?', (aid,))
        # An upgrade must not add a full-workbook print to old, partly submitted
        # split jobs. Retain their receipts; unfinished preparation gets a diagnostic.
        if suffix in ('.xlsx', '.xls', '.xlsm') and existing and any(j['group_key'] != 'workbook' for j in existing):
            for job in existing:
                if job['status'] == 'PREPARING':
                    self.fail(job['id'], 'CONVERSION ERROR',
                              'LEGACY REPORT INTERRUPTED BY UPDATE; ORIGINAL NOT AUTOMATICALLY REPRINTED')
        else:
            key = 'pdf' if suffix == '.pdf' else 'workbook'
            job = self.make_job(aid, key)
            if job['status'] == 'PREPARING':
                options = self.job_options(job)
                self.db.step(job['id'], 'Saved print settings: ' + json.dumps(options.snapshot(), sort_keys=True))
                try:
                    if attachment['error']:
                        raise converter.ConversionError(attachment['error'])
                    if suffix == '.pdf':
                        pages = converter.page_count(source)
                        self.ready(job['id'], source, pages, False)
                        self.db.step(job['id'], 'Incoming PDF: original bytes retained; no page-limit rule')
                    elif suffix in ('.xlsx', '.xls', '.xlsm'):
                        self.db.step(job['id'], 'Original workbook rendering; no header detection, row splitting or restyling')
                        pdf = converter.convert(source, self.directory(job['id']), replace(self.cfg, print_options=options))
                        pages = converter.page_count(pdf)
                        self.db.output(job['id'], 'Original-layout report PDF', pdf)
                        self.db.execute('UPDATE jobs SET page_count=? WHERE id=?', (pages, job['id']))
                        self.db.step(job['id'], f'LibreOffice conversion completed; actual PDF pages={pages}')
                        if options.page_policy == 'one-page' and pages != 1:
                            self.fail(job['id'], 'CONVERSION ERROR', f'REPORT RENDERED TO {pages} PAGES; ONE-PAGE RULE ENABLED')
                        else:
                            self.ready(job['id'], pdf, pages, False)
                    else:
                        raise converter.ConversionError('UNSUPPORTED ATTACHMENT TYPE')
                except Exception as exc:
                    self.fail(job['id'], 'CONVERSION ERROR', str(exc) or type(exc).__name__)
        self.db.execute("UPDATE attachments SET state='DONE' WHERE id=?", (aid,))

    def printer_problem(self, job_id: int, reason: str) -> None:
        reason = clean_text(reason, 2000)
        self.db.set('last_printer_error', {'at': time.time(), 'message': reason})
        self.db.execute("UPDATE jobs SET status='PRINTER ERROR',next_attempt=?,updated=? WHERE id=?",
                        (time.time() + self.cfg.retry_seconds, time.time(), job_id))
        self.db.step(job_id, reason + '; automatic retry/reconciliation scheduled')
        log.warning('Job %s: %s', job_id, reason)

    def advance(self, job: dict) -> None:
        jid = job['id']
        attempt = self.db.one('SELECT * FROM print_attempts WHERE job_id=? ORDER BY id DESC LIMIT 1', (jid,))
        if not attempt or attempt['state'] in ('FAILED', 'UNKNOWN'):
            token = 'printer-app-' + uuid.uuid4().hex
            now = time.time()
            aid = self.db.execute('INSERT INTO print_attempts(job_id,token,created,updated) VALUES (?,?,?,?)',
                                  (jid, token, now, now))
            attempt = self.db.one('SELECT * FROM print_attempts WHERE id=?', (aid,))
        if attempt['state'] == 'COMPLETE':
            return
        aid = attempt['id']
        try:
            if not attempt['cups_id']:
                matches = self.printer.find(attempt['token'])
                if matches:
                    chosen = min(matches, key=lambda item: item['job-id'])
                    cups_id = chosen['job-id']
                    for other in matches:
                        if other['job-id'] != cups_id and other.get('job-state') == 4:
                            self.printer.cancel_held_duplicate(other['job-id'])
                    result, command = 'Recovered held CUPS receipt by unique job title', []
                else:
                    self.db.step(jid, 'Submitting held document to CUPS; no physical printing before durable receipt')
                    try:
                        cups_id, result, command = self.printer.hold(Path(job['printable']), attempt['token'],
                            self.job_options(job).error_sheet() if job['is_error'] else self.job_options(job),
                            received_pdf=bool(job['is_error']) or job['group_key'] == 'pdf')
                    except SubmissionRejected as exc:
                        self.db.execute("UPDATE print_attempts SET state='FAILED',result=?,updated=? WHERE id=?",
                                        (str(exc), time.time(), aid))
                        if not job['is_error']:
                            self.fail(jid, 'PRINTER ERROR', str(exc))
                        self.printer_problem(jid, str(exc))
                        return
                # This transaction completes BEFORE any release command can execute.
                self.db.execute('''UPDATE print_attempts SET cups_id=?,request_id=?,state='HELD',
                    result=?,command=?,updated=? WHERE id=?''',
                    (cups_id, f'{self.cfg.queue}-{cups_id}', result, json.dumps(command), time.time(), aid))
                self.db.step(jid, f'CUPS receipt persisted: {self.cfg.queue}-{cups_id}; {result}')
                attempt['cups_id'] = cups_id
            attrs = self.printer.attributes(attempt['cups_id'])
            state = int(attrs['job-state'])
            if state == 4:
                self.db.execute("UPDATE print_attempts SET state='RELEASING',updated=? WHERE id=?", (time.time(), aid))
                result = self.printer.release(attempt['cups_id'])
                self.db.execute("UPDATE print_attempts SET state='RELEASED',result=result || ?,updated=? WHERE id=?",
                                ('\nRelease: ' + result, time.time(), aid))
                self.db.step(jid, 'Held document released for automatic printing')
            elif state == 9:
                outcome = 'ERROR PRINTED' if job['is_error'] else 'PRINTED'
                now = time.time()
                with self.db.connect() as conn:
                    conn.execute("UPDATE print_attempts SET state='COMPLETE',updated=? WHERE id=?", (now, aid))
                    conn.execute('UPDATE jobs SET status=?,completed=?,updated=? WHERE id=?', (outcome, now, now, jid))
                self.db.set('last_successful_print', now)
                self.db.step(jid, f'{outcome}: CUPS reported job-completed (not an independent paper sensor)')
                log.info('Job %s: %s', jid, outcome)
                return
            elif state in (7, 8):
                reason = 'CUPS JOB CANCELLED' if state == 7 else 'CUPS JOB ABORTED'
                self.db.execute("UPDATE print_attempts SET state='FAILED',result=result || ?,updated=? WHERE id=?",
                                ('\n' + reason, time.time(), aid))
                if not job['is_error']:
                    self.fail(jid, 'PRINTER ERROR', reason + '; ORIGINAL WILL NOT BE RESUBMITTED')
                self.printer_problem(jid, reason)
                return
            elif state == 6:
                self.printer_problem(jid, 'CUPS JOB STOPPED; RETAINING EXISTING REQUEST, NOT RESUBMITTING')
                return
            self.db.execute("UPDATE jobs SET status='SUBMITTED',next_attempt=?,updated=? WHERE id=?",
                            (time.time() + 5, time.time(), jid))
        except MissingJob as exc:
            self.db.execute("UPDATE print_attempts SET state='UNKNOWN',result=?,updated=? WHERE id=?",
                            (str(exc), time.time(), aid))
            reason = 'PRINT OUTCOME UNKNOWN: CUPS HISTORY LOST; ORIGINAL NOT RESUBMITTED'
            if job['is_error']:
                self.db.execute("UPDATE jobs SET status='PRINT UNKNOWN',error=error || ?,updated=? WHERE id=?",
                                ('; ' + reason, time.time(), jid))
                self.db.step(jid, reason + '; error sheet is also not blindly duplicated')
            else:
                self.fail(jid, 'PRINTER ERROR', reason)
            self.db.set('last_printer_error', {'at': time.time(), 'message': reason})
        except PrinterError as exc:
            self.printer_problem(jid, str(exc))

    def test_print(self) -> None:
        jid = self.db.create_job(None, 'test-' + uuid.uuid4().hex, self.cfg.print_options.snapshot())
        job = self.db.job(jid)
        pdf = error_page(self.directory(jid) / 'test.pdf', job, 'Printer app is operating independently.', self.cfg.timezone, test=True)
        self.ready(jid, pdf, converter.page_count(pdf), False)

    def tick(self) -> None:
        attachment = self.db.one("SELECT * FROM attachments WHERE state IN ('PENDING','PROCESSING') ORDER BY id LIMIT 1")
        if attachment and not self.stop.is_set():
            self.process_attachment(attachment)
        for job in self.db.rows("SELECT * FROM jobs WHERE status IN ('READY','SUBMITTED','PRINTER ERROR') AND next_attempt<=? ORDER BY id LIMIT 20", (time.time(),)):
            if self.stop.is_set():
                break
            self.advance(job)


class RedactingFormatter(logging.Formatter):
    def __init__(self, cfg):
        super().__init__('%(asctime)s %(levelname)s %(name)s %(message)s')
        self.secrets = ()
        self.update(cfg)

    def update(self, cfg):
        values = set(self.secrets) | {s for s in (cfg.email_password, cfg.secret_key, cfg.password_hash) if s}
        self.secrets = tuple(sorted(values, key=len, reverse=True))

    def format(self, record):
        text = super().format(record)
        for secret in self.secrets:
            text = text.replace(secret, '[REDACTED]')
        return text


def main():
    cfg = Config.from_env()
    handler = logging.StreamHandler()
    formatter = RedactingFormatter(cfg)
    handler.setFormatter(formatter)
    settings = SettingsService(SettingsRepository(cfg.env_file or environment_file()), cfg)
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    db = Database(cfg.db_path)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    # Kernel lock survives until process exit; a second worker cannot double-print.
    with (cfg.data_dir / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        engine = Engine(cfg, db, stop=stop)
        gmail = GmailClient(cfg, db, stop=stop)

        def heartbeat():
            while not stop.is_set():
                try:
                    db.set('worker_heartbeat', time.time())
                except Exception:
                    log.exception('Heartbeat database error')
                stop.wait(5)
        thread = threading.Thread(target=heartbeat, daemon=True, name='printer-heartbeat')
        thread.start()
        next_poll, next_status = 0, 0
        active_revision = None
        log.info('Independent printer worker started, queue=%s', cfg.queue)
        try:
            while not stop.is_set():
                try:
                    now = time.time()
                    # Apply only between operations: never interrupt a workbook or
                    # an in-flight CUPS transaction. Queue/path identity is immutable.
                    try:
                        updated, revision = settings.read()
                        if revision != active_revision:
                            if updated != cfg:
                                cfg = updated
                                formatter.update(cfg)
                                engine = Engine(cfg, db, stop=stop)
                                gmail = GmailClient(cfg, db, stop=stop)
                                next_poll, next_status = 0, 0
                            active_revision = revision
                            db.set('settings_revision', revision)
                            log.info('Printer settings applied')
                        db.set('settings_error', '')
                    except (SettingsError, SettingsStorageError):
                        db.set('settings_error', 'Could not load new settings; previous settings remain active.')
                    if now >= next_status:
                        status = engine.printer.status()
                        db.set('printer_status', status)
                        if not status['online']:
                            db.set('last_printer_error', {'at': now, 'message': status['detail'] or 'PRINTER OFFLINE'})
                        next_status = now + 15
                    with db.connect() as conn:
                        commands = list(conn.execute('SELECT * FROM commands ORDER BY id'))
                        conn.execute('DELETE FROM commands')
                    force = any(row['name'] == 'run-now' for row in commands)
                    for row in commands:
                        if row['name'] == 'test-print':
                            engine.test_print()
                    paused = db.get('paused', False)
                    if not cfg.email_enabled:
                        db.set('gmail_state', 'DISABLED')
                        db.set('next_check', None)
                    elif not paused or force:
                        if now >= next_poll or force:
                            db.set('last_check', now)
                            try:
                                found = gmail.poll()
                                db.set('monitor_error', '')
                                log.info('Inbox poll complete: %s new message(s)', found)
                            except Exception as exc:
                                # IMAP errors never terminate the worker or reveal login secrets.
                                db.set('gmail_state', 'ERROR')
                                db.set('monitor_error', 'GMAIL CHECK FAILED: ' + type(exc).__name__)
                                log.warning('Gmail check failed: %s', type(exc).__name__)
                            next_poll = time.time() + cfg.poll_seconds
                            db.set('next_check', next_poll)
                    engine.tick()
                    stop.wait(1)
                except Exception:
                    log.exception('Worker cycle failed; will retry without abandoning durable jobs')
                    db.set('monitor_error', 'WORKER CYCLE ERROR; SEE PRINTER WORKER LOG')
                    stop.wait(5)
        finally:
            stop.set()
            thread.join(timeout=10)
            db.set('worker_heartbeat', 0)
            log.info('Printer worker stopped')


if __name__ == '__main__':
    main()
