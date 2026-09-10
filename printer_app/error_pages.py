"""A fixed one-page physical error sheet, independent of LibreOffice."""
from datetime import datetime
from pathlib import Path
import textwrap
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from .converter import page_count


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
        text = ' '.join(str(value).replace('\x00', '').split())
        lines = textwrap.wrap(text, width=66, break_long_words=True) or ['-']
        maximum = 5 if name == 'Reason' else 3
        if len(lines) > maximum:
            lines = lines[:maximum]
            lines[-1] = lines[-1][:62] + '...'
        for line in lines:
            canvas.drawString(42, y, line)
            y -= 16
        y -= 15
    canvas.setFont(font, 9)
    canvas.drawString(42, 30, 'Full details and previews are available in the independent Print Control interface.')
    canvas.showPage()
    canvas.save()
    if page_count(path) != 1:
        raise RuntimeError('Internal error-sheet preflight failed')
