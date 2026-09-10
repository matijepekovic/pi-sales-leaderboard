"""CUPS adapter. Keep existing driver, account tracking and queue configuration intact."""
import re
import subprocess
from .contracts import Submission
from .processes import safe_environment


class CupsPrinter:
    def __init__(self, queue, connection_factory=None, runner=subprocess.run):
        if connection_factory is None:
            import cups
            connection_factory = cups.Connection
        self.connection_factory = connection_factory
        self.runner = runner
        self.queue = queue

    def snapshot(self):
        printers = self.connection_factory().getPrinters()
        info = printers.get(self.queue)
        if info is None:
            return {'queue': self.queue, 'known': False, 'online': False, 'detail': 'CUPS queue is not configured'}
        reasons = info.get('printer-state-reasons', [])
        offline = info.get('printer-state') == 5 or any('offline' in r or 'connecting-to-device' in r for r in reasons)
        return {'queue': self.queue, 'known': True, 'online': not offline,
                'detail': str(info.get('printer-state-message', ''))[:500], 'reasons': reasons}

    def submit(self, path, token, tabloid=False):
        args = ['lp', '-d', self.queue, '-t', token]
        if tabloid:
            args += ['-o', 'media=Tabloid', '-o', 'sides=one-sided']
        args.append(str(path.resolve()))
        try:
            result = self.runner(args, capture_output=True, text=True, timeout=30, env=safe_environment(), check=False)
        except subprocess.TimeoutExpired:
            return Submission(detail='lp timed out; submission outcome is uncertain', uncertain=True)
        except OSError as exc:
            return Submission(detail='lp could not be started: ' + type(exc).__name__)
        detail = (result.stdout + '\n' + result.stderr).strip()[:4000]
        match = re.search(r'request id is (' + re.escape(self.queue) + r'-\d+)', result.stdout)
        if match:
            return Submission(match.group(1), detail)
        return Submission(detail=detail or f'lp exited with code {result.returncode}', uncertain=result.returncode == 0)

    def find(self, token):
        jobs = self.connection_factory().getJobs(which_jobs='all', my_jobs=True,
            requested_attributes=['job-id', 'job-name', 'job-printer-uri'])
        for job_id, attrs in jobs.items():
            if attrs.get('job-name') == token and str(attrs.get('job-printer-uri', '')).rstrip('/').endswith('/' + self.queue):
                return f'{self.queue}-{job_id}'
        return None

    def state(self, request_id):
        if not re.fullmatch(re.escape(self.queue) + r'-\d+', request_id):
            return 'UNKNOWN'
        try:
            attrs = self.connection_factory().getJobAttributes(int(request_id.rsplit('-', 1)[1]))
        except Exception:
            return 'UNKNOWN'
        state = attrs.get('job-state')
        return 'COMPLETED' if state == 9 else 'FAILED' if state in (7, 8) else 'WAITING'
