"""Numerical parser stress tests using synthetic digits only; no customer data."""
import shutil

import pytest

from printer_app.gallery import recognition
from printer_app.gallery.numeric_parser import (
    normalize_numeric_token,
    numeric_token_from_text,
    parse_numeric_image,
)


@pytest.fixture
def raster():
    return pytest.importorskip('cv2'), pytest.importorskip('numpy')


def _field(raster, text, *, font, blur=0, angle=0, contrast=1.0,
           noise=0, label_tail=False, morphology=''):
    cv2, np = raster
    height, pitch = 65, 28
    start = 40 if label_tail else 20
    width = start + pitch * 8 + 100
    image = np.full((height, width), 255, np.uint8)

    if label_tail:
        cv2.putText(
            image, 'r:', (1, 44), font, 1.1, 0, 2, cv2.LINE_AA,
        )

    x = start
    for character in text:
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
        x += pitch

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
