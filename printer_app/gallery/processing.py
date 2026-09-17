"""Resource-limited subprocess: Poppler -> line crops -> local Tesseract search text.

Runs under system Python with distro OpenCV/Pillow; never imports printer runtime.
Only finished crops and a manifest leave the temporary workspace. No cloud APIs.
"""
import csv
from datetime import date
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from PIL import Image
import cv2
import numpy as np

# Executed as a script, deliberately without loading the printer package/runtime.
from cropper import cut_forms


def printed_date(words, height):
    # Dates are for retention, not cutting. Only unambiguous dates in the printed
    # header are considered. Repeated matching dates provide corroboration.
    header = ' '.join(w['text'] for w in words if int(w['top']) < height * .27)
    readings = []
    for m in re.finditer(r'\b(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\b', header):
        try:
            readings.append(date(*map(int, m.groups())).isoformat())
        except ValueError:
            pass
    months = 'jan feb mar apr may jun jul aug sep oct nov dec'.split()
    for m in re.finditer(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(20\d{2})\b', header, re.I):
        try:
            readings.append(date(int(m[3]), months.index(m[1].lower()) + 1, int(m[2])).isoformat())
        except ValueError:
            pass
    if len(readings) >= 2 and len(set(readings)) == 1:
        return readings[0], 'printed'
    return None, 'needs-date'


def recognize(path, work):
    # Only a disposable OCR copy loses rules; the saved gallery image is untouched.
    source = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    h, w = source.shape
    ink = cv2.threshold(source, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    rules = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(30, w // 25)), np.uint8))
    rules |= cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(30, h // 12), 1), np.uint8))
    source[cv2.dilate(rules, np.ones((3, 3), np.uint8)) > 0] = 255
    ocr_copy = work / 'ocr.png'
    cv2.imwrite(str(ocr_copy), source)
    result = subprocess.run(['tesseract', str(ocr_copy), 'stdout', '-l', 'eng', '--psm', '6', 'tsv'],
        check=True, capture_output=True, text=True, timeout=120)
    words = [r for r in csv.DictReader(io.StringIO(result.stdout), delimiter='\t')
             if r.get('text', '').strip() and float(r.get('conf', '-1')) >= 0]
    text = ' '.join(r['text'] for r in words)[:100000]
    # Low-confidence words can assist search, but never authorize date expiry.
    confident = [r for r in words if float(r['conf']) >= 70]
    docdate, state = printed_date(confident, h)
    ocr_copy.unlink(missing_ok=True)
    return text, docdate, state


def report_progress(output, stage, page=0, pages=0, crops=0):
    temporary = output / '.progress.json'
    temporary.write_text(json.dumps(dict(stage=stage, page=page, pages=pages, crops=crops)), encoding='utf-8')
    temporary.replace(output / 'progress.json')


def process(source, output, budget):
    output.mkdir(parents=True, exist_ok=True)
    report_progress(output, 'inspect')
    info = subprocess.run(['pdfinfo', str(source)], check=True, capture_output=True, text=True, timeout=30)
    match = re.search(r'^Pages:\s+(\d+)', info.stdout, re.M)
    if not match or not 1 <= int(match[1]) <= 100:
        raise ValueError('PDF must contain 1–100 pages')
    manifest = {'items': [], 'skipped': [], 'warnings': []}
    used = 0
    pages = int(match[1])
    with tempfile.TemporaryDirectory(dir=output) as temp:
        work = Path(temp)
        for page in range(1, int(match[1]) + 1):
            if shutil.disk_usage(output).free < 512 * 1048576 + 64 * 1048576:
                raise OSError('Not enough gallery processing space')
            report_progress(output, 'render', page, pages, len(manifest['items']))
            prefix = work / 'page'
            subprocess.run(['pdftoppm', '-f', str(page), '-l', str(page), '-singlefile',
                '-scale-to', '3300', '-png', str(source), str(prefix)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
            pagefile = prefix.with_suffix('.png')
            with Image.open(pagefile) as image:
                raster = np.array(image.convert('RGB'))
            report_progress(output, 'crop', page, pages, len(manifest['items']))
            count = 0
            for part, crop in cut_forms(raster):
                count += 1
                filename = f'{page:04d}-{part:03d}.png'
                path = output / filename
                Image.fromarray(crop).save(path, optimize=True)
                size = path.stat().st_size
                used += size
                if used > budget:
                    raise OSError('Rendered crops exceed gallery storage budget')
                report_progress(output, 'search', page, pages, len(manifest['items']))
                try:
                    text, docdate, state = recognize(path, work)
                except (OSError, ValueError, subprocess.SubprocessError):
                    text, docdate, state = '', None, 'needs-date'
                    manifest['warnings'].append(f'Page {page} crop {part}: search text unavailable')
                manifest['items'].append(dict(file=filename, page=page, part=part, bytes=size,
                    text=text, document_date=docdate, date_status=state))
            if not count:
                manifest['skipped'].append(page)
            pagefile.unlink(missing_ok=True)
            del raster
            report_progress(output, 'page-complete', page, pages, len(manifest['items']))
    if not manifest['items']:
        raise ValueError('No recognizable work-order boxes found; source discarded')
    report_progress(output, 'publish', pages, pages, len(manifest['items']))
    (output / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


if __name__ == '__main__':
    os.environ['OMP_THREAD_LIMIT'] = '1'
    cv2.setNumThreads(1)
    process(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
