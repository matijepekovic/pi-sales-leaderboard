"""PDF preflight is application-owned, not part of a particular office renderer."""
from pathlib import Path
from pypdf import PdfReader


def page_count(path: Path) -> int:
    with path.open('rb') as stream:
        reader = PdfReader(stream, strict=False)
        if reader.is_encrypted:
            raise ValueError('ENCRYPTED PDF CANNOT BE PRINTED AUTOMATICALLY')
        count = len(reader.pages)
        if not count:
            raise ValueError('NO PDF PAGES FOUND')
        return count
