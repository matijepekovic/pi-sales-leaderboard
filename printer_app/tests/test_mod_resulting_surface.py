"""Literal-template regressions: keep Printer as the sole owner of the form."""
from dataclasses import asdict, replace
from types import SimpleNamespace
from io import BytesIO
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageChops
import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter

from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_sheets.pdf_renderer import PRODUCT_COLORS, render_mod_pdf
from printer_app.mod_resulting.surface import (
    BOXES, DPI, HEIGHT, LEFT, TOP, WIDTH, ModSheetSurface, SheetSurfaceError, overlay_css,
)


RECORD = ModSheetRecord(source_id='0WO000000000001AAA', work_order_number='00123456',
                       lead_name='Sample Customer', address='123 Example Lane',
                       product_interest='Roofing;Siding')


@pytest.mark.skipif(not shutil.which('pdftoppm'), reason='Poppler required for literal sheet rendering')
def test_background_is_pixel_identical_to_original_printer_pdf(tmp_path):
    received = []
    def original_renderer(records):
        received.extend(records)
        return render_mod_pdf(records)
    surface = ModSheetSurface(original_renderer)
    actual = surface.image(RECORD)
    assert received == [RECORD]
    assert surface.image(RECORD) == actual
    assert received == [RECORD]  # Bounded cache, no repeated renderer calls.

    # Independently rasterize Printer's original PDF at the documented crop.
    reader = PdfReader(BytesIO(render_mod_pdf([RECORD])))
    writer = PdfWriter()
    page = writer.add_page(reader.pages[0])
    page.cropbox.lower_left = (LEFT, letter[1] - TOP - HEIGHT)
    page.cropbox.upper_right = (LEFT + WIDTH, letter[1] - TOP)
    with (tmp_path / 'reference.pdf').open('wb') as stream:
        writer.write(stream)
    subprocess.run(['pdftoppm','-f','1','-singlefile','-cropbox','-r',str(DPI),'-png',
                    str(tmp_path/'reference.pdf'),str(tmp_path/'reference')], check=True,
                   capture_output=True, timeout=30)
    with Image.open(BytesIO(actual)) as a, Image.open(tmp_path/'reference.png') as b:
        assert a.size == b.size
        assert ImageChops.difference(a.convert('RGB'),b.convert('RGB')).getbbox() is None
    surface.image(replace(RECORD, assigned_service_resources=('New Rep',)))
    assert len(received) == 2  # Routing refresh cannot reuse a stale image.


@pytest.mark.skipif(not shutil.which('pdftoppm'), reason='Poppler required for color rendering')
def test_color_code_reuses_printer_renderer_and_separate_image_cache():
    calls = []

    def renderer(records, *, color_code=False):
        calls.append(color_code)
        return render_mod_pdf(records, color_code=color_code)

    surface = ModSheetSurface(renderer)
    plain = surface.image(RECORD, color_code=False)
    colored = surface.image(RECORD, color_code=True)
    assert plain != colored
    assert calls == [False, True]
    assert surface.image(RECORD, color_code=True) == colored
    assert surface.image(RECORD, color_code=False) == plain
    assert calls == [False, True]

    with Image.open(BytesIO(colored)) as image:
        # Roofing's cyan and Siding's green come solely from Printer's
        # existing PRODUCT_COLORS palette, not a second MOD Resulting palette.
        assert any(r < 40 and g > 140 and b > 200
                   for r, g, b in image.convert('RGB').getdata())


@pytest.mark.skipif(not shutil.which('pdftoppm'), reason='Poppler required for color rendering')
def test_gutters_is_purple_in_shared_printer_and_resulting_color_palette():
    palette = {key: color for key, _, color in PRODUCT_COLORS}
    assert palette['gutters'] == '#B266FF'
    assert palette['roofing'] == '#00B0F0'  # Roofing stays blue.

    record = replace(RECORD, product_interest='Gutters')
    surface = ModSheetSurface(render_mod_pdf)
    with Image.open(BytesIO(surface.image(record, color_code=True))) as colored:
        assert any(abs(r - 178) <= 3 and abs(g - 102) <= 3 and abs(b - 255) <= 3
                   for r, g, b in colored.convert('RGB').getdata())
    with Image.open(BytesIO(surface.image(record, color_code=False))) as plain:
        assert not any(abs(r - 178) <= 3 and abs(g - 102) <= 3 and abs(b - 255) <= 3
                       for r, g, b in plain.convert('RGB').getdata())


