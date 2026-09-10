import hashlib
from pathlib import Path
import pytest
from reportlab.pdfgen.canvas import Canvas
from werkzeug.security import generate_password_hash
from printer_app.config import Config
from printer_app.contracts import Attachment, Message, Submission
from printer_app.db import migrate
from printer_app.repository import Repository
from printer_app.services import PrintService


def make_pdf(path, pages=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = Canvas(str(path))
    for index in range(pages):
        c.drawString(40, 720, f'Test report page {index + 1}')
        c.showPage()
    c.save()
    return path


class FakePrinter:
    def __init__(self):
        self.calls = []
        self.tokens = {}
        self.outcome = 'COMPLETED'
        self.reject = False
        self.uncertain = False

    def snapshot(self):
        return {'queue': 'konicaa', 'known': True, 'online': True, 'detail': ''}

    def submit(self, path, token, tabloid):
        self.calls.append((Path(path), token, tabloid))
        if self.reject:
            return Submission(detail='queue unavailable')
        if self.uncertain:
            return Submission(detail='timeout', uncertain=True)
        request_id = f'konicaa-{len(self.calls)}'
        self.tokens[token] = request_id
        return Submission(request_id, 'request id is ' + request_id)

    def find(self, token):
        return self.tokens.get(token)

    def state(self, request_id):
        return self.outcome


class FakeRenderer:
    def __init__(self, pages=None, fail=None):
        self.pages = pages or {}
        self.fail = fail

    def render(self, group, directory):
        from openpyxl import Workbook
        directory.mkdir(parents=True, exist_ok=True)
        if group.substatus == self.fail:
            raise RuntimeError('test renderer failure')
        book = Workbook()
        book.active.append(list(group.headers))
        workbook = directory / 'report.xlsx'
        book.save(workbook)
        book.close()
        return workbook, make_pdf(directory / 'report.pdf', self.pages.get(group.substatus, 1))


@pytest.fixture
def setup(tmp_path):
    cfg = Config(data_dir=tmp_path / 'data', ui_password_hash=generate_password_hash('testing-password-123'), session_secret='test-session-secret-' * 4)
    migrate(cfg.database)
    repo = Repository(cfg.database)
    printer = FakePrinter()
    renderer = FakeRenderer()
    service = PrintService(cfg, repo, renderer, printer)
    return cfg, repo, printer, renderer, service


def ingest(repo, path, source='uid-1', message_id='<mail-1>', filename=None):
    a = Attachment(filename or path.name, path, hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size)
    message = Message(source, 'mailbox-scope', source, 'validity-1', message_id, 'Source report', 'sender@example.test', (a,))
    return repo.ingest(message)


def workbook(path, statuses=('Alpha', 'Beta', 'Alpha')):
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(['Report title'])
    sheet.append([])
    sheet.append([None, 'Job', 'Sub Status', 'Amount'])
    for index, status in enumerate(statuses):
        sheet.append([None, f'Row {index}', status, index + 100])
    book.save(path)
    book.close()
    return path
