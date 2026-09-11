"""Use the existing queue unchanged. Held submissions close the crash/reprint window."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .config import Config, clean_text
from .print_options import PrintOptions


class PrinterError(RuntimeError):
    pass


class SubmissionRejected(PrinterError):
    pass


class MissingJob(PrinterError):
    pass


class Printer:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def connection(self):
        import cups
        return cups.Connection()

    def status(self) -> dict:
        try:
            printers = self.connection().getPrinters()
            p = printers.get(self.cfg.queue)
            if p is None:
                return {'known': False, 'online': False, 'detail': 'QUEUE NOT FOUND'}
            reasons = p.get('printer-state-reasons', [])
            stopped = int(p.get('printer-state', 5)) == 5
            offline = any('offline' in x or 'connecting-to-device' in x for x in reasons)
            return {'known': True, 'online': not stopped and not offline,
                    'accepting': bool(p.get('printer-is-accepting-jobs', False)),
                    'detail': clean_text(p.get('printer-state-message', '') or ', '.join(reasons))}
        except Exception:
            return {'known': False, 'online': False, 'detail': 'CUPS CONNECTION FAILED'}

    def find(self, token: str) -> list[dict]:
        try:
            jobs = self.connection().getJobs(which_jobs='all', my_jobs=True,
                requested_attributes=['job-id', 'job-name', 'job-state', 'job-printer-uri'])
            return [dict(item, **{'job-id': int(number)}) for number, item in jobs.items()
                    if item.get('job-name') == token
                    and item.get('job-printer-uri', '').rstrip('/').endswith('/' + self.cfg.queue)]
        except Exception as exc:
            raise PrinterError('CUPS JOB LOOKUP FAILED') from exc

    def attributes(self, job_id: int) -> dict:
        import cups
        try:
            return self.connection().getJobAttributes(job_id)
        except cups.IPPError as exc:
            if exc.args and exc.args[0] == cups.IPP_NOT_FOUND:
                raise MissingJob('CUPS JOB HISTORY IS UNAVAILABLE') from exc
            raise PrinterError('CUPS JOB STATUS FAILED') from exc
        except Exception as exc:
            raise PrinterError('CUPS CONNECTION FAILED') from exc

    def run(self, command: list[str]) -> str:
        env = {k: v for k, v in os.environ.items()
               if k in ('PATH', 'HOME', 'USER', 'LOGNAME', 'CUPS_SERVER', 'XDG_CONFIG_HOME')}
        env.update(LANG='C', LC_ALL='C')
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PrinterError('PRINTER SUBMISSION FAILED: ' + type(exc).__name__) from exc
        text = clean_text((result.stdout + '\n' + result.stderr).strip(), 2000)
        if result.returncode:
            raise SubmissionRejected('PRINTER SUBMISSION FAILED: ' + text)
        return text

    def hold(self, path: Path, token: str, options: PrintOptions, *, received_pdf=False) -> tuple[int, str, list[str]]:
        # No print can occur until the receipt is persisted and the worker releases it.
        command = ['lp', '-d', self.cfg.queue, '-n', str(options.copies), '-t', token, '-H', 'hold']
        if options.paper != 'source':
            paper = {'tabloid': 'Tabloid', 'letter': 'Letter', 'legal': 'Legal', 'a4': 'A4', 'a3': 'A3'}[options.paper]
            command += ['-o', 'media=' + paper]
        if options.orientation != 'source':
            command += ['-o', 'orientation-requested=' + ('4' if options.orientation == 'landscape' else '3')]
        if options.color != 'default':
            command += ['-o', 'print-color-mode=' + options.color]
        if options.sides != 'default':
            command += ['-o', 'sides=' + options.sides]
        if received_pdf and options.pdf_scaling != 'default':
            command += ['-o', 'print-scaling=' + ('fit' if options.pdf_scaling == 'fit' else 'none'),
                        '-o', 'fit-to-page=' + ('true' if options.pdf_scaling == 'fit' else 'false')]

        command += ['--', str(path.resolve())]
        result = self.run(command)
        match = re.search(r'request id is ' + re.escape(self.cfg.queue) + r'-(\d+)\b', result)
        if not match:
            raise PrinterError('CUPS ACCEPTANCE RECEIPT NOT UNDERSTOOD; WILL RECONCILE HELD JOB')
        return int(match.group(1)), result, command

    def release(self, job_id: int) -> str:
        return self.run(['lp', '-i', f'{self.cfg.queue}-{job_id}', '-H', 'resume'])

    def cancel_held_duplicate(self, job_id: int) -> None:
        self.connection().cancelJob(job_id)
