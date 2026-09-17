"""Focused invariant: one gallery PDF owns one document date."""
from pathlib import Path

from printer_app.gallery import recognition


def test_known_pdf_date_skips_per_card_date_detection(monkeypatch):
    calls = []

    def detect(words, height):
        calls.append((words, height))
        return '2026-09-15', 'printed'

    monkeypatch.setattr(recognition, 'printed_date', detect)
    assert recognition.document_date([], 500, '2026-09-14') == ('2026-09-14', 'printed')
    assert calls == []
    assert recognition.document_date([], 500) == ('2026-09-15', 'printed')
    assert len(calls) == 1


def test_pdf_processing_reuses_first_reliable_date_for_every_card():
    source = (Path(__file__).resolve().parents[1] / 'gallery' / 'processing.py').read_text()
    assert 'pdf_date = None' in source
    assert 'known_date=pdf_date' in source
    assert "pdf_date = reading['document_date']" in source
    assert "for item in manifest['items']:" in source
    assert "item['document_date'] = pdf_date" in source
    assert "item['date_status'] = 'printed'" in source
