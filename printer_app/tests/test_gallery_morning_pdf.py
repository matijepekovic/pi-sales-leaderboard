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
            source_id='synthetic-morning-one', work_order_number='00012345',
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
            source_id='synthetic-morning-two', work_order_number='00023456',
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
        [sys.executable, str(script), str(source), str(directory), str(64 * 1048576)],
        capture_output=True, text=True, timeout=300, env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['items']) == 2
    assert [(entry['page'], entry['part']) for entry in manifest['items']] == [(1, 1), (1, 2)]
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
        ('3605550121', '00012345'), ('Showcase', '00012345'),
        ('Skyline', '00012345'), ('Neighborhood', '00012345'),
        ('Energy', '00012345'), ('Windows', '00012345'),
        ('3605550182', '00023456'), ('Homeowner', '00023456'),
        ('Valley', '00023456'), ('Meadow', '00023456'),
        ('Entryway', '00023456'), ('Doors', '00023456'),
    ):
        assert [item['work_order_number'] for item in gallery.search(query, 0)['items']] == [number]
    assert gallery.repository.import_state(job['id']) == 'COMPLETE'
    assert not source.exists()
    assert not directory.exists()

    first = by_number['00012345']
    removed_id = by_number['00023456']['id']
    gallery.note(first['id'], 'a' * 32, 'Synthetic Reviewer', 'Keep this appointment note')
    # The arriving scan is a one-card PDF of the produced raster. Its already-read
    # manifest tests publication/replacement without running the same OCR twice.
    scan_pdf = BytesIO()
    with image_module.open(BytesIO(scan_image)) as image:
        image.convert('RGB').save(scan_pdf, format='PDF')
    scan_id = gallery.offer('synthetic-returned-scan.pdf', scan_pdf.getvalue(), inbox.options)
    scan_job = gallery.repository.claim()
    assert scan_job['id'] == scan_id and scan_job['origin'] == 'scan'
    scan_directory = gallery.files.path('work', scan_id)
    scan_directory.mkdir()
    (scan_directory / scan_entry['file']).write_bytes(scan_image)
    # Returned scans now OCR only the work order. The saved Salesforce
    # reference supplies the date/name/address when this scan is published.
    assert scan_entry['document_date'] is None
    gallery.publish(scan_job, {'items': [scan_entry], 'warnings': [], 'skipped': []}, scan_directory)

    retained = gallery.search('', 0)['items']
    assert len(retained) == 1
    assert retained[0]['id'] == first['id']
    assert retained[0]['origin'] == 'scan'
    assert retained[0]['image_revision'] != first['image_revision']
    assert gallery.item(first['id'])['notes'][0]['body'] == 'Keep this appointment note'
    assert gallery.files.path('crops', first['id']).read_bytes() == scan_image
    assert gallery.item(removed_id) is None
    assert not gallery.files.path('crops', removed_id).exists()
    assert gallery.search('Energy', 0)['total'] == 1
    assert gallery.search('Entryway', 0)['total'] == 0
    assert not (tmp_path / 'printer.db').exists()
