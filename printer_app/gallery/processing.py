"""Resource-limited subprocess: Poppler -> line crops -> local Tesseract search text.

Runs under system Python with distro OpenCV/Pillow; never imports printer runtime.
Only finished crops and a manifest leave the temporary workspace. No cloud APIs.
"""
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
from recognition import recognize


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
    pdf_date = None
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
                    # A gallery PDF has one document date. Keep checking cards only
                    # until one reliable printed date is found, then reuse it.
                    reading = recognize(path, work, known_date=pdf_date)
                    if (pdf_date is None and reading.get('date_status') == 'printed'
                            and reading.get('document_date')):
                        pdf_date = reading['document_date']
                except (OSError, ValueError, subprocess.SubprocessError):
                    reading = dict(text='', lead_text='', document_date=None, date_status='needs-date')
                    manifest['warnings'].append(f'Page {page} crop {part}: search text unavailable')
                manifest['items'].append(dict(file=filename, page=page, part=part, bytes=size,
                    **reading))
            if not count:
                manifest['skipped'].append(page)
            pagefile.unlink(missing_ok=True)
            del raster
            report_progress(output, 'page-complete', page, pages, len(manifest['items']))
    if not manifest['items']:
        raise ValueError('No recognizable work-order boxes found; source discarded')
    if pdf_date:
        # Earlier crops may have been unreadable before a later crop established the
        # PDF date. Normalize every card to the same source-document date.
        for item in manifest['items']:
            item['document_date'] = pdf_date
            item['date_status'] = 'printed'
    report_progress(output, 'publish', pages, pages, len(manifest['items']))
    (output / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


if __name__ == '__main__':
    os.environ['OMP_THREAD_LIMIT'] = '1'
    cv2.setNumThreads(1)
    process(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
