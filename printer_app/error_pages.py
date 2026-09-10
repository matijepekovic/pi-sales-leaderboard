"""A fixed one-page physical error sheet, independent of LibreOffice."""
from datetime import datetime
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from .pdfs import page_count


def wrapped_lines(text, font, size=12, width=528, maximum=3):
    """Bound both actual glyph width and line count, including very long filenames."""
    text = ' '.join(str(text).replace('\x00', '').split()) or '-'
    result = []
    while text and len(result) < maximum:
        end = 0
        while end < len(text) and pdfmetrics.stringWidth(text[:end + 1], font, size) <= width:
            end += 1
        end = max(1, end)
        if end < len(text):
            space = text.rfind(' ', 0, end)
            if space > 0:
                end = space
        result.append(text[:end])
        text = text[end:].lstrip()
    if text:
        line = result[-1]
        while line and pdfmetrics.stringWidth(line + '...', font, size) > width:
            line = line[:-1]
        result[-1] = line + '...'
    return result


def error_page(path: Path, job: dict, reason: str, title='PRINT ERROR'):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    font = 'Helvetica'
    system_font = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if system_font.is_file():
        if 'PrinterSans' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('PrinterSans', str(system_font)))
        font = 'PrinterSans'
    canvas = Canvas(str(path), pagesize=letter)
    canvas.setTitle(title)
    canvas.setFont(font, 26)
    canvas.drawString(42, 744, title)
    canvas.line(42, 726, 570, 726)
    fields = [
        ('File', job.get('filename', '')),
        ('Source Email', job.get('subject', '')),
        ('Sender', job.get('sender', '')),
        ('Sub Status', job.get('substatus') or '(not applicable)'),
        ('Reason', reason),
        ('Timestamp', datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')),
        ('Job ID', job.get('id', '')),
    ]
    y = 696
    for name, value in fields:
        canvas.setFont(font, 10)
        canvas.drawString(42, y, name.upper())
        y -= 18
        canvas.setFont(font, 12)
        for line in wrapped_lines(value, font, maximum=5 if name == 'Reason' else 3):
            canvas.drawString(42, y, line)
            y -= 16
        y -= 15
    canvas.setFont(font, 9)
    canvas.drawString(42, 30, 'Full details and previews are available in the independent Print Control interface.')
    canvas.showPage()
    canvas.save()
    if page_count(path) != 1:
        raise RuntimeError('Internal error-sheet preflight failed')
