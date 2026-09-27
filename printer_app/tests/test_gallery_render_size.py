"""Synthetic PDF metadata regressions; page rendering remains owned by Poppler."""
import builtins
from types import SimpleNamespace

import pytest

from printer_app.tests.test_gallery_pdf_date import _processor


def _pdf(path, *, width=600, height=800, change=None):
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=400)
    image = DecodedStreamObject()
    image.update({
        NameObject('/Type'): NameObject('/XObject'),
        NameObject('/Subtype'): NameObject('/Image'),
        NameObject('/Width'): NumberObject(width),
        NameObject('/Height'): NumberObject(height),
        NameObject('/ColorSpace'): NameObject('/DeviceGray'),
        NameObject('/BitsPerComponent'): NumberObject(8),
    })
    image.set_data(b'\xff')  # Only metadata is inspected; no image extraction.
    objects = DictionaryObject({NameObject('/Scan'): writer._add_object(image)})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): objects})
    content = b'q 300 0 0 400 0 0 cm /Scan Do Q'
    if change == 'text':
        content += b' BT (Overlay) Tj ET'
    elif change == 'vector':
        content += b' 10 10 m 20 20 l S'
    elif change == 'multiple-images':
        objects[NameObject('/Other')] = writer._add_object(DecodedStreamObject())
    elif change == 'mask':
        image[NameObject('/Mask')] = ArrayObject([NumberObject(0), NumberObject(0)])
    elif change == 'soft-mask':
        image[NameObject('/SMask')] = writer._add_object(DecodedStreamObject())
    elif change == 'crop':
        page.cropbox.upper_right = (290, 390)
    elif change == 'rotation':
        page.rotate(90)
    elif change == 'annotation':
        page[NameObject('/Annots')] = ArrayObject([DictionaryObject()])
    elif change == 'partial':
        content = b'q 280 0 0 400 10 0 cm /Scan Do Q'
    elif change == 'skew':
        content = b'q 300 1 0 400 0 0 cm /Scan Do Q'
    elif change == 'bad-name':
        content = b'q 300 0 0 400 0 0 cm /Missing Do Q'
    elif change == 'bad-matrix':
        content = b'q 300 0 400 0 0 cm /Scan Do Q'
    elif change == 'vector-only':
        content = b'10 10 m 20 20 l S'
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)


@pytest.mark.parametrize('width,height,expected', [(600, 800, 800), (3600, 4800, 3300)])
def test_only_full_page_raster_uses_native_size_without_extraction(
        tmp_path, monkeypatch, width, height, expected):
    processor, _, _ = _processor(monkeypatch)
    source = tmp_path / 'raster.pdf'
    _pdf(source, width=width, height=height)

    assert processor.native_render_sizes(source, 1) == {1: expected}


@pytest.mark.parametrize('change', [
    'text', 'vector', 'multiple-images', 'mask', 'soft-mask', 'crop', 'rotation',
    'annotation', 'partial', 'skew', 'bad-name', 'bad-matrix', 'vector-only',
])
def test_mixed_transformed_or_unrecognized_page_keeps_original_render_size(
        tmp_path, monkeypatch, change):
    processor, _, _ = _processor(monkeypatch)
    source = tmp_path / 'other.pdf'
    _pdf(source, change=change)

    assert processor.native_render_sizes(source, 1) == {}


def test_unavailable_reader_or_malformed_pdf_keeps_poppler_fallback(tmp_path, monkeypatch):
    processor, _, _ = _processor(monkeypatch)
    source = tmp_path / 'scan.pdf'
    source.write_bytes(b'not a PDF')
    assert processor.native_render_sizes(source, 1) == {}
    _pdf(source)
    assert processor.native_render_sizes(source, 2) == {}
    original = builtins.__import__

    def missing_reader(name, *args, **kwargs):
        if name == 'pypdf':
            raise ModuleNotFoundError(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', missing_reader)
    assert processor.native_render_sizes(source, 1) == {}


def test_processing_renders_entire_native_page_with_poppler(tmp_path, monkeypatch):
    processor, np, image_module = _processor(monkeypatch)
    source = tmp_path / 'scan.pdf'
    _pdf(source)
    commands = []

    def poppler(command, **kwargs):
        commands.append(command)
        if command[0] == 'pdfinfo':
            return SimpleNamespace(stdout='Pages: 1\n')
        assert command[0] == 'pdftoppm'
        image_module.new('RGB', (600, 800), 'white').save(command[-1] + '.png')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(processor.subprocess, 'run', poppler)
    monkeypatch.setattr(processor.shutil, 'disk_usage', lambda path: SimpleNamespace(free=2**30))
    monkeypatch.setattr(processor, 'deskew_page', lambda image: image)
    monkeypatch.setattr(processor, 'orient_work_order_page', lambda image: image)
    monkeypatch.setattr(processor, 'is_dense_grid_page', lambda image: False)
    monkeypatch.setattr(processor, 'cut_forms', lambda image: iter([(1, image)]))
    monkeypatch.setattr(processor, 'recognize', lambda *args, **kwargs: dict(
        text='', document_date=None, date_status='needs-date'))

    processor.process(source, tmp_path / 'output', 1048576)

    assert len(commands) == 2
    render = commands[1]
    assert render[render.index('-scale-to') + 1] == '800'
    assert str(source) in render