def test_coordinates_use_the_original_mod_notes_cell_and_allow_only_overlays():
    notes = BOXES['notes']
    assert notes.x == pytest.approx(1 + 571.65 * .4)
    assert notes.width == pytest.approx(571.65 * .6)
    assert notes.y == pytest.approx(104.5)
    assert notes.height == pytest.approx(132.75)
    assert BOXES['ninety'].height == 30
    assert BOXES['dispo'].width == pytest.approx(571.65 * .2)
    assert BOXES['extras'].width == BOXES['dispo'].width
    root = Path(__file__).parents[1]
    html = (root/'templates/mod_resulting.html').read_text()
    css = (root/'static/mod_resulting/sheet.css').read_text()
    assert 'style=' not in html and '<style' not in html
    assert 'grid-template' not in css
    assert 'mod_resulting.surface_styles' in html
    assert 'printer-sheet' in html
    for name in BOXES:
        assert '.field-' + name in overlay_css()


def test_render_failure_never_substitutes_a_rebuilt_form():
    renderer = ModSheetSurface(render_mod_pdf, rasterizer='/missing-pdftoppm')
    with pytest.raises(SheetSurfaceError, match='could not render'):
        renderer.image(RECORD)


@pytest.mark.skipif(not shutil.which('pdftoppm'), reason='Poppler required for color verification')
def test_mod_resulting_preview_and_completed_pdf_follow_saved_mod_color_setting(tmp_path):
    from printer_app.app import create_app
    from printer_app.config import Config
    from printer_app.mod_sheets.policy import ModSheetAutomationSettings
    from printer_app.tests.auth_helpers import login_admin

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path / 'data', env_file=env,
                            secret_key='s' * 64, email_enabled=False))
    app.testing = True
    service = app.extensions['mod_resulting']
    service.repository.refresh(service.day(), [RECORD], market_segment='Olympia')
    service.writer = SimpleNamespace(
        mod_users=lambda market: [],
        dropdowns=lambda: {'result_details': [], 'dnr_reasons': [], 'products': []},
    )
    client = app.test_client()
    login_admin(client)
    image_url = '/mod-resulting/sheet/' + service.day() + '/' + RECORD.source_id + '.png'

    plain = client.get(image_url)
    assert plain.status_code == 200
    page = client.get('/mod-resulting')
    assert page.status_code == 200
    assert b'class="cell field-product replacement color-coded-product"' not in page.data
    rows = [{'snapshot': asdict(RECORD), 'draft': {}}]
    plain_pdf = service.pdf_exporter(rows)

    settings = app.extensions['mod_sheet_settings']
    settings.save(ModSheetAutomationSettings(market_segment='Olympia', color_code=True))
    colored = client.get(image_url)
    assert colored.status_code == 200 and colored.data != plain.data
    colored_page = client.get('/mod-resulting')
    assert b'class="cell field-product replacement color-coded-product"' in colored_page.data
    colored_pdf = service.pdf_exporter(rows)

    # Check the actual completed PDF pixels, not only PDF metadata or API flags.
    for label, payload in (('plain', plain_pdf), ('color', colored_pdf)):
        target = tmp_path / label
        target.with_suffix('.pdf').write_bytes(payload)
        subprocess.run([
            'pdftoppm', '-f', '1', '-singlefile', '-r', '90', '-png',
            str(target.with_suffix('.pdf')), str(target),
        ], check=True, capture_output=True, timeout=30)
    with Image.open(tmp_path / 'plain.png') as plain_image, \
         Image.open(tmp_path / 'color.png') as colored_image:
        assert ImageChops.difference(
            plain_image.convert('RGB'), colored_image.convert('RGB')
        ).getbbox() is not None
        assert any(r < 40 and g > 140 and b > 200
                   for r, g, b in colored_image.convert('RGB').getdata())

    settings.save(ModSheetAutomationSettings(market_segment='Olympia', color_code=False))
    assert client.get(image_url).data == plain.data
    assert b'class="cell field-product replacement color-coded-product"' not in client.get('/mod-resulting').data
    assert service.allow_salesforce_writes is False


def test_surface_endpoints_require_printer_login_and_a_saved_day(tmp_path):
    from printer_app.app import create_app
    from printer_app.config import Config
    from printer_app.tests.auth_helpers import login_admin
    env = tmp_path/'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path/'data',env_file=env,
                            secret_key='s'*64,email_enabled=False))
    app.testing = True
    service = app.extensions['mod_resulting']
    day = service.day()
    service.repository.refresh(day,[RECORD])
    client = app.test_client()
    route = '/mod-resulting/sheet/'+day+'/'+RECORD.source_id+'.png'
    assert client.get(route).status_code == 302
    login_admin(client)
    response = client.get(route)
    assert response.status_code == 200 and response.mimetype == 'image/png'
    assert response.headers['Cache-Control'] == 'no-store'
    styles = client.get('/mod-resulting/surface.css')
    assert styles.status_code == 200 and styles.mimetype == 'text/css'
    assert b'.field-notes' in styles.data
    assert client.get('/mod-resulting/sheet/'+day+'/unknown.png').status_code == 404
    assert client.get('/mod-resulting/sheet/not-a-day/'+RECORD.source_id+'.png').status_code == 404
    assert service.allow_salesforce_writes is False
