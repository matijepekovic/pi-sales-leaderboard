"""Rendered-PDF regressions, using synthetic data only (no customer fixtures)."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import ast
import unittest

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Table, Paragraph
from reportlab.lib.styles import ParagraphStyle

from printer_app.report_notes_contract import ReportNotesError, ReportNotesOptions
from printer_app.report_notes_pdf import normalize_pdf, render_notes
from printer_app.report_table_pdf import read_tables


def fixture(pages=None, size=(612, 792), top=100, widths=None, styles=(), footer=True):
    """Real text, lines, merged cells and pagination, not fabricated parser output."""
    pages = pages if pages is not None else [
        [['Customer', 'Job', 'Product'], ['Alpha', '101', 'Roof'], ['Beta', '102', 'Bath']]]
    width, height = size
    widths = widths or [170, 70, width - 288]
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=size)
    for index, rows in enumerate(pages):
        canvas.setFont('Helvetica', 10)
        canvas.drawString(24, height - 30, 'Synthetic report')
        table = Table(rows, colWidths=widths, style=[
            ('GRID', (0, 0), (-1, -1), .5, colors.black),
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 9),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'), *styles])
        _, table_height = table.wrap(width - 48, 100000)
        table.drawOn(canvas, 24, height - top - table_height)
        if footer:
            canvas.setFont('Helvetica', 8)
            canvas.drawString(24, 10, f'Page {index + 1}')
        canvas.showPage()
    canvas.save()
    return normalize_pdf(stream.getvalue())


def overlay(data, **changes):
    options = ReportNotesOptions(enabled=True, columns=('Customer', 'Job'), **changes)
    tables = read_tables(data, options.columns)
    output, placement = render_notes(data, tables, options)
    return tables, output, placement


class ReportNotesSettingsTests(unittest.TestCase):
    def test_defaults_are_disabled_and_snapshot_round_trips(self):
        self.assertFalse(ReportNotesOptions().enabled)
        value = ReportNotesOptions(True, ('Customer', 'Job'), 14.5, 11.5, 3)
        self.assertEqual(ReportNotesOptions.from_dict(value.snapshot()), value)

    def test_invalid_settings_fail_before_rendering(self):
        invalid = [dict(enabled=1), dict(enabled=True), dict(columns='Customer'),
                   dict(columns=['Customer', 'Customer ↑']), dict(font_size=float('nan')),
                   dict(row_spacing_mm=float('inf')), dict(table_gap_mm=-1),
                   dict(font_size=True), dict(columns=['']), dict(unknown=True)]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ReportNotesError):
                ReportNotesOptions.from_dict(value)


class ReportNotesPdfTests(unittest.TestCase):
    def test_real_grid_and_native_cell_text_are_used(self):
        data = fixture()
        tables, output, placements = overlay(data)
        self.assertEqual(tables.columns, ('Customer', 'Job', 'Product'))
        self.assertEqual(tables.pages[0].rows, (('Alpha', '101'), ('Beta', '102')))
        text = PdfReader(BytesIO(output)).pages[0].extract_text()
        self.assertEqual(text.count('Alpha'), 2)
        self.assertEqual(text.count('Beta'), 2)
        self.assertEqual(placements[0].rows, 2)
        self.assertEqual(placements[0].scale, 1)

    def test_gap_and_spacing_are_physical_controls(self):
        data = fixture()
        a, _, pa = overlay(data, row_spacing_mm=4, table_gap_mm=2)
        b, _, pb = overlay(data, row_spacing_mm=12, table_gap_mm=7)
        self.assertAlmostEqual(pb[0].notes_top - pa[0].notes_top, 5 * 72 / 25.4)
        self.assertAlmostEqual((pb[0].notes_bottom - pb[0].notes_top) -
                               (pa[0].notes_bottom - pa[0].notes_top), 2 * 8 * 72 / 25.4)
        self.assertEqual(a.pages[0].bottom, b.pages[0].bottom)

    def test_start_tracks_moved_table_not_a_fixed_y(self):
        a, _, pa = overlay(fixture(top=80))
        b, _, pb = overlay(fixture(top=260))
        self.assertAlmostEqual(pb[0].notes_top - pa[0].notes_top, 180)
        self.assertGreater(pb[0].notes_top, b.pages[0].bottom)

    def test_crowded_page_shrinks_without_clipping_or_extra_pages(self):
        data = fixture(top=670)
        tables, result, placements = overlay(data, row_spacing_mm=25)
        p = placements[0]
        self.assertLess(p.scale, 1)
        self.assertGreater(p.notes_top, p.table_bottom)
        self.assertLessEqual(p.notes_bottom, p.footer_top + .0001)
        self.assertEqual(len(PdfReader(BytesIO(result)).pages), 1)
        text = PdfReader(BytesIO(result)).pages[0].extract_text()
        self.assertIn('Alpha', text)
        self.assertEqual(p.rows, 2)
        # Cropped PDF streams can retain invisible text. Test printed pixels,
        # not a text extractor that ignores graphics-state clipping.
        import pypdfium2
        doc = pypdfium2.PdfDocument(result)
        try:
            image = doc[0].render(scale=2).to_pil().convert('RGB')
            old_right_edge = image.crop((1174, 1340, 1178, 1440))
            # Gray handwriting rules may cross this strip, but the old black
            # vertical table border must no longer be printed here.
            self.assertGreater(min(v[0] for v in old_right_edge.getextrema()), 140)
        finally:
            doc.close()
        with pdfplumber.open(BytesIO(result)) as pdf:
            for char in pdf.pages[0].chars:
                self.assertGreaterEqual(char['x0'], 0)
                self.assertLessEqual(char['x1'], 612)
                self.assertGreaterEqual(char['top'], 0)
                self.assertLessEqual(char['bottom'], 792)

    def test_footer_position_survives_shrink(self):
        data = fixture(top=670)
        _, result, _ = overlay(data, row_spacing_mm=25)
        with pdfplumber.open(BytesIO(data)) as before, pdfplumber.open(BytesIO(result)) as after:
            a = [c['top'] for c in before.pages[0].chars if c['text'] == 'P' and c['top'] > 750]
            b = [c['top'] for c in after.pages[0].chars if c['text'] == 'P' and c['top'] > 750]
            self.assertEqual(a, b)
        import pypdfium2
        before = pypdfium2.PdfDocument(data)
        after = pypdfium2.PdfDocument(result)
        try:
            box = (0, int(min(a) * 2) - 1, 1224, 1584)
            a = before[0].render(scale=2).to_pil().crop(box)
            b = after[0].render(scale=2).to_pil().crop(box)
            self.assertEqual(a.tobytes(), b.tobytes())
        finally:
            before.close(); after.close()

    def test_existing_report_pixels_unchanged_when_space_is_available(self):
        import pypdfium2
        data = fixture()
        tables, result, _ = overlay(data)
        before = pypdfium2.PdfDocument(data)
        after = pypdfium2.PdfDocument(result)
        try:
            box = (0, 0, 1224, int(tables.pages[0].bottom * 2))
            a = before[0].render(scale=2).to_pil().crop(box)
            b = after[0].render(scale=2).to_pil().crop(box)
            self.assertEqual(a.tobytes(), b.tobytes())
        finally:
            before.close(); after.close()

    def test_columns_follow_names_and_selected_order_not_positions(self):
        data = fixture(pages=[[['Product', 'Customer', 'Job'], ['Roof', 'Alpha', '101']]])
        options = ReportNotesOptions(True, ('Job', 'Customer'))
        parsed = read_tables(data, options.columns)
        self.assertEqual(parsed.pages[0].rows, (('101', 'Alpha'),))

    def test_duplicate_customer_names_remain_distinct_jobs(self):
        data = fixture(pages=[[['Customer', 'Job', 'Product'], ['Alpha', '101', 'Roof'], ['Alpha', '102', 'Bath']]])
        parsed = read_tables(data, ('Customer',))
        self.assertEqual(parsed.pages[0].rows, (('Alpha',), ('Alpha',)))

    def test_blank_selected_cells_do_not_drop_detail_records(self):
        data = fixture(pages=[[['Customer', 'Job', 'Product'], ['', '101', 'Roof'], ['Beta', '102', 'Bath']]])
        parsed = read_tables(data, ('Customer',))
        self.assertEqual(parsed.pages[0].rows, (('',), ('Beta',)))

    def test_merged_groups_and_multiline_subtotals(self):
        data = fixture(pages=[[
            ['Market', 'Customer', 'Job'], ['West', 'Alpha', '101'], ['', 'Beta', '102'],
            ['Subtotal', 'Sum', '203'], ['', 'Count', '2'], ['Total', 'Sum', '203']]],
            styles=[('SPAN', (0, 1), (0, 2)), ('SPAN', (0, 3), (0, 4))])
        parsed = read_tables(data, ('Market', 'Customer', 'Job'))
        self.assertEqual(parsed.pages[0].rows, (('West', 'Alpha', '101'), ('West', 'Beta', '102')))

    def test_no_cross_page_jobs(self):
        data = fixture(pages=[
            [['Customer', 'Job', 'Product'], ['Alpha', '101', 'Roof']],
            [['Customer', 'Job', 'Product'], ['Beta', '102', 'Bath']]])
        parsed, result, placements = overlay(data)
        self.assertEqual(len(placements), 2)
        texts = [page.extract_text() for page in PdfReader(BytesIO(result)).pages]
        self.assertEqual(texts[0].count('Alpha'), 2)
        self.assertNotIn('Beta', texts[0])
        self.assertEqual(texts[1].count('Beta'), 2)
        self.assertNotIn('Alpha', texts[1])

    def test_continued_page_without_a_repeated_header(self):
        data = fixture(pages=[
            [['Customer', 'Job', 'Product'], ['Alpha', '101', 'Roof']],
            [['Beta', '102', 'Bath'], ['Gamma', '103', 'Windows']]])
        parsed = read_tables(data, ('Customer', 'Job'))
        self.assertEqual(parsed.pages[1].rows, (('Beta', '102'), ('Gamma', '103')))

    def test_catalog_does_not_mistake_continuation_customers_for_columns(self):
        data = fixture(pages=[
            [['Customer', 'Job', 'Product'], ['Alpha', '101', 'Roof']],
            [['Beta', '102', 'Bath'], ['Gamma', '103', 'Windows']]])
        self.assertEqual(read_tables(data).columns, ('Customer', 'Job', 'Product'))

    def test_changed_header_on_same_grid_fails_instead_of_mislabeling(self):
        data = fixture(pages=[
            [['Customer', 'Job', 'Product'], ['Alpha', '101', 'Roof']],
            [['Assignee', 'Job', 'Product'], ['Beta', '102', 'Bath']]])
        with self.assertRaises(ReportNotesError):
            read_tables(data, ('Customer', 'Job'))

    def test_missing_and_duplicate_headings_fail_visibly(self):
        with self.assertRaises(ReportNotesError):
            read_tables(fixture(), ('Missing',))
        with self.assertRaises(ReportNotesError):
            read_tables(fixture(pages=[[['Customer', 'Customer', 'Job'], ['Alpha', 'Beta', '101']]]), ('Customer',))

    def test_header_only_report_has_no_phantom_jobs(self):
        parsed, result, placements = overlay(fixture(pages=[[['Customer', 'Job', 'Product']]]))
        self.assertEqual(parsed.pages[0].rows, ())
        self.assertEqual(placements, ())
        self.assertNotIn('Updates', PdfReader(BytesIO(result)).pages[0].extract_text())

    def test_wrapped_field_and_long_name_are_retained(self):
        name = 'Alexandra Example-With-A-Very-Long-Surname'
        style = ParagraphStyle('cell', fontName='Helvetica', fontSize=9, leading=11)
        data = fixture(pages=[[
            ['Customer', 'Job', 'Product'], [Paragraph(name, style), '101', 'Roof']]], widths=[115, 70, 350])
        parsed, result, _ = overlay(data, font_size=18)
        self.assertEqual(parsed.pages[0].rows[0][0].replace(' ', ''), name.replace(' ', ''))
        # Every non-space source character is still in the overlay paragraph.
        text = ''.join(PdfReader(BytesIO(result)).pages[0].extract_text().split())
        self.assertEqual(text.count(name.replace(' ', '')), 2)

    def test_multiple_paper_sizes(self):
        for size in ((612, 792), (792, 612), (1224, 792)):
            with self.subTest(size=size):
                parsed, result, placements = overlay(fixture(size=size))
                page = PdfReader(BytesIO(result)).pages[0]
                self.assertEqual((float(page.mediabox.width), float(page.mediabox.height)), size)
                self.assertLessEqual(placements[0].notes_bottom, size[1] - 18)

    def test_nonzero_crop_origin_is_normalized(self):
        reader = PdfReader(BytesIO(fixture()))
        page = reader.pages[0]
        page.cropbox = RectangleObject((12, 12, 600, 780))
        writer = PdfWriter(); writer.add_page(page)
        stream = BytesIO(); writer.write(stream)
        parsed, result, placements = overlay(normalize_pdf(stream.getvalue()))
        self.assertEqual((parsed.pages[0].width, parsed.pages[0].height), (588, 768))
        self.assertLessEqual(placements[0].notes_bottom, 750)

    def test_disabled_notes_are_byte_identical(self):
        data = fixture()
        result, placements = render_notes(data, read_tables(data), ReportNotesOptions())
        self.assertEqual(result, data)
        self.assertEqual(placements, ())

    def test_architecture_boundaries(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('report_notes_contract.py', 'report_table_pdf.py', 'report_notes_pdf.py'):
            tree = ast.parse((root / name).read_text())
            imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            self.assertFalse(any(any(word in value for word in ('salesforce', 'tableau', 'gallery', 'sqlite3', 'repository', 'web')) for value in imports), name)
            if name == 'report_notes_pdf.py':
                self.assertNotIn('pdfplumber', imports)
                self.assertNotIn('report_table_pdf', imports)


if __name__ == '__main__':
    unittest.main()
