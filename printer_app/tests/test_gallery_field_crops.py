"""Pixel-preservation regressions for border-to-border variable-field OCR.

The synthetic form contains real letters/colons rather than solid label masks.
Dark-gray value ink lets these tests distinguish preserved data from black form
ink without invoking an OCR engine or depending on customer documents.
"""
import pytest

from printer_app.gallery.form_template import FormRegistration, TEMPLATE_FIELDS, map_box
from printer_app.gallery import recognition
from printer_app.tests.gallery_form_fixture import form_image as _form


VALUE_INK = 80
FIELDS = {field.key: field for field in TEMPLATE_FIELDS}
OCR_KEYS = set(recognition._OCR_FIELD_KEYS)


@pytest.fixture
def raster():
    return pytest.importorskip('cv2'), pytest.importorskip('numpy')


def _value_count(raster, image):
    return int(raster[1].count_nonzero(image == VALUE_INK))


def _field_pixels(canvas, segments, key):
    _, top, bottom = next(segment for segment in segments if segment[0] == key)
    return canvas[top:bottom]


@pytest.mark.parametrize('scale', [0.7, 1.0, 1.5])
def test_realistic_blank_labels_and_borders_do_not_enter_ocr(raster, scale):
    source, registration = _form(raster, scale)
    before = source.copy()

    canvas, segments = recognition.template_ocr_canvas(source, registration)

    assert canvas is None
    assert segments == []
    assert raster[1].array_equal(source, before)


def test_every_requested_field_keeps_ink_near_its_top_bottom_and_right_borders(raster):
    cv2, _ = raster
    source, registration = _form(raster)
    expected = {}
    for field in TEMPLATE_FIELDS:
        if field.key not in OCR_KEYS:
            continue
        left, top, right, bottom = map_box(registration, field.box)
        # Small disconnected value strokes sit inside the rules, beyond the
        # previous fixed percentage insets on all three relevant edges.
        cv2.rectangle(source, (right - 11, top + 4), (right - 4, top + 11), VALUE_INK, -1)
        cv2.rectangle(source, (right - 11, bottom - 11), (right - 4, bottom - 4), VALUE_INK, -1)
        expected[field.key] = _value_count(raster, source[top:bottom, left:right])

    canvas, segments = recognition.template_ocr_canvas(source, registration)

    assert {key for key, _, _ in segments} == OCR_KEYS
    for key, count in expected.items():
        assert _value_count(raster, _field_pixels(canvas, segments, key)) == count, key


@pytest.mark.parametrize('key', sorted(OCR_KEYS))
def test_value_starts_at_the_printed_colon_not_a_fixed_label_rectangle(raster, key):
    cv2, np = raster
    source, registration = _form(raster)
    left, top, right, bottom = map_box(registration, FIELDS[key].label_box)
    ys, xs = np.nonzero(source[top:bottom + 1, left:right + 1] == 0)
    printed_right = left + int(xs.max())
    baseline = top + int(ys.max())
    # The sample labels have ordinary font-width differences from the template.
    # A value after the actual colon must survive even before label_box.right.
    cv2.putText(source, 'Q', (printed_right + 3, baseline), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, VALUE_INK, 1, cv2.LINE_8)
    expected = _value_count(raster, source)

    canvas, segments = recognition.template_ocr_canvas(source, registration)

    assert [segment[0] for segment in segments] == [key]
    assert _value_count(raster, _field_pixels(canvas, segments, key)) == expected
    assert not np.any(canvas == 0)


@pytest.mark.parametrize('key', sorted(OCR_KEYS & {'lead_name', 'address', 'scheduled_start'}))
def test_wrapped_values_keep_full_width_below_the_label(raster, key):
    cv2, np = raster
    source, registration = _form(raster)
    field = FIELDS[key]
    left, top, right, bottom = map_box(registration, field.box)
    _, _, _, label_bottom = map_box(registration, field.label_box)
    # This line starts before the label, where a rectangular colon-to-border
    # crop would destroy the beginning of a wrapped address, time or note.
    baseline = min(bottom - 5, label_bottom + 30)
    font_scale = min(0.75, max(0.35, (bottom - label_bottom - 3) / 25.0))
    cv2.putText(source, 'CONTINUED', (left + 4, baseline), cv2.FONT_HERSHEY_SIMPLEX,
                font_scale, VALUE_INK, 2, cv2.LINE_8)
    expected = _value_count(raster, source)

    canvas, segments = recognition.template_ocr_canvas(source, registration)

    assert [segment[0] for segment in segments] == [key]
    assert _value_count(raster, _field_pixels(canvas, segments, key)) == expected
    assert not np.any(canvas == 0)


