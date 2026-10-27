"""Literal-template regressions: keep Printer as the sole owner of the form."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageChops
import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter

from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_sheets.pdf_renderer import render_mod_pdf
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
