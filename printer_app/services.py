"""Printing workflow and web-facing control contract. No HTTP, IMAP or SQL here."""
import logging
from pathlib import Path
import time
from .contracts import ConversionError
from .pdfs import page_count
from .error_pages import error_page
from .files import contained, safe_name
from .parser import ParserError, parse

log = logging.getLogger(__name__)


class PrintService:
    def __init__(self, config, repository, renderer, printer, parser=parse):
        self.config, self.repo = config, repository
        self.renderer, self.printer, self.parser = renderer, printer, parser

    def has_error_output(self, job_id):
        return any(o['kind'] == 'ERROR' for o in self.repo.outputs(job_id))

    def error(self, job, kind, reason):
        if self.has_error_output(job['id']):
            return
        self.repo.set_job(job['id'], kind, reason, kind)
        self.repo.step(job['id'], reason)
        log.warning('Job %s: %s', job['id'], reason)
        path = self.config.data_dir / 'outputs' / job['id'] / 'ERROR.pdf'
        error_page(path, job, reason)
        self.repo.add_output(job['id'], 'ERROR', path, 1, printable=True)

    def prepared(self, job):
        return any(o['state'] != 'PREVIEW' for o in self.repo.outputs(job['id']))

    def prepare(self):
        for attachment in self.repo.pending_attachments():
            try:
                self.prepare_attachment(attachment)
                self.repo.finish_attachment(attachment['id'])
            except OSError:
                log.error('Artifact storage unavailable; attachment %s remains pending', attachment['id'])
                raise

    def prepare_attachment(self, attachment):
        path = contained(self.config.data_dir, attachment['path'])
        suffix = Path(attachment['filename']).suffix.lower()
        if suffix == '.pdf':
            job = self.repo.job(attachment, '__file__')
            if self.prepared(job):
                return
            try:
                pages = page_count(path)
                self.repo.set_job(job['id'], 'READY', page_count=pages)
                self.repo.step(job['id'], f'Incoming PDF: {pages} page(s), printing directly without the Excel page limit')
                self.repo.add_output(job['id'], 'REPORT', path, pages, printable=True)
            except Exception as exc:
                reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                self.error(job, 'CONVERSION ERROR', 'PDF PREFLIGHT FAILED: ' + reason)
            return
        if suffix not in {'.xlsx', '.xls', '.xlsm'}:
            job = self.repo.job(attachment, '__file__')
            if not self.prepared(job):
                self.error(job, 'PARSER ERROR', 'UNSUPPORTED ATTACHMENT TYPE')
            return
        try:
            groups = self.parser(path)
        except Exception as exc:
            job = self.repo.job(attachment, '__file__')
            if not self.prepared(job):
                reason = str(exc) if isinstance(exc, ParserError) else 'EXCEL PARSER FAILED: ' + type(exc).__name__
                self.error(job, 'PARSER ERROR', reason)
            return
        for group in groups:
            job = self.repo.job(attachment, group.key, group.substatus)
            if self.prepared(job):
                continue
            self.repo.step(job['id'], f'Main table: {group.sheet}; {len(group.rows)} rows; Sub Status: {group.substatus}')
            try:
                workbook, pdf = self.renderer.render(group, self.config.data_dir / 'outputs' / job['id'])
                self.repo.add_output(job['id'], 'WORKBOOK', workbook, None)
                pages = page_count(pdf)
                self.repo.set_job(job['id'], 'READY', page_count=pages)
                self.repo.step(job['id'], f'PDF preflight: {pages} page(s)')
                self.repo.add_output(job['id'], 'REPORT', pdf, pages, printable=pages == 1, tabloid=True)
                if pages != 1:
                    self.error(job, 'CONVERSION ERROR', f'REPORT RENDERED TO {pages} PAGES')
            except Exception as exc:
                reason = str(exc) if isinstance(exc, ConversionError) else 'EXCEL CONVERSION FAILED: ' + type(exc).__name__
                self.error(job, 'CONVERSION ERROR', reason)

    def test_print(self, command_id):
        job = self.repo.job({'id': None, 'filename': 'test-print.pdf', 'subject': 'Local test print', 'sender': 'Print Control'}, 'test', job_id=command_id)
        if not self.prepared(job):
            path = self.config.data_dir / 'outputs' / job['id'] / 'test-print.pdf'
            error_page(path, job, 'Printer automation test. Queue: ' + self.config.queue, title='TEST PRINT')
            self.repo.add_output(job['id'], 'REPORT', path, 1, printable=True)
            self.repo.step(job['id'], 'Test print requested from authenticated control UI')

    def printer_failure(self, output, reason):
        self.repo.put('last_printer_error', {'at': time.time(), 'reason': reason})
        if output['kind'] == 'ERROR':
            self.repo.set_job(output['job_id'], 'PRINTER ERROR', reason)
            self.repo.step(output['job_id'], reason)
            self.repo.set_output(output['id'], 'RETRY', delay=60)
        else:
            # Make the fallback durable before removing the failed report from recovery.
            self.error(self.repo.detail(output['job_id']), 'PRINTER ERROR', reason)
            self.repo.set_output(output['id'], 'FAILED')

    def uncertain(self, output, attempt, reason):
        if output['kind'] == 'REPORT' and self.has_error_output(output['job_id']):
            return
        self.repo.set_job(output['job_id'], 'PRINTER ERROR', reason)
        self.repo.put('last_printer_error', {'at': time.time(), 'reason': reason})
        if output['kind'] == 'REPORT' and time.time() - attempt['started'] >= 60:
            # Do not repeat the original report. Print a diagnostic after allowing
            # CUPS time to make an interrupted submission visible in its history.
            self.error(self.repo.detail(output['job_id']), 'PRINTER ERROR', reason)

    def dispatch(self, allow_new=True):
        for output in self.repo.outputs():
            try:
                self.dispatch_output(output, allow_new)
            except Exception as exc:
                self.repo.put('last_printer_error', {'at': time.time(), 'reason': 'CUPS communication failed: ' + type(exc).__name__})
                log.warning('CUPS operation failed for output %s: %s', output['id'], type(exc).__name__)

    def dispatch_output(self, output, allow_new):
        state = output['state']
        fallback_exists = output['kind'] == 'REPORT' and self.has_error_output(output['job_id'])
        if state in {'SUBMITTING', 'UNCERTAIN'}:
            attempt = self.repo.latest_attempt(output['id'])
            if attempt is None:
                raise RuntimeError('Missing durable print attempt')
            if attempt['state'] == 'FAILED':
                self.printer_failure(output, 'PRINTER SUBMISSION FAILED: ' + attempt['detail'])
                return
            found = self.printer.find(attempt['token'])
            if found:
                self.repo.set_output(output['id'], 'SUBMITTED', found)
                self.repo.finish_attempt(attempt['id'], 'SUBMITTED', found, 'Recovered by unique CUPS job title')
                if not fallback_exists:
                    self.repo.set_job(output['job_id'], 'SUBMITTED')
            else:
                self.repo.set_output(output['id'], 'UNCERTAIN')
                self.uncertain(output, attempt, 'PRINTER SUBMISSION OUTCOME UNKNOWN; the original report will not be submitted again')
            return
        if state == 'SUBMITTED':
            outcome = self.printer.state(output['request_id'])
            if outcome == 'COMPLETED':
                self.repo.set_output(output['id'], 'COMPLETED')
                result = 'ERROR PRINTED' if output['kind'] == 'ERROR' else 'PRINTED'
                if not fallback_exists:
                    self.repo.set_job(output['job_id'], result)
                self.repo.put('last_successful_print', {'at': time.time(), 'request_id': output['request_id'], 'result': result})
                self.repo.step(output['job_id'], 'CUPS reports job completed: ' + output['request_id'])
            elif outcome == 'FAILED':
                self.printer_failure(output, 'PRINTER JOB CANCELED OR ABORTED: ' + output['request_id'])
            elif outcome == 'UNKNOWN':
                attempt = self.repo.latest_attempt(output['id'])
                if attempt:
                    self.uncertain(output, attempt, 'CUPS JOB STATE UNAVAILABLE; the original report will not be submitted again')
            return
        if not allow_new or output['retry_at'] > time.time():
            return
        attempt_id, token = self.repo.begin_attempt(output['id'])
        self.repo.step(output['job_id'], 'Submitting ' + output['kind'] + ' to CUPS; token=' + token)
        log.info('Print submission output=%s kind=%s token=%s', output['id'], output['kind'], token)
        result = self.printer.submit(contained(self.config.data_dir, output['path']), token, bool(output['tabloid']))
        if result.request_id:
            self.repo.finish_attempt(attempt_id, 'SUBMITTED', result.request_id, result.detail)
            self.repo.set_output(output['id'], 'SUBMITTED', result.request_id)
            self.repo.set_job(output['job_id'], 'SUBMITTED')
        elif result.uncertain:
            self.repo.finish_attempt(attempt_id, 'UNCERTAIN', '', result.detail)
            self.repo.set_output(output['id'], 'UNCERTAIN')
        else:
            self.repo.finish_attempt(attempt_id, 'FAILED', '', result.detail)
            self.printer_failure(output, 'PRINTER SUBMISSION FAILED: ' + result.detail)