@pytest.mark.parametrize('key', sorted(OCR_KEYS & {'work_order_number', 'local_scheduled_start_time'}))
def test_single_line_fields_exclude_the_whole_label_column_but_keep_full_value_height(raster, key):
    cv2, np = raster
    source, registration = _form(raster)
    left, top, right, bottom = map_box(registration, FIELDS[key].box)
    label_left, label_top, label_right, label_bottom = map_box(registration, FIELDS[key].label_box)
    ys, _ = np.nonzero(source[label_top:label_bottom + 1, label_left:label_right + 1] == 0)
    printed_bottom = label_top + int(ys.max())
    excluded_ink = 140
    # These two fields never wrap: even ink below the label stays outside
    # their rectangular value region. Keep it separated from the printed line.
    cv2.rectangle(source, (left + 8, printed_bottom + 4),
                  (left + 14, bottom - 5), excluded_ink, -1)
    cv2.rectangle(source, (right - 12, top + 4), (right - 4, top + 11), VALUE_INK, -1)
    cv2.rectangle(source, (right - 12, bottom - 11), (right - 4, bottom - 4), VALUE_INK, -1)
    expected = _value_count(raster, source)
    before = source.copy()

    canvas, segments = recognition.template_ocr_canvas(source, registration)

    assert [segment[0] for segment in segments] == [key]
    pixels = _field_pixels(canvas, segments, key)
    assert _value_count(raster, pixels) == expected
    assert not np.any(pixels == excluded_ink)
    assert not np.any(canvas == 0)
    assert np.array_equal(source, before)


@pytest.mark.parametrize('key', sorted(OCR_KEYS & {'lead_name', 'address', 'scheduled_start'}))
def test_label_padding_cannot_clip_a_wrapped_line_two_blank_rows_below(raster, key):
    cv2, np = raster
    source, registration = _form(raster)
    left, _, _, _ = map_box(registration, FIELDS[key].box)
    label_left, label_top, label_right, label_bottom = map_box(registration, FIELDS[key].label_box)
    ys, _ = np.nonzero(source[label_top:label_bottom + 1, label_left:label_right + 1] == 0)
    printed_bottom = label_top + int(ys.max())
    text = np.full((40, 180), 255, np.uint8)
    cv2.putText(text, 'SECOND LINE', (0, 28), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, VALUE_INK, 1, cv2.LINE_8)
    ys, xs = np.nonzero(text == VALUE_INK)
    glyphs = text[int(ys.min()):int(ys.max()) + 1, int(xs.min()):int(xs.max()) + 1]
    value_top, value_left = printed_bottom + 3, left + 4
    source[value_top:value_top + glyphs.shape[0], value_left:value_left + glyphs.shape[1]] = glyphs
    assert np.all(source[printed_bottom + 1:value_top, value_left:value_left + glyphs.shape[1]] == 255)
    expected = _value_count(raster, source)
    before = source.copy()

    canvas, segments = recognition.template_ocr_canvas(source, registration)

    assert [segment[0] for segment in segments] == [key]
    assert _value_count(raster, _field_pixels(canvas, segments, key)) == expected
    assert not np.any(canvas == 0)
    assert np.array_equal(source, before)


@pytest.mark.parametrize('key', sorted(OCR_KEYS & {'local_scheduled_start_time', 'scheduled_start'}))
def test_colon_in_a_value_cannot_be_mistaken_for_the_label_colon(raster, key):
    cv2, np = raster
    source, registration = _form(raster)
    left, top, right, bottom = map_box(registration, FIELDS[key].label_box)
    ys, xs = np.nonzero(source[top:bottom + 1, left:right + 1] == 0)
    printed_right = left + int(xs.max())
    baseline = top + int(ys.max())
    cv2.putText(source, '10:30 AM', (printed_right + 4, baseline),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, VALUE_INK, 1, cv2.LINE_8)
    expected = _value_count(raster, source)
    before = source.copy()

    canvas, segments = recognition.template_ocr_canvas(source, registration)

    assert [segment[0] for segment in segments] == [key]
    assert _value_count(raster, _field_pixels(canvas, segments, key)) == expected
    assert not np.any(canvas == 0)
    assert np.array_equal(source, before)


