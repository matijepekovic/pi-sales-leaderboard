"""Template OCR fast-path regressions; no printer/runtime dependencies."""
from pathlib import Path

import pytest

from printer_app.tests.gallery_form_fixture import form_image


def test_blank_template_geometry_is_removed_before_ocr():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.recognition import template_ocr_canvas

    image, registration = form_image((cv2, np))

    canvas, segments = template_ocr_canvas(image, registration)
    assert canvas is None
    assert segments == []


def test_template_ocr_packs_only_populated_variable_fields():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.form_template import TEMPLATE_FIELDS, map_box
    from printer_app.gallery.recognition import template_ocr_canvas

    image, registration = form_image((cv2, np))
    fields = {field.key: field for field in TEMPLATE_FIELDS}

    for key in ('lead_name', 'address', 'local_scheduled_start_time', 'scheduled_start'):
        field = fields[key]
        left, top, right, bottom = map_box(registration, field.box)
        # Variable ink deliberately lives away from the constant label rectangle.
        # Include a same-line name and lower-row values in the other cells.
        if field.lead:
            _, label_top, label_right, label_bottom = map_box(registration, field.label_box)
            x0 = label_right + 10
            y0 = label_top + 3
            y1 = min(label_bottom + 2, bottom - 8)
        else:
            x0 = left + int((right - left) * .62)
            y0 = top + int((bottom - top) * .62)
            y1 = min(bottom - 12, y0 + 12)
        cv2.rectangle(
            image,
            (x0, y0),
            (min(right - 20, x0 + 75), y1),
            0,
            -1,
        )

    canvas, segments = template_ocr_canvas(image, registration)
    keys = [key for key, _, _ in segments]
    assert canvas is not None
    assert set(keys) == {
        'lead_name', 'address', 'local_scheduled_start_time', 'scheduled_start'
    }
    # Tesseract should see a tiny packed raster, not the full 1942x809 card.
    assert canvas.size < image.size * .20
    assert 'mod_notes' not in keys  # blank handwriting area never enters OCR


def test_lead_name_label_mask_removes_residue_above_the_printed_label():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.form_template import FormRegistration, TEMPLATE_FIELDS, map_box
    from printer_app.gallery.recognition import _meaningful_bbox, template_ocr_canvas

    image = np.full((809, 1942), 255, np.uint8)
    registration = FormRegistration(1.0, 26, 1916, 19, 787)
    lead = next(field for field in TEMPLATE_FIELDS if field.lead)
    left, top, right, bottom = map_box(registration, lead.box)
    _, label_top, label_right, label_bottom = map_box(registration, lead.label_box)

    # Include the printed label so its line can be measured. The border-to-border
    # path deliberately preserves uncertain pixels when no label can be found.
    label_left, _, _, _ = map_box(registration, lead.label_box)
    cv2.putText(image, 'Lead Name:', (label_left, label_bottom - 3),
                cv2.FONT_HERSHEY_SIMPLEX, .7, 0, 1, cv2.LINE_8)
    # Residue above that label is within the label's excluded upper-left area.
    cv2.rectangle(image, (left + 45, top + 8), (left + 90, top + 9), 0, -1)

    # Simulate the actual printed lead-name value immediately after the label.
    value_left = label_right + 6
    value_top = label_top + 3
    cv2.rectangle(
        image,
        (value_left, value_top),
        (min(right - 18, value_left + 70), min(label_bottom + 2, bottom - 8)),
        0,
        -1,
    )

    canvas, segments = template_ocr_canvas(image, registration)
    lead_segment = next((segment for segment in segments if segment[0] == 'lead_name'), None)
    assert lead_segment is not None
    _, seg_top, seg_bottom = lead_segment
    bbox = _meaningful_bbox(canvas[seg_top:seg_bottom], minimum_area=1)

    assert bbox is not None
    # Only the value block remains. If left-side label/grid residue leaked into
    # this OCR segment, the bounding box would span far more than this.
    assert bbox[2] - bbox[0] < 100


def test_template_search_contract_keeps_fields_lead_date_and_each_cards_time():
    from printer_app.gallery.recognition import _template_document_date, _template_search_text

    values = {
        'work_order_number': '02275180',
        'local_scheduled_start_time': '2026-09-19 10:30 AM',
        'lead_name': 'JORDAN EXAMPLE',
        'address': '123 MAIN ST',
        'scheduled_start': '2026-09-19 10:30 AM',
        'product_interest': 'WINDOWS',
    }
    text = _template_search_text(values)
    assert 'Lead Name: JORDAN EXAMPLE' in text
    assert 'Address: 123 MAIN ST' in text
    assert 'Work Order Number: 02275180' in text
    assert 'Product Interest' not in text
    assert 'WINDOWS' not in text
    assert text.count('10:30 AM') == 2
    assert _template_document_date(values) == ('2026-09-19', 'printed')

    # Reusing a PDF date does not replace or invent a card's time text.
    different_time = dict(values, local_scheduled_start_time='2026-09-19 2:15 PM')
    assert '2:15 PM' in _template_search_text(different_time)
    assert _template_document_date(different_time, '2026-09-19') == ('2026-09-19', 'printed')


def test_template_and_ocr_owners_remain_replaceable():
    root = Path(__file__).resolve().parents[1]
    template = (root / 'gallery/form_template.py').read_text()
    recognition = (root / 'gallery/recognition.py').read_text()
    processing = (root / 'gallery/processing.py').read_text()

    assert 'subprocess' not in template and "['tesseract'" not in template.lower()
    assert 'sqlite3' not in template and 'flask' not in template
    assert 'TEMPLATE_FIELDS' in recognition
    assert 'TEMPLATE_FIELDS' not in processing
    assert "['tesseract'," not in processing.lower()  # no direct OCR-engine invocation