class ControlService:
    """The web layer sees monitoring and command operations, not worker internals."""
    def __init__(self, config, repository):
        self.config, self.repo = config, repository

    def health(self):
        try:
            database = self.repo.healthy()
            heartbeat = self.repo.get('heartbeat', 0)
            worker = time.time() - heartbeat < 30
            known = self.repo.get('printer', {}).get('known', False)
        except Exception:
            database, worker, known = False, False, False
        return {'web_alive': True, 'database_accessible': database, 'worker_running': worker, 'cups_queue_known': known}

    def status(self):
        return {'health': self.health(), 'printer': self.repo.get('printer', {'queue': self.config.queue, 'known': False, 'online': False}),
                'monitor': self.repo.get('monitor', {'state': 'starting'}), 'paused': self.repo.get('paused', False),
                'last_successful_print': self.repo.get('last_successful_print'), 'last_printer_error': self.repo.get('last_printer_error')}

    def command(self, action):
        if action in {'pause', 'resume'}:
            self.repo.put('paused', action == 'pause')
        elif action in {'run', 'test'}:
            self.repo.command(action)
        else:
            raise ValueError('Unknown control action')

    def recent(self):
        return self.repo.recent()

    def detail(self, job_id):
        return self.repo.detail(job_id)

    def artifact(self, output_id):
        output = self.repo.output(output_id)
        if output is None:
            return None
        path = contained(self.config.data_dir, output['path'])
        job = self.repo.detail(output['job_id'])
        suffix = '.xlsx' if output['kind'] == 'WORKBOOK' else '.pdf'
        name = safe_name(job['substatus'] or Path(job['filename']).stem)
        if output['kind'] == 'ERROR':
            name += '-ERROR'
        return path, name + suffix
