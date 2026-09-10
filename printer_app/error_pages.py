"""Fixed one-page physical error sheets; independent of Office conversion."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

from .config import clean_text


def wrapped_lines(text: str, width: float = 528) -> list[str]:
    """Wrap by actual font width, including exceptionally wide/unbroken filenames."""
    result, line = [], ''
    for character in text:
        if line and stringWidth(line + character, 'Helvetica', 11) > width:
            split = line.rfind(' ')
            if split > len(line) // 2:
                result.append(line[:split])
                line = line[split + 1:]
            else:
                result.append(line)
                line = ''
        line += character
    return result + ([line] if line else []) or ['-']


def error_page(path: Path, job: dict, reason: str, timezone: str, *, test: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    page = canvas.Canvas(str(path), pagesize=letter, pageCompression=1)
    page.setTitle('Printer app test' if test else 'PRINT ERROR')
    page.setFont('Helvetica-Bold', 30)
    page.drawString(42, 738, 'TEST PRINT' if test else 'PRINT ERROR')
    page.setFont('Helvetica', 10)
    page.drawString(42, 714, 'Printer automation | no approval required')
    y = 682
    fields = [
        ('File', job.get('filename') or 'Printer app test'),
        ('Source Email', job.get('subject') or '(local test)'),
        ('Sender', job.get('sender') or '(local)'),
        ('Sub Status', job.get('substatus') or '(not applicable)'),
        ('Reason', reason),
        ('Timestamp', datetime.now(ZoneInfo(timezone)).strftime('%Y-%m-%d %H:%M:%S %Z')),
        ('Job', str(job.get('id', ''))),
    ]
    for label, text in fields:
        page.setFont('Helvetica-Bold', 11)
        page.drawString(42, y, label + ':')
        y -= 16
        page.setFont('Helvetica', 11)
        # Bounded, ASCII-safe text; full original text remains in the authenticated UI.
        text = clean_text(text, 2500).encode('ascii', 'replace').decode().replace('\n', ' ')
        lines = wrapped_lines(text)
        maximum = 7 if label == 'Reason' else 3
        if len(lines) > maximum:
            lines = lines[:maximum]
            lines[-1] = lines[-1][:-5] + ' ...'
        for line in lines:
            page.drawString(42, y, line)
            y -= 14
        y -= 12
    page.setFont('Helvetica', 9)
    page.drawString(42, 30, 'Check Print Control for complete details. This error sheet contains one page.')
    page.showPage()
    page.save()
    return path
