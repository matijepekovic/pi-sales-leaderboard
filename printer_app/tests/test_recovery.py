"""Regression tests for real headless conversion, isolation and interrupted print delivery."""
import ast
from dataclasses import replace
import signal
import subprocess
import sys
import time
from pathlib import Path
import pytest
from reportlab.pdfbase import pdfmetrics
from printer_app.bootstrap import build_web
from printer_app.converter import run_conversion
from printer_app.error_pages import error_page, wrapped_lines
from printer_app.pdfs import page_count
from printer_app.processes import safe_environment
from printer_app.worker import Worker
from .conftest import ingest, make_pdf


def test_renderer_and_cups_adapters_can_be_replaced_independently():
    package = Path(__file__).resolve().parents[1]
    for name in ('printer.py', 'error_pages.py', 'services.py', 'web.py', 'worker.py', 'pdfs.py'):
        imports = [node.module for node in ast.walk(ast.parse((package / name).read_text())) if isinstance(node, ast.ImportFrom)]
        assert 'converter' not in imports, name
    code = 'import sys; import printer_app.printer; import printer_app.error_pages; assert "printer_app.converter" not in sys.modules'
    subprocess.run([sys.executable, '-c', code], cwd=package.parent, check=True, timeout=20)


def test_child_environment_excludes_all_application_secrets(monkeypatch):
    for key in ('EMAIL_APP_PASSWORD', 'SESSION_SECRET', 'UI_PASSWORD_HASH', 'CUPS_PASSWORD'):
        monkeypatch.setenv(key, 'private-secret')
        assert key not in safe_environment()


def test_real_process_group_timeout_reaps_children(tmp_path):
    marker = tmp_path / 'orphan-marker'
    child = f'import time; from pathlib import Path; time.sleep(1.2); Path({str(marker)!r}).write_text("orphan")'
    parent = f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(60)'
    with pytest.raises(subprocess.TimeoutExpired):
        run_conversion([sys.executable, '-c', parent], timeout=.3)
    time.sleep(1.3)
    assert not marker.exists()


def test_error_page_wide_text_stays_in_one_page_and_in_bounds(tmp_path):
    for text in ('W' * 1000, 'Long filename with spaces ' * 100, '<script>unsafe</script>' * 100):
        lines = wrapped_lines(text, 'Helvetica', maximum=3)
        assert len(lines) <= 3
        assert all(pdfmetrics.stringWidth(line, 'Helvetica', 12) <= 528 for line in lines)
    job = dict(id='a' * 32, filename='W' * 1000, subject='W' * 1000, sender='W' * 1000, substatus='W' * 1000)
    path = tmp_path / 'error.pdf'
    error_page(path, job, 'W' * 2000)
    assert page_count(path) == 1


def test_unicode_csrf_is_rejected_not_server_error(setup):
    config, *_ = setup
    client = build_web(config).test_client()
    client.get('/login')
    assert client.post('/control/test', data={'csrf': 'wrong-ž漢字'}).status_code == 400


def test_pause_only_stops_new_mail_not_downloaded_jobs(setup):
    config, repo, printer, _, service = setup
    ingest(repo, make_pdf(config.data_dir / 'already-downloaded.pdf'))
    repo.put('paused', True)
    class Mail:
        def messages(self, seen):
            pytest.fail('Paused monitor must not poll new mail')
    worker = Worker(config, repo, Mail(), service)
    worker.tick()
    worker.tick()
    assert len(printer.calls) == 1
    assert repo.recent()[0]['state'] == 'PRINTED'


def test_uncertain_report_automatically_gets_one_error_not_a_duplicate_report(setup, monkeypatch):
    config, repo, printer, _, service = setup
    ingest(repo, make_pdf(config.data_dir / 'input.pdf'))
    service.prepare()
    printer.uncertain = True
    service.dispatch()
    output = repo.outputs()[0]
    started = repo.latest_attempt(output['id'])['started']
    printer.uncertain = False
    monkeypatch.setattr(time, 'time', lambda: started + 61)
    for _ in range(5):
        service.dispatch()
    assert len(printer.calls) == 2
    assert printer.calls[0][0].name == 'input.pdf'
    assert printer.calls[1][0].name == 'ERROR.pdf'
    assert repo.recent()[0]['state'] == 'ERROR PRINTED'
    assert repo.output(output['id'])['state'] == 'UNCERTAIN'


def test_rejected_report_recovers_crash_before_fallback_creation(setup):
    config, repo, printer, _, service = setup
    ingest(repo, make_pdf(config.data_dir / 'input.pdf'))
    service.prepare()
    output = repo.outputs()[0]
    attempt, _ = repo.begin_attempt(output['id'])
    repo.finish_attempt(attempt, 'FAILED', '', 'known rejection')
    # Simulate power loss after recording rejection and before creating its error PDF.
    for _ in range(3):
        service.dispatch()
    assert len(printer.calls) == 1
    assert printer.calls[0][0].name == 'ERROR.pdf'
    assert repo.recent()[0]['state'] == 'ERROR PRINTED'


def test_low_disk_defers_mail_without_acknowledging(tmp_path):
    from printer_app.files import check_disk
    with pytest.raises(OSError, match='remains unprocessed'):
        check_disk(tmp_path, reserve_mb=10**12)
