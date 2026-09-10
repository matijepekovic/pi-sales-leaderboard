"""Opt-in integration test. Queue must be a disposable local CUPS file sink."""
import os
import time
import uuid
from pathlib import Path

import pytest
from pypdf import PdfWriter

from printer_app.config import Config
from printer_app.printer import Printer


@pytest.mark.skipif(os.environ.get('PRINTER_CUPS_INTEGRATION') != '1', reason='Requires isolated CI CUPS sink')
def test_real_cups_hold_receipt_find_release_and_completion(tmp_path):
    pytest.importorskip('cups')
    printer = Printer(Config(data_dir=tmp_path, queue='printer_app_ci'))
    path = tmp_path / 'receipt.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(path)
    token = 'printer-app-ci-' + uuid.uuid4().hex
    assert printer.status()['known']
    jid, result, command = printer.hold(path, token, False)
    assert 'request id is printer_app_ci-' in result
    assert printer.attributes(jid)['job-state'] == 4
    assert printer.find(token)[0]['job-id'] == jid
    assert '-H' in command and 'hold' in command
    printer.release(jid)
    for _ in range(50):
        if printer.attributes(jid)['job-state'] == 9:
            break
        time.sleep(.2)
    assert printer.attributes(jid)['job-state'] == 9
