"""Template-to-numeric-field regressions with no customer images."""
import pytest

from printer_app.gallery.form_template import FormRegistration, TEMPLATE_FIELDS, map_box
from printer_app.gallery import recognition
from printer_app.tests.gallery_form_fixture import form_image as _form


VALUE_INK = 80
FIELDS = {field.key: field for field in TEMPLATE_FIELDS}


@pytest.fixture
def raster():
    return pytest.importorskip('cv2'), pytest.importorskip('numpy')


def _value_count(np, image):
    return int(np.count_nonzero(image == VALUE_INK))


def test_work_order_search_field_keeps_left_slack_instead_of_clipping_first_digit(raster):
    cv2, np = raster
    source, registration = _form(raster)
    field = FIELDS['work_order_number']
    left, top, right, bottom = map_box(registration, field.box)
    _, _, label_right, _ = map_box(registration, field.label_box)

    # Start deliberately before the old hard label boundary. The previous
    # implementation clipped this leading glyph and then tried to invent it.
    cv2.putText(
        source,
        '02285011',
        (label_right - 5, bottom - 7),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        VALUE_INK,
        2,
        cv2.LINE_8,
    )
    expected = _value_count(np, source[top:bottom, left:right])
    before = source.copy()

    canvas, segments = recognition.template_ocr_canvas(source, registration)

    assert [segment[0] for segment in segments] == ['work_order_number']
    assert _value_count(np, canvas) == expected
    assert np.array_equal(source, before)


@pytest.mark.parametrize('dx,dy', [(-4, -2), (4, 2)])
def test_numeric_search_field_survives_small_registration_offsets(raster, dx, dy):
    cv2, np = raster
    source, actual = _form(raster)
    field = FIELDS['work_order_number']
    _, _, label_right, _ = map_box(actual, field.label_box)
    _, _, _, bottom = map_box(actual, field.box)
    cv2.putText(
        source,
        '02275180',
        (label_right - 3, bottom - 6),
        cv2.FONT_HERSHEY_COMPLEX,
        0.7,
        VALUE_INK,
        2,
        cv2.LINE_AA,
    )
    approximate = FormRegistration(
        actual.score,
        actual.left + dx,
        actual.right + dx,
        actual.top + dy,
        actual.bottom + dy,
    )

    canvas, segments = recognition.template_ocr_canvas(source, approximate)

    assert [segment[0] for segment in segments] == ['work_order_number']
    assert _value_count(np, canvas) > 0


