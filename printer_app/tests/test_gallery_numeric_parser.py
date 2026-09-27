"""Numerical parser stress tests using synthetic digits only; no customer data."""
import shutil

import pytest

from printer_app.gallery import numeric_parser, recognition
from printer_app.gallery.numeric_parser import (
    normalize_numeric_token,
    numeric_token_from_text,
    parse_numeric_image,
)


@pytest.fixture
def raster():
    return pytest.importorskip('cv2'), pytest.importorskip('numpy')


def _field(raster, text, *, font, blur=0, angle=0, contrast=1.0,
           noise=0, label_tail=False, morphology='', pitches=()):
    cv2, np = raster
    height, pitch = 65, 28
    start = 40 if label_tail else 20
    width = start + (sum(pitches) if pitches else pitch * 8) + 100
    image = np.full((height, width), 255, np.uint8)

    if label_tail:
        cv2.putText(
            image, 'r:', (1, 44), font, 1.1, 0, 2, cv2.LINE_AA,
        )

    x = start
    for position, character in enumerate(text):
        (text_width, _), _ = cv2.getTextSize(character, font, 1.1, 2)
        cv2.putText(
            image,
            character,
            (x + (pitch - text_width) // 2, 45),
            font,
            1.1,
            0,
            2,
            cv2.LINE_AA,
        )
        x += pitches[position] if pitches else pitch

    # Residual MOD cell rules are normal input to the parser.
    cv2.line(image, (0, 2), (width - 1, 2), 0, 2)
    cv2.line(image, (0, height - 3), (width - 1, height - 3), 0, 2)
    cv2.line(image, (width - 3, 0), (width - 3, height - 1), 0, 2)

    if angle:
        transform = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
        image = cv2.warpAffine(
            image, transform, (width, height), borderValue=255,
        )
    if blur:
        image = cv2.GaussianBlur(image, (blur, blur), 0)
    if contrast != 1.0:
        image = np.clip(255 - (255 - image) * contrast, 0, 255).astype(np.uint8)
    if noise:
        rng = np.random.default_rng(12345)
        image = np.clip(
            image + rng.normal(0, noise, image.shape),
            0,
            255,
        ).astype(np.uint8)
    if morphology:
        binary = cv2.threshold(
            image, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )[1]
        if morphology == 'dilate':
            binary = cv2.dilate(binary, np.ones((2, 2), np.uint8))
        elif morphology == 'erode':
            binary = cv2.erode(binary, np.ones((2, 2), np.uint8))
        image = 255 - binary
    return image


@pytest.mark.parametrize(('raw', 'expected'), [
    ('02285011', '02285011'),
    ('O228501!', '02285011'),
    ('o22B501!', '02285011'),
    ('32285011', '32285011'),
    ('0225558', ''),
    ('2285011', ''),
    ('022850111', ''),
])
def test_text_token_normalization_changes_glyph_identity_not_position(raw, expected):
    assert normalize_numeric_token(raw) == expected


def test_generic_text_token_parser_has_no_work_order_prefix_knowledge():
    assert numeric_token_from_text('Value: O22B501! End') == '02285011'
    assert numeric_token_from_text('Value: 32285011 End') == '32285011'
    assert numeric_token_from_text('Value: 0228501 End') == ''


@pytest.mark.parametrize(('text', 'font_name', 'options'), [
    ('02285011', 'complex', {}),
    ('02012345', 'simplex', {'blur': 3}),
    ('02678901', 'triplex', {'blur': 5}),
    ('02987654', 'duplex', {'angle': 2}),
    ('02234567', 'complex', {'angle': -2}),
    ('02888888', 'complex', {'contrast': .45}),
    ('02111111', 'duplex', {'noise': 8}),
    ('02000000', 'triplex', {'label_tail': True, 'blur': 3}),
    ('02555555', 'simplex', {'morphology': 'dilate'}),
    ('02666666', 'complex', {'morphology': 'erode'}),
    ('73910426', 'simplex', {'pitches': (24, 32, 26, 38, 25, 30, 27, 24)}),
])
def test_numerical_parser_reads_eight_positions_across_scan_damage(
        raster, tmp_path, text, font_name, options):
    if not shutil.which('tesseract'):
        pytest.skip('Tesseract is required for numerical parser integration.')

    cv2, _ = raster
    fonts = {
        'simplex': cv2.FONT_HERSHEY_SIMPLEX,
        'duplex': cv2.FONT_HERSHEY_DUPLEX,
        'complex': cv2.FONT_HERSHEY_COMPLEX,
        'triplex': cv2.FONT_HERSHEY_TRIPLEX,
    }
    image = _field(raster, text, font=fonts[font_name], **options)
    working = tmp_path / 'digit.png'

    def read_words(glyph, psm):
        return recognition._run_tesseract(
            glyph,
            working,
            digits_only=True,
            psm=psm,
        )

    parsed = parse_numeric_image(image, read_words)

    assert parsed['candidate'] == text
    assert ''.join(parsed['positions']) == text


def test_numerical_parser_never_pads_a_missing_position(raster, tmp_path):
    if not shutil.which('tesseract'):
        pytest.skip('Tesseract is required for numerical parser integration.')

    cv2, _ = raster
    image = _field(
        raster,
        '0225558',
        font=cv2.FONT_HERSHEY_COMPLEX,
        blur=3,
        label_tail=True,
    )
    working = tmp_path / 'digit.png'

    def read_words(glyph, psm):
        return recognition._run_tesseract(
            glyph,
            working,
            digits_only=True,
            psm=psm,
        )

    assert parse_numeric_image(image, read_words)['candidate'] == ''


def test_border_cleanup_preserves_compact_full_height_digit_stems(raster):
    cv2, np = raster
    image = np.full((38, 210), 255, np.uint8)
    cv2.line(image, (0, 0), (209, 0), 0, 1)
    for x in range(15, 175, 20):
        cv2.rectangle(image, (x, 6), (x + 2, 31), 0, -1)

    layouts, mask = numeric_parser._slot_candidates(image, 8)

    assert len(layouts) == 1
    assert len(layouts[0]) == 8
    assert np.count_nonzero(mask[:, 16]) == 26
    assert not mask[0].any()


def test_disconnected_top_and_bottom_still_own_one_glyph_position(raster):
    cv2, np = raster
    image = np.full((38, 240), 255, np.uint8)
    # A shorter label remnant precedes eight full-height glyphs. One glyph has
    # a faded horizontal band splitting its ink into two disconnected pieces.
    cv2.rectangle(image, (0, 15), (14, 31), 0, -1)
    for x in range(35, 195, 20):
        cv2.rectangle(image, (x, 6), (x + 4, 31), 0, -1)
    image[18:20, 75:80] = 255

    layouts, _ = numeric_parser._slot_candidates(image, 8)

    assert len(layouts) == 1
    assert len(layouts[0]) == 8
    assert layouts[0][0][0] > 14
    assert layouts[0][2][0] <= 75 < layouts[0][2][1]


@pytest.mark.parametrize('digits', ['1234567', '123456789'])
def test_visible_character_count_cannot_be_fitted_to_eight_slots(raster, digits):
    cv2, _ = raster
    image = _field(raster, digits, font=cv2.FONT_HERSHEY_SIMPLEX)
    layouts, _ = numeric_parser._slot_candidates(image, 8)
    assert layouts == ()
    assert parse_numeric_image(image, lambda *args: ())['regions'] == ()


def test_complete_observed_region_preserves_all_eight_glyphs_without_recognition(raster):
    cv2, np = raster
    image = np.full((38, 220), 255, np.uint8)
    for x in range(15, 175, 20):
        cv2.rectangle(image, (x, 6), (x + 2, 31), 0, -1)

    parsed = parse_numeric_image(image, lambda *args: ())

    assert parsed['candidates'] == ()
    assert len(parsed['regions']) == 1
    left, top, right, bottom = parsed['regions'][0]
    ys, xs = np.nonzero(image < 255)
    assert left < xs.min() <= xs.max() < right
    assert top == ys.min() - 2
    assert bottom == ys.max() + 3
    assert np.count_nonzero(image[top:bottom, left:right] < 255) == len(xs)


def test_small_dust_only_field_returns_unresolved_without_a_valley_search_error(raster):
    _, np = raster
    image = np.full((50, 200), 255, np.uint8)
    image[20:24, 40:46] = 0

    parsed = parse_numeric_image(image, lambda *args: ())

    assert parsed['candidate'] == ''
    assert parsed['candidates'] == ()
    assert parsed['attempts'] == ()
    assert parsed['regions'] == ()


def _observed_slots(monkeypatch, raster, *, layouts=1):
    _, np = raster
    bounds = tuple(tuple((layout * 100 + position * 10, layout * 100 + position * 10 + 8)
                         for position in range(8)) for layout in range(layouts))
    mask = np.full((12, layouts * 100), 255, np.uint8)
    monkeypatch.setattr(numeric_parser, '_slot_candidates', lambda image, count: (bounds, mask))
    monkeypatch.setattr(numeric_parser, '_normalized_glyph',
                        lambda image, mask, left, right, *, glyph_height:
                        np.array([[left // 10, glyph_height]], dtype=np.uint8))
    return mask


def test_conflicting_complete_passes_remain_separate_answers(monkeypatch, raster):
    image = _observed_slots(monkeypatch, raster)

    def reader(glyph, psm):
        position, scale = glyph[0]
        value = '73910426' if scale == 36 else '73910428'
        return [{'text': value[position], 'conf': 95}]

    parsed = parse_numeric_image(image, reader)

    assert parsed['candidate'] == ''
    assert parsed['candidates'] == ('73910426', '73910428')
    assert len(parsed['attempts']) == 24


def test_a_complete_first_layout_does_not_hide_a_conflicting_later_layout(monkeypatch, raster):
    image = _observed_slots(monkeypatch, raster, layouts=2)

    def reader(glyph, psm):
        index = int(glyph[0][0])
        value = '73910426' if index < 10 else '73910428'
        return [{'text': value[index % 10], 'conf': 95}]

    parsed = parse_numeric_image(image, reader)

    assert parsed['candidate'] == ''
    assert parsed['candidates'] == ('73910426', '73910428')
    assert {attempt['layout'] for attempt in parsed['attempts']} == {0, 1}


def test_incomplete_passes_cannot_be_spliced_into_a_new_answer(monkeypatch, raster):
    image = _observed_slots(monkeypatch, raster)

    def reader(glyph, psm):
        position, scale = glyph[0]
        missing = 0 if psm == 13 else (1 if scale == 36 else 2)
        return [] if position == missing else [{'text': '73910426'[position], 'conf': 95}]

    parsed = parse_numeric_image(image, reader)

    assert parsed['candidate'] == ''
    assert parsed['candidates'] == ()
    assert len(parsed['attempts']) == 24


def test_repeated_low_confidence_reads_remain_unresolved(monkeypatch, raster):
    image = _observed_slots(monkeypatch, raster)
    parsed = parse_numeric_image(image, lambda glyph, psm: [{'text': '8', 'conf': 1}])

    assert parsed['candidate'] == ''
    assert parsed['candidates'] == ()
    assert all(attempt['digit'] == '8' and attempt['confidence'] == 1 for attempt in parsed['attempts'])


@pytest.mark.parametrize('words', [
    [{'text': '8x', 'conf': 95}],
    [{'text': '８', 'conf': 95}],
    [{'text': '²', 'conf': 95}],
    [{'text': '1', 'conf': 95}, {'text': '4', 'conf': 95}],
])
def test_one_glyph_does_not_drop_symbols_or_select_one_of_multiple_digits(words):
    assert numeric_parser._one_digit(words) == ('', -1.0)
