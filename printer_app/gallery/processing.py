"""Resource-limited subprocess: Poppler -> line crops -> local Tesseract search text.

Runs under system Python with distro OpenCV/Pillow; never imports printer runtime.
Completed pages are checkpointed in the gallery-owned work directory so a service
restart or Pi reboot resumes from the next page instead of starting the PDF over.
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
from cropper import cut_forms, deskew_page, is_dense_grid_page
from recognition import recognize
from processing_contract import RETRYABLE_EXIT


CHECKPOINT_VERSION = 1
CHECKPOINT = 'checkpoint.json'
MANIFEST = 'manifest.json'
CROP_FILE = re.compile(r'^\d{4}-\d{3}\.png$')


def write_json_atomic(path, value):
    temporary = path.with_name('.' + path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    try:
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        pass


def report_progress(output, stage, page=0, pages=0, crops=0):
    write_json_atomic(
        output / 'progress.json',
        dict(stage=stage, page=page, pages=pages, crops=crops),
    )


def fresh_manifest():
    return {'items': [], 'skipped': [], 'warnings': []}


def clear_resume_state(output):
    for path in output.iterdir():
        if path.is_symlink():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif path.name in (CHECKPOINT, MANIFEST, '.' + CHECKPOINT + '.tmp',
                           '.' + MANIFEST + '.tmp') or CROP_FILE.fullmatch(path.name):
            path.unlink(missing_ok=True)


def cleanup_uncommitted(output, manifest):
    committed = {str(item.get('file', '')) for item in manifest['items']}
    for path in output.iterdir():
        if path.is_symlink():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif CROP_FILE.fullmatch(path.name) and path.name not in committed:
            path.unlink(missing_ok=True)


def load_checkpoint(output, pages):
    path = output / CHECKPOINT
    if not path.is_file():
        clear_resume_state(output)
        return fresh_manifest(), 0, None, 0
    try:
        if path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('invalid checkpoint')
        state = json.loads(path.read_text(encoding='utf-8'))
        if state.get('version') != CHECKPOINT_VERSION or state.get('pages') != pages:
            raise ValueError('checkpoint does not match source')
        completed = int(state.get('completed_page', -1))
        if not 0 <= completed <= pages:
            raise ValueError('invalid completed page')
        manifest = state.get('manifest')
        if (not isinstance(manifest, dict)
                or not isinstance(manifest.get('items'), list)
                or not isinstance(manifest.get('skipped'), list)
                or not isinstance(manifest.get('warnings'), list)):
            raise ValueError('invalid checkpoint manifest')
        used = 0
        for item in manifest['items']:
            if not isinstance(item, dict):
                raise ValueError('invalid checkpoint item')
            filename = str(item.get('file', ''))
            page = int(item.get('page', 0))
            if not CROP_FILE.fullmatch(filename) or not 1 <= page <= completed:
                raise ValueError('invalid committed crop')
            crop = output / filename
            if crop.is_symlink() or not crop.is_file():
                raise ValueError('committed crop is missing')
            size = crop.stat().st_size
            if int(item.get('bytes', -1)) != size:
                raise ValueError('committed crop size changed')
            used += size
        skipped = [int(value) for value in manifest['skipped']]
        if any(value < 1 or value > completed for value in skipped):
            raise ValueError('invalid skipped-page checkpoint')
        manifest['skipped'] = skipped
        pdf_date = state.get('pdf_date') or None
        if pdf_date is not None and (not isinstance(pdf_date, str) or len(pdf_date) > 32):
            raise ValueError('invalid checkpoint date')
        cleanup_uncommitted(output, manifest)
        return manifest, completed, pdf_date, used
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        clear_resume_state(output)
        return fresh_manifest(), 0, None, 0


def save_checkpoint(output, pages, completed_page, manifest, pdf_date):
    write_json_atomic(
        output / CHECKPOINT,
        dict(
            version=CHECKPOINT_VERSION,
            pages=pages,
            completed_page=completed_page,
            pdf_date=pdf_date,
            manifest=manifest,
        ),
    )


def process(source, output, budget):
    output.mkdir(parents=True, exist_ok=True)
    report_progress(output, 'inspect')
    info = subprocess.run(
        ['pdfinfo', str(source)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    match = re.search(r'^Pages:\s+(\d+)', info.stdout, re.M)
    if not match or not 1 <= int(match[1]) <= 100:
        raise ValueError('PDF must contain 1–100 pages')

    pages = int(match[1])
    manifest, completed_page, pdf_date, used = load_checkpoint(output, pages)

    # The only durable work state is page-complete. If the previous process died
    # halfway through page N, that page has no checkpoint and is rendered again.
    with tempfile.TemporaryDirectory(dir=output) as temp:
        work = Path(temp)
        for page in range(completed_page + 1, pages + 1):
            if shutil.disk_usage(output).free < 512 * 1048576 + 64 * 1048576:
                raise OSError('Not enough gallery processing space')
            report_progress(output, 'render', page, pages, len(manifest['items']))
            prefix = work / 'page'
            subprocess.run(
                [
                    'pdftoppm', '-f', str(page), '-l', str(page), '-singlefile',
                    '-scale-to', '3300', '-png', str(source), str(prefix),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            pagefile = prefix.with_suffix('.png')
            with Image.open(pagefile) as image:
                raster = np.array(image.convert('RGB'))

            # Normalize printed rule geometry before form detection.
            raster = deskew_page(raster)
            report_progress(output, 'crop', page, pages, len(manifest['items']))

            if is_dense_grid_page(raster):
                manifest['skipped'].append(page)
                pagefile.unlink(missing_ok=True)
                del raster
                report_progress(output, 'page-complete', page, pages, len(manifest['items']))
                save_checkpoint(output, pages, page, manifest, pdf_date)
                continue

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
                    reading = dict(
                        text='',
                        lead_text='',
                        document_date=None,
                        date_status='needs-date',
                    )
                    manifest['warnings'].append(
                        f'Page {page} crop {part}: search text unavailable'
                    )
                manifest['items'].append(
                    dict(file=filename, page=page, part=part, bytes=size, **reading)
                )

            if not count:
                manifest['skipped'].append(page)
            pagefile.unlink(missing_ok=True)
            del raster
            report_progress(output, 'page-complete', page, pages, len(manifest['items']))
            save_checkpoint(output, pages, page, manifest, pdf_date)

    if not manifest['items']:
        raise ValueError('No recognizable work-order boxes found; source discarded')

    if pdf_date:
        # Earlier crops may have been unreadable before a later crop established the
        # PDF date. Normalize every card to the same source-document date.
        for item in manifest['items']:
            item['document_date'] = pdf_date
            item['date_status'] = 'printed'

    save_checkpoint(output, pages, pages, manifest, pdf_date)
    report_progress(output, 'publish', pages, pages, len(manifest['items']))
    write_json_atomic(output / MANIFEST, manifest)


if __name__ == '__main__':
    os.environ['OMP_THREAD_LIMIT'] = '1'
    cv2.setNumThreads(1)
    try:
        process(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
    except (subprocess.TimeoutExpired, OSError, MemoryError):
        # Runtime/tool/storage interruptions are not source-data failures.
        # The worker keeps the PDF plus every page-complete checkpoint and retries.
        raise SystemExit(RETRYABLE_EXIT)