def test_template_recognition_runs_independent_systems_on_same_field(
        raster, monkeypatch, tmp_path):
    cv2, np = raster
    source, registration = _form(raster)
    field = FIELDS['work_order_number']
    _, _, label_right, _ = map_box(registration, field.label_box)
    _, _, _, bottom = map_box(registration, field.box)
    cv2.putText(
        source,
        '02275180',
        (label_right - 2, bottom - 7),
        cv2.FONT_HERSHEY_COMPLEX,
        0.8,
        VALUE_INK,
        2,
        cv2.LINE_AA,
    )

    numeric_inputs = []

    def numeric_reader(image, reader):
        numeric_inputs.append(image.copy())
        return {
            'candidate': '02275180',
            'candidates': ('02275180',),
            'positions': tuple('02275180'),
            'regions': ((0, 0, image.shape[1], image.shape[0]),),
            'attempts': ({'psm': 10},),
        }

    monkeypatch.setattr(recognition, 'parse_numeric_image', numeric_reader)

    outputs = iter([
        '02275188',
        '02275180',
        '02275108',
        '02275180',
        'O227518O',
    ])
    calls = []

    def fake_tesseract(canvas, path, **kwargs):
        text = next(outputs)
        calls.append((canvas.copy(), kwargs, text))
        return [dict(
            text=text,
            left=0,
            top=0,
            width=80,
            height=30,
            conf=90,
            page_num=1,
            block_num=1,
            par_num=1,
            line_num=1,
        )]

    monkeypatch.setattr(recognition, '_run_tesseract', fake_tesseract)
    debug = tmp_path / 'ocr-field.png'
    before = source.copy()

    result = recognition._recognize_template(
        source,
        registration,
        tmp_path / 'ocr.png',
        '2026-09-19',
        debug_path=debug,
    )

    assert debug.is_file()
    field_pixels = cv2.imread(str(debug), cv2.IMREAD_GRAYSCALE)
    assert np.array_equal(field_pixels, numeric_inputs[0])
    assert np.array_equal(field_pixels, calls[0][0])
    assert np.array_equal(field_pixels, calls[4][0])
    enlarged = cv2.resize(field_pixels, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    assert np.array_equal(enlarged, calls[1][0])
    assert np.array_equal(
        cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        calls[2][0],
    )
    tight = cv2.resize(field_pixels, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    tight = cv2.copyMakeBorder(tight, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    assert np.array_equal(tight, calls[3][0])
    assert np.array_equal(source, before)
    assert [read['label'] for read in result['work_order_reads']] == [
        'Numerical parser',
        'Whole field',
        '2x whole field',
        'Thresholded whole field',
        'Tight whole field',
        'Text field',
    ]
    assert result['work_order_candidates'] == (
        '02275180',
        '02275188',
        '02275108',
    )
    assert result['text'] == ''
    assert len(calls) == 5


def test_independent_candidate_answers_are_never_voted_away():
    result = recognition._candidate_result(
        ('02283948', '02283048', '02283948'),
        '2026-09-24',
    )

    assert result['work_order_candidates'] == ('02283948', '02283048')
    assert result['text'] == ''


@pytest.mark.parametrize('raw,expected', [
    ('02012345', ('02012345',)),
    ('O2O1234!', ('02012341',)),
    ('020123 45', ('02012345',)),
    ('O2O1 234!', ('02012341',)),
    ('02012345 1', ()),
    ('0 02012345', ()),
    ('02012 3451', ()),
    ('02012348 02012345 02012348', ('02012348', '02012345')),
    ('2012345', ()),
    ('020123451', ()),
    ('102012345', ()),
    ('!02012345', ()),
    ('02012345!', ()),
    ('00000001', ()),
    ('12012345', ()),
])
def test_scan_recognition_validates_complete_observed_tokens(raw, expected):
    assert recognition._work_order_candidates(raw) == expected


def test_whole_card_scan_cannot_recover_a_rejected_number_from_another_field():
    raw = 'Work Order Number: 020123451 Phone: 02012345\nMOD Notes: 02054321'
    assert recognition._work_order_candidates(raw, labeled=True) == ()


def test_whole_card_scan_preserves_independent_labeled_readings():
    raw = 'Work Order Number: O2O1234!\nWork Order Number: 02054321'
    assert recognition._work_order_candidates(raw, labeled=True) == ('02012341', '02054321')


def test_whole_card_joins_only_observed_digits_inside_the_work_order_field():
    raw = 'Work Order Number: 020123 45 Phone: 12345678\nMOD Notes: 02054321'
    assert recognition._work_order_candidates(raw, labeled=True) == ('02012345',)
    raw = 'Work Order Number: 020123 Phone: 45\nMOD Notes: 02054321'
    assert recognition._work_order_candidates(raw, labeled=True) == ()


def test_diagnostic_text_limit_cannot_turn_nine_digits_into_eight(
        raster, monkeypatch, tmp_path):
    source, registration = _form(raster)
    raw = 'x' * 119 + ' ' + '020123451'
    monkeypatch.setattr(recognition, 'parse_numeric_image', lambda *args: {})
    monkeypatch.setattr(recognition, '_run_tesseract', lambda *args, **kwargs: [dict(
        text=raw, page_num=1, block_num=1, par_num=1, line_num=1,
    )])
    result = recognition._recognize_template(source, registration, tmp_path / 'ocr.png', None)
    assert result['work_order_candidates'] == ()
    assert all(len(read['text']) <= 128 for read in result['work_order_reads'])


def test_full_card_text_limit_cannot_remove_an_observed_digit():
    raw = 'x' * 99974 + '\nWork Order Number: 020123451'
    words = [dict(text=raw, page_num=1, block_num=1, par_num=1, line_num=1)]
    assert recognition.search_text(words) == raw
    assert recognition._work_order_candidates(recognition.search_text(words), labeled=True) == ()


def test_partial_digit_read_does_not_suppress_whole_card_answer(
        raster, monkeypatch, tmp_path):
    from types import SimpleNamespace
    cv2, _ = raster
    source, _ = _form(raster)
    path = tmp_path / 'card.png'
    assert cv2.imwrite(str(path), source)
    monkeypatch.setattr(recognition, 'register_form', lambda image: SimpleNamespace(matched=True))
    monkeypatch.setattr(recognition, 'mod_notes_present', lambda *args: True)
    monkeypatch.setattr(recognition, '_recognize_template', lambda *args, **kwargs: {
        'work_order_candidates': ('02012345',),
        'work_order_reads': ({'label': 'Numerical parser', 'text': '0201234?', 'candidate': ''},),
    })
    monkeypatch.setattr(recognition, '_recognize_legacy', lambda *args: {
        'work_order_candidates': ('02012348',),
    })
    result = recognition.recognize(path, tmp_path)
    assert result['work_order_candidates'] == ('02012345', '02012348')
