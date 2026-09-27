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

    monkeypatch.setattr(recognition, 'parse_numeric_image', lambda image, reader: {
        'candidate': '02275180',
        'positions': tuple('02275180'),
        'attempts': ({'psm': 10},),
    })

    outputs = iter([
        '02275188',
        '02275180',
        '02275108',
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

    result = recognition._recognize_template(
        source,
        registration,
        tmp_path / 'ocr.png',
        '2026-09-19',
        debug_path=debug,
    )

    assert debug.is_file()
    assert [read['label'] for read in result['work_order_reads']] == [
        'Numerical parser',
        'Whole field',
        '2x whole field',
        'Thresholded whole field',
        'Text field',
    ]
    assert result['work_order_candidates'] == (
        '02275180',
        '02275188',
        '02275108',
    )
    assert result['text'] == ''
    assert len(calls) == 4


def test_independent_candidate_answers_are_never_voted_away():
    result = recognition._candidate_result(
        ('02283948', '02283048', '02283948'),
        '2026-09-24',
    )

    assert result['work_order_candidates'] == ('02283948', '02283048')
    assert result['text'] == ''
