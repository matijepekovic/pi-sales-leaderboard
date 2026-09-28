"""Native MOD PDF-to-card handoff using synthetic appointments only."""
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_rendered_morning_pdf_becomes_searchable_cards_then_yields_to_scan(tmp_path, monkeypatch):
    missing = [name for name in ('pdfinfo', 'pdftoppm', 'tesseract') if not shutil.which(name)]
    if missing:
        pytest.skip('Native PDF/OCR tools unavailable: ' + ', '.join(missing))
    pytest.importorskip('fcntl')
    pytest.importorskip('cv2')
    image_module = pytest.importorskip('PIL.Image')
    pytest.importorskip('reportlab')

    from printer_app.gallery.bootstrap import GalleryReferenceInbox
    from printer_app.mod_sheet_contract import ModSheetRecord
    from printer_app.mod_sheets.pdf_renderer import render_mod_pdf
    from printer_app.print_queue_repository import PrintQueueRepository

    def unexpected_print(*args, **kwargs):
        pytest.fail('Gallery ingestion must not enqueue a print job')

    monkeypatch.setattr(PrintQueueRepository, '_enqueue_generated_pdf', unexpected_print)
    day = '2026-09-21'
    records = (
        ModSheetRecord(
            source_id='synthetic-morning-one', work_order_number='02012345',
            lead_name='Morgan Example', address='123 Harbor Street, Lacey, WA, 98503',
            local_scheduled_start_time='9/21/2026 8:00 AM',
            scheduled_start='2026.09.21 ; 08:00:00 AM', phone='3605550121',
            product_interest='Windows', work_type='Sales Appointment',
            source='Internet', sub_source='Showcase', set_by='Skyline Setter',
            canvass_set_by='Neighborhood Canvasser',
            lead_description='Energy efficient replacement requested',
            assigned_service_resources=('Morning Representative',),
        ),
        ModSheetRecord(
            source_id='synthetic-morning-two', work_order_number='02023456',
            lead_name='Taylor Sample', address='456 Orchard Avenue, Olympia, WA, 98501',
            local_scheduled_start_time='9/21/2026 10:30 AM',
            scheduled_start='2026.09.21 ; 10:30:00 AM', phone='3605550182',
            product_interest='Doors', work_type='Sales Appointment',
            source='Referral', sub_source='Homeowner', set_by='Valley Setter',
            canvass_set_by='Meadow Canvasser',
            lead_description='Entryway renovation requested',
        ),
    )
    payload = render_mod_pdf(records, color_code=False)
    inbox = GalleryReferenceInbox(tmp_path)
    inbox.publish(day, 'morning', records, 100.0, pdf_payload=payload)
    gallery = inbox.service
    job = gallery.repository.claim()
    assert job is not None and job['origin'] == 'morning'
    assert job['reference_day'] == day
    source = gallery.files.path('spool', job['id'])
    assert source.read_bytes() == payload
    directory = gallery.files.path('work', job['id'])
    script = Path(__file__).resolve().parents[1] / 'gallery' / 'processing.py'
    environment = dict(os.environ, OMP_THREAD_LIMIT='1', OPENBLAS_NUM_THREADS='1')
    result = subprocess.run(
        [sys.executable, str(script), str(source), str(directory), str(64 * 1048576), 'morning'],
        capture_output=True, text=True, timeout=300, env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['items']) == 2
    assert [(entry['page'], entry['part']) for entry in manifest['items']] == [(1, 1), (1, 2)]
    # This end-to-end handoff uses the real eight-digit 02 scan contract;
    # generic morning/source numbers remain covered by the non-OCR tests.
    # Retain one real crop and its actual recognition result for the scan handoff below.
    scan_entry = dict(manifest['items'][0])
    scan_image = (directory / scan_entry['file']).read_bytes()
    assert scan_image.startswith(b'\x89PNG\r\n\x1a\n')
    gallery.publish(job, manifest, directory)

    cards = gallery.search('', 0)['items']
    assert len(cards) == 2
    by_number = {card['work_order_number']: card for card in cards}
    assert set(by_number) == {record.work_order_number for record in records}
    for record in records:
        card = by_number[record.work_order_number]
        assert card['origin'] == 'morning'
        assert card['document_date'] == day
        assert card['lead_name'] == record.lead_name
        assert card['address'] == record.address
        assert gallery.files.path('crops', card['id']).is_file()
    for query, number in (
        ('3605550121', '02012345'), ('Showcase', '02012345'),
        ('Skyline', '02012345'), ('Neighborhood', '02012345'),
        ('Energy', '02012345'), ('Windows', '02012345'),
        ('3605550182', '02023456'), ('Homeowner', '02023456'),
        ('Valley', '02023456'), ('Meadow', '02023456'),
        ('Entryway', '02023456'), ('Doors', '02023456'),
    ):
        assert [item['work_order_number'] for item in gallery.search(query, 0)['items']] == [number]
    assert gallery.repository.import_state(job['id']) == 'COMPLETE'
    assert not source.exists()
    assert not directory.exists()

    first = by_number['02012345']
    remaining_id = by_number['02023456']['id']
    gallery.note(first['id'], 'a' * 32, 'Synthetic Reviewer', 'Keep this appointment note')
    # A returned scan must contain actual MOD notes. Draw a synthetic note inside
    # the observed notes cell and let the real recognition boundary verify it.
    import cv2
    import numpy as np
    from printer_app.gallery.form_template import field_boxes, register_form
    from printer_app.gallery.recognition import recognize
    raster = cv2.imdecode(np.frombuffer(scan_image, np.uint8), cv2.IMREAD_GRAYSCALE)
    registration = register_form(raster)
    notes = next(box for field, box in field_boxes(raster, registration) if field.key == 'mod_notes')
    left, top, right, bottom = notes
    cv2.putText(raster, 'Called homeowner', (left + 15, top + (bottom - top) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 3)
    scan_image = cv2.imencode('.png', raster)[1].tobytes()
    scan_pdf = BytesIO()
    with image_module.open(BytesIO(scan_image)) as image:
        image.convert('RGB').save(scan_pdf, format='PDF')
    scan_id = gallery.offer('synthetic-returned-scan.pdf', scan_pdf.getvalue(), inbox.options)
    scan_job = gallery.repository.claim()
    assert scan_job['id'] == scan_id and scan_job['origin'] == 'scan'
    scan_directory = gallery.files.path('work', scan_id)
    scan_directory.mkdir()
    (scan_directory / scan_entry['file']).write_bytes(scan_image)
    scan_entry.update(recognize(scan_directory / scan_entry['file'], scan_directory, known_date=day))
    assert scan_entry['mod_notes_present'] is True
    # The scan reader supplies only the exact work order; the source reference
    # supplies its date and customer fields even when OCR has no document date.
    assert tuple(scan_entry['work_order_candidates']) == ('02012345',)
    gallery.publish(scan_job, {'items': [scan_entry], 'warnings': [], 'skipped': []}, scan_directory)

    retained = gallery.search('', 0)['items']
    assert len(retained) == 2
    scanned = next(item for item in retained if item['id'] == first['id'])
    assert scanned['origin'] == 'scan'
    assert scanned['document_date'] == day
    assert scanned['image_revision'] != first['image_revision']
    assert gallery.item(first['id'])['notes'][0]['body'] == 'Keep this appointment note'
    assert gallery.files.path('crops', first['id']).read_bytes() == scan_image
    assert gallery.item(remaining_id)['origin'] == 'morning'
    assert gallery.files.path('crops', remaining_id).exists()
    assert gallery.search('Energy', 0)['total'] == 1
    assert gallery.search('Entryway', 0)['total'] == 1
    assert not (tmp_path / 'printer.db').exists()