@pytest.mark.parametrize('key', sorted(OCR_KEYS & {'lead_name', 'address', 'scheduled_start'}))
@pytest.mark.parametrize('text', ['ALEX', '10:30 AM'])
def test_missing_printed_colon_must_not_erase_the_start_of_the_value(raster, key, text):
    cv2, np = raster
    source, registration = _form(raster)
    left, top, right, bottom = map_box(registration, FIELDS[key].label_box)
    ys, xs = np.nonzero(source[top:bottom + 1, left:right + 1] == 0)
    printed_right = left + int(xs.max())
    baseline = top + int(ys.max())
    # Missing punctuation is a normal consequence of a faint printed label.
    # Its template position cannot authorize erasing an adjacent value word.
    source[top:bottom + 1, printed_right - 2:printed_right + 1] = 255
    cv2.putText(source, text, (printed_right + 4, baseline),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, VALUE_INK, 1, cv2.LINE_8)
    expected = _value_count(raster, source)
    before = source.copy()

    canvas, segments = recognition.template_ocr_canvas(source, registration)

    assert [segment[0] for segment in segments] == [key]
    assert _value_count(raster, _field_pixels(canvas, segments, key)) == expected
    assert np.array_equal(source, before)


@pytest.mark.parametrize('dx,dy', [(-3, -2), (3, 2)])
def test_small_registration_offsets_follow_the_printed_borders(raster, dx, dy):
    cv2, np = raster
    source, actual = _form(raster)
    left, top, right, bottom = map_box(actual, FIELDS['work_order_number'].box)
    _, _, label_right, _ = map_box(actual, FIELDS['work_order_number'].label_box)
    cv2.putText(source, '02275180', (label_right + 10, bottom - 6), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, VALUE_INK, 2, cv2.LINE_8)
    expected = _value_count(raster, source)
    approximate = FormRegistration(
        actual.score, actual.left + dx, actual.right + dx,
        actual.top + dy, actual.bottom + dy,
    )

    canvas, segments = recognition.template_ocr_canvas(source, approximate)

    assert [segment[0] for segment in segments] == ['work_order_number']
    assert _value_count(raster, _field_pixels(canvas, segments, 'work_order_number')) == expected
    assert not np.any(canvas == 0)


def test_work_order_field_uses_three_independent_reads_without_changing_mask(raster, monkeypatch, tmp_path):
    cv2, np = raster
    source, registration = _form(raster)
    key = 'work_order_number'
    left, top, right, bottom = map_box(registration, FIELDS[key].box)
    _, _, label_right, _ = map_box(registration, FIELDS[key].label_box)
    cv2.putText(source, '02275180', (label_right + 10, bottom - 7), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, VALUE_INK, 2, cv2.LINE_8)
    before = source.copy()
    calls = []

    def fake_tesseract(canvas, path, **kwargs):
        calls.append((canvas.copy(), path, kwargs))
        return [dict(text='02275180', left=0, top=0, width=40, height=12, conf=90,
                     page_num=1, block_num=1, par_num=1, line_num=1)]

    monkeypatch.setattr(recognition, '_run_tesseract', fake_tesseract)
    result = recognition._recognize_template(
        source, registration, tmp_path / 'ocr.png', '2026-09-19',
    )

    assert len(calls) == 3
    assert [call[2] for call in calls] == [
        {'digits_only': True, 'psm': 7},
        {'digits_only': True, 'psm': 13},
        {'digits_only': True, 'psm': 6},
    ]
    assert _value_count(raster, calls[0][0]) > 0
    assert np.array_equal(source, before)
    assert result['work_order_candidates'] == ('02275180',)
    assert result['text'] == 'Work Order Number: 02275180'
    assert result['document_date'] == '2026-09-19'
    assert result['date_status'] == 'printed'


def test_all_unrequested_fields_are_ignored_even_when_populated(raster):
    cv2, np = raster
    source, registration = _form(raster)
    for field in TEMPLATE_FIELDS:
        if field.key in OCR_KEYS:
            continue
        left, top, right, bottom = map_box(registration, field.box)
        cv2.rectangle(source, (left + 6, top + 6), (right - 6, bottom - 6),
                      VALUE_INK, -1)
    before = source.copy()
    assert _value_count(raster, source) > 0

    canvas, segments = recognition.template_ocr_canvas(source, registration)

    assert canvas is None
    assert segments == []
    assert np.array_equal(source, before)
