"""Focused invariant: one gallery PDF owns one document date."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from printer_app.gallery import recognition


@pytest.mark.parametrize(('printed', 'expected'), [
    ('9/21/2026 8:00 AM', '2026-09-21'),
    ('09/21/2026 10:30 AM', '2026-09-21'),
    ('2/29/2024', '2024-02-29'),
])
def test_month_first_appointment_dates_are_normalized(printed, expected):
    assert recognition._date_readings(printed) == [expected]


@pytest.mark.parametrize('printed', ['2/29/2026', '2/30/2026', '13/21/2026', '9/32/2026'])
def test_invalid_month_first_dates_are_not_readings(printed):
    assert recognition._date_readings(printed) == []


@pytest.mark.parametrize(('local', 'scheduled', 'expected'), [
    ('9/21/2026 8:00 AM', '2026.09.21 ; 08:00:00 AM', ('2026-09-21', 'printed')),
    ('09/21/2026 8:00 AM', '9/21/2026 08:00 AM', ('2026-09-21', 'printed')),
    ('9/21/2026 9/21/2026', '', (None, 'needs-date')),
    ('', '2026.09.21 2026.09.21', (None, 'needs-date')),
    ('9/21/2026 8:00 AM', '2026.09.22 ; 08:00:00 AM', (None, 'needs-date')),
    ('9/21/2026 9/22/2026', '2026.09.21', (None, 'needs-date')),
    ('2/29/2026', '2026.02.28', (None, 'needs-date')),
])
def test_template_date_still_requires_two_independent_agreeing_boxes(local, scheduled, expected):
    values = {
        'local_scheduled_start_time': local,
        'scheduled_start': scheduled,
        'lead_name': '9/21/2026',  # Other fields cannot supply the second reading.
    }
    assert recognition._template_document_date(values) == expected


def test_known_pdf_date_skips_per_card_date_detection(monkeypatch):
    calls = []

    def detect(words, height):
        calls.append((words, height))
        return '2026-09-15', 'printed'

    monkeypatch.setattr(recognition, 'printed_date', detect)
    assert recognition.document_date([], 500, '2026-09-14') == ('2026-09-14', 'printed')
    assert calls == []
    assert recognition.document_date([], 500) == ('2026-09-15', 'printed')
    assert len(calls) == 1


def test_processor_reuses_first_reliable_day_and_backfills_earlier_card(tmp_path, monkeypatch):
    pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    image_module = pytest.importorskip('PIL.Image')
    from printer_app.gallery import cropper, processing_contract

    # The production worker executes this standalone module with local imports.
    # Resolve those imports explicitly without loading the printer runtime.
    for name, module in (('cropper', cropper), ('recognition', recognition),
                         ('processing_contract', processing_contract)):
        monkeypatch.setitem(sys.modules, name, module)
    script = Path(__file__).resolve().parents[1] / 'gallery' / 'processing.py'
    spec = importlib.util.spec_from_file_location('batch_date_processor_test', script)
    processor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(processor)

    def poppler(command, **kwargs):
        if command[0] == 'pdfinfo':
            return SimpleNamespace(stdout='Pages: 1\n')
        assert command[0] == 'pdftoppm'
        image_module.new('RGB', (120, 180), 'white').save(
            Path(command[-1]).with_suffix('.png')
        )
        return SimpleNamespace(returncode=0)

    crops = [(part, np.full((30, 120, 3), 240, dtype=np.uint8)) for part in range(1, 4)]
    monkeypatch.setattr(processor.subprocess, 'run', poppler)
    monkeypatch.setattr(processor.shutil, 'disk_usage', lambda path: SimpleNamespace(free=2**30))
    monkeypatch.setattr(processor, 'deskew_page', lambda raster: raster)
    monkeypatch.setattr(processor, 'orient_work_order_page', lambda raster: raster)
    monkeypatch.setattr(processor, 'is_dense_grid_page', lambda raster: False)
    monkeypatch.setattr(processor, 'cut_forms', lambda raster: iter(crops))
    observed_dates = []
    texts = ['Card one at 8:00 AM', 'Card two at 10:30 AM', 'Card three at 2:15 PM']

    def read_card(path, work, known_date=None):
        observed_dates.append(known_date)
        part = int(path.stem.split('-')[1])
        day = known_date or ('2026-09-21' if part == 2 else None)
        return dict(text=texts[part - 1], lead_text='', document_date=day,
                    date_status='printed' if day else 'needs-date')

    monkeypatch.setattr(processor, 'recognize', read_card)
    source = tmp_path / 'batch.pdf'
    source.write_bytes(b'%PDF-test-boundary')
    directory = tmp_path / 'processed'
    processor.process(source, directory, 1048576)

    assert observed_dates == [None, None, '2026-09-21']
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['items']) == 3
    assert [item['document_date'] for item in manifest['items']] == ['2026-09-21'] * 3
    assert [item['date_status'] for item in manifest['items']] == ['printed'] * 3
    assert [item['text'] for item in manifest['items']] == texts
    checkpoint = json.loads((directory / 'checkpoint.json').read_text(encoding='utf-8'))
    assert checkpoint['pdf_date'] == '2026-09-21'


def test_pdf_processing_reuses_first_reliable_date_for_every_card():
    source = (Path(__file__).resolve().parents[1] / 'gallery' / 'processing.py').read_text()
    assert 'pdf_date = None' in source
    assert 'known_date=pdf_date' in source
    assert "pdf_date = reading['document_date']" in source
    assert "for item in manifest['items']:" in source
    assert "item['document_date'] = pdf_date" in source
    assert "item['date_status'] = 'printed'" in source
