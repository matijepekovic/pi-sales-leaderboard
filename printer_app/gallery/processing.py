"""Resource-limited subprocess: Poppler -> line crops -> local Tesseract search text.

Runs under system Python with distro OpenCV/Pillow; never imports printer runtime.
Completed pages are checkpointed in the gallery-owned work directory so a service
restart or Pi reboot resumes from the next page instead of starting the PDF over.
Only finished crops and a manifest leave the temporary workspace. No cloud APIs.
"""
import json
import math
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
from cropper import cut_forms, deskew_page, is_dense_grid_page, orient_work_order_page
from recognition import recognize
from processing_contract import RETRYABLE_EXIT


# Old OCR decisions could count the printed MOD Notes label as content and let
# a blank placeholder establish the scan's date. Re-read those cached pages.
CHECKPOINT_VERSION = 3
CHECKPOINT = 'checkpoint.json'
MANIFEST = 'manifest.json'
CROP_FILE = re.compile(r'^\\d{4}-\\d{3}\\.png$')
OCR_FILE = re.compile(r'^\\d{4}-\\d{3}\\.ocr\\.png$')
REVIEW_FILE = re.compile(r'^page-\\d{4}\\.review\\.png$')

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
    return {'items': [], 'skipped': [], 'warnings': [], 'review_pages': []}


def retain_review_page(output, pagefile, page, manifest, used, budget):
    """Keep one rendered page that produced no card so admins can inspect it."""
    filename = f'page-{page:04d}.review.png'
    target = output / filename
    shutil.copyfile(pagefile, target)
    size = target.stat().st_size
    used += size
    if used > budget:
        target.unlink(missing_ok=True)
        raise OSError('Rendered review pages exceed gallery storage budget')
    manifest['review_pages'].append(
        dict(page=page, file=filename, bytes=size, reason='no-recognized-forms')
    )
    return used


def clear_resume_state(output):
    for path in output.iterdir():
        if path.is_symlink():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif path.name in (CHECKPOINT, MANIFEST, '.' + CHECKPOINT + '.tmp',
                           '.' + MANIFEST + '.tmp') or CROP_FILE.fullmatch(path.name) or OCR_FILE.fullmatch(path.name) or REVIEW_FILE.fullmatch(path.name):
            path.unlink(missing_ok=True)


def cleanup_uncommitted(output, manifest):
    committed = {str(item.get('file', '')) for item in manifest['items']}
    committed.update(str(item.get('ocr_file', '')) for item in manifest['items'] if item.get('ocr_file'))
    committed.update(str(item.get('file', '')) for item in manifest.get('review_pages', ()))
    for path in output.iterdir():
        if path.is_symlink():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif ((CROP_FILE.fullmatch(path.name) or OCR_FILE.fullmatch(path.name) or REVIEW_FILE.fullmatch(path.name))
              and path.name not in committed):
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
                or not isinstance(manifest.get('warnings'), list)
                or not isinstance(manifest.get('review_pages'), list)):
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
            ocr_filename = str(item.get('ocr_file', '') or '')
            if ocr_filename:
                if not OCR_FILE.fullmatch(ocr_filename):
                    raise ValueError('invalid OCR diagnostic file')
                ocr_path = output / ocr_filename
                if ocr_path.is_symlink() or not ocr_path.is_file():
                    raise ValueError('OCR diagnostic file is missing')
                used += ocr_path.stat().st_size
        skipped = [int(value) for value in manifest['skipped']]
        if any(value < 1 or value > completed for value in skipped):
            raise ValueError('invalid skipped-page checkpoint')
        manifest['skipped'] = skipped
        review_pages = []
        for entry in manifest['review_pages']:
            if not isinstance(entry, dict):
                raise ValueError('invalid review-page checkpoint')
            filename = str(entry.get('file', ''))
            page = int(entry.get('page', 0))
            if not REVIEW_FILE.fullmatch(filename) or page not in skipped:
                raise ValueError('invalid review-page artifact')
            artifact = output / filename
            if artifact.is_symlink() or not artifact.is_file():
                raise ValueError('review-page artifact is missing')
            size = artifact.stat().st_size
            if int(entry.get('bytes', -1)) != size:
                raise ValueError('review-page artifact size changed')
            used += size
            review_pages.append(dict(page=page, file=filename, bytes=size,
                                     reason='no-recognized-forms'))
        manifest['review_pages'] = review_pages
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


def native_render_sizes(source, pages):
    """Avoid resampling a sole full-page scan before OCR; keep Poppler as renderer.

    A page containing anything beyond one ordinary image keeps the existing
    render size. In particular, image metadata alone cannot establish that a
    mixed page has no text, vector marks, annotations, masks or transformations.
    Metadata inspection is optional so an unavailable or damaged PDF reader
    cannot prevent the established Poppler path from processing the document.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(source)
        if len(reader.pages) != pages:
            return {}
    except Exception:
        return {}

    sizes = {}
    for index in range(1, pages + 1):
        try:
            page = reader.pages[index - 1]
            if page.get('/Rotate', 0) or page.get('/UserUnit', 1) != 1 or page.get('/Annots'):
                continue
            media, crop = tuple(map(float, page.mediabox)), tuple(map(float, page.cropbox))
            if not all(math.isfinite(value) for value in media + crop):
                continue
            if any(abs(a - b) > .01 for a, b in zip(media, crop)):
                continue
            operations = page.get_contents().operations
            if [operator for _, operator in operations] != [b'q', b'cm', b'Do', b'Q']:
                continue
            if operations[0][0] or operations[3][0] or len(operations[2][0]) != 1:
                continue
            matrix = tuple(map(float, operations[1][0]))
            expected = (media[2] - media[0], 0, 0, media[3] - media[1], media[0], media[1])
            if (len(matrix) != 6 or not all(math.isfinite(value) for value in matrix)
                    or any(abs(a - b) > .01 for a, b in zip(matrix, expected))):
                continue
            objects = page['/Resources']['/XObject'].get_object()
            if len(objects) != 1:
                continue
            image = objects[operations[2][0][0]].get_object()
            if (image.get('/Subtype') != '/Image' or image.get('/ImageMask')
                    or image.get('/Mask') is not None or image.get('/SMask') is not None):
                continue
            width, height = int(image['/Width']), int(image['/Height'])
            if width <= 0 or height <= 0 or min(expected[0], expected[3]) <= 0:
                continue
            if abs((width / height) / (expected[0] / expected[3]) - 1) > .005:
                continue
            sizes[index] = min(3300, max(width, height))
        except Exception:
            # Unrecognized page metadata uses the complete existing renderer.
            continue
    return sizes


def process(source, output, budget, *, origin='scan'):
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
    render_sizes = native_render_sizes(source, pages)

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
                    '-scale-to', str(render_sizes.get(page, 3300)), '-png', str(source), str(prefix),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=300,
            )
            pagefile = prefix.with_suffix('.png')
            with Image.open(pagefile) as image:
                raster = np.array(image.convert('RGB'))

            # Normalize small scan skew, then use the known form geometry
            # to correct a full 180-degree upside-down scan before cropping/OCR.
            raster = deskew_page(raster)
            raster = orient_work_order_page(raster)
            report_progress(output, 'crop', page, pages, len(manifest['items']))

            if is_dense_grid_page(raster):
                manifest['skipped'].append(page)
                used = retain_review_page(output, pagefile, page, manifest, used, budget)
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
                ocr_filename = f'{page:04d}-{part:03d}.ocr.png'
                ocr_path = output / ocr_filename
                try:
                    # A gallery PDF has one document date. Keep checking cards only
                    # until one reliable printed date is found, then reuse it.
                    reading = recognize(
                        path, work, known_date=pdf_date, debug_path=ocr_path,
                    )
                    usable_date = (origin == 'morning' or
                                   reading.get('mod_notes_present', True) is True)
                    if (usable_date and pdf_date is None and reading.get('date_status') == 'printed'
                            and reading.get('document_date')):
                        pdf_date = reading['document_date']
                except (OSError, ValueError, subprocess.SubprocessError):
                    ocr_path.unlink(missing_ok=True)
                    reading = dict(
                        text='',
                        lead_text='',
                        document_date=None,
                        date_status='needs-date',
                        work_order_candidates=(),
                        work_order_reads=(),
                        mod_notes_present=None,
                    )
                    manifest['warnings'].append(
                        f'Page {page} crop {part}: search text unavailable'
                    )
                if ocr_path.is_file():
                    used += ocr_path.stat().st_size
                    if used > budget:
                        raise OSError('Rendered crops exceed gallery storage budget')
                    reading['ocr_file'] = ocr_filename
                manifest['items'].append(
                    dict(file=filename, page=page, part=part, bytes=size, **reading)
                )

            if not count:
                manifest['skipped'].append(page)
                used = retain_review_page(output, pagefile, page, manifest, used, budget)
            pagefile.unlink(missing_ok=True)
            del raster
            report_progress(output, 'page-complete', page, pages, len(manifest['items']))
            save_checkpoint(output, pages, page, manifest, pdf_date)

    if not manifest['items'] and not manifest['review_pages']:
        raise ValueError('No reviewable pages were rendered from this PDF')

    if pdf_date:
        # Earlier crops may have been unreadable before a later crop established the
        # PDF date. Normalize every card to the same source-document date.
        for item in manifest['items']:
            item['document_date'] = pdf_date
            item['date_status'] = 'printed'
            if 'work_order_evidence' in item:
                # All cards share the independently established printed PDF
                # date, including cards read before that date was available.
                item['work_order_evidence']['dates'] = (pdf_date,)

    save_checkpoint(output, pages, pages, manifest, pdf_date)
    report_progress(output, 'publish', pages, pages, len(manifest['items']))
    write_json_atomic(output / MANIFEST, manifest)


if __name__ == '__main__':
    os.environ['OMP_THREAD_LIMIT'] = '1'
    cv2.setNumThreads(1)
    try:
        process(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]),
                origin=sys.argv[4] if len(sys.argv) > 4 else 'scan')
    except (subprocess.TimeoutExpired, OSError, MemoryError):
        # Runtime/tool/storage interruptions are not source-data failures.
        # The worker keeps the PDF plus every page-complete checkpoint and retries.
        raise SystemExit(RETRYABLE_EXIT)
)
REVIEW_FILE = re.compile(r'^page-\\d{4}\\.review\\.png

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
    return {'items': [], 'skipped': [], 'warnings': [], 'review_pages': []}


def retain_review_page(output, pagefile, page, manifest, used, budget):
    """Keep one rendered page that produced no card so admins can inspect it."""
    filename = f'page-{page:04d}.review.png'
    target = output / filename
    shutil.copyfile(pagefile, target)
    size = target.stat().st_size
    used += size
    if used > budget:
        target.unlink(missing_ok=True)
        raise OSError('Rendered review pages exceed gallery storage budget')
    manifest['review_pages'].append(
        dict(page=page, file=filename, bytes=size, reason='no-recognized-forms')
    )
    return used


def clear_resume_state(output):
    for path in output.iterdir():
        if path.is_symlink():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif path.name in (CHECKPOINT, MANIFEST, '.' + CHECKPOINT + '.tmp',
                           '.' + MANIFEST + '.tmp') or CROP_FILE.fullmatch(path.name) or OCR_FILE.fullmatch(path.name) or REVIEW_FILE.fullmatch(path.name):
            path.unlink(missing_ok=True)


def cleanup_uncommitted(output, manifest):
    committed = {str(item.get('file', '')) for item in manifest['items']}
    committed.update(str(item.get('ocr_file', '')) for item in manifest['items'] if item.get('ocr_file'))
    committed.update(str(item.get('file', '')) for item in manifest.get('review_pages', ()))
    for path in output.iterdir():
        if path.is_symlink():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif ((CROP_FILE.fullmatch(path.name) or OCR_FILE.fullmatch(path.name) or REVIEW_FILE.fullmatch(path.name))
              and path.name not in committed):
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
                or not isinstance(manifest.get('warnings'), list)
                or not isinstance(manifest.get('review_pages'), list)):
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
            ocr_filename = str(item.get('ocr_file', '') or '')
            if ocr_filename:
                if not OCR_FILE.fullmatch(ocr_filename):
                    raise ValueError('invalid OCR diagnostic file')
                ocr_path = output / ocr_filename
                if ocr_path.is_symlink() or not ocr_path.is_file():
                    raise ValueError('OCR diagnostic file is missing')
                used += ocr_path.stat().st_size
        skipped = [int(value) for value in manifest['skipped']]
        if any(value < 1 or value > completed for value in skipped):
            raise ValueError('invalid skipped-page checkpoint')
        manifest['skipped'] = skipped
        review_pages = []
        for entry in manifest['review_pages']:
            if not isinstance(entry, dict):
                raise ValueError('invalid review-page checkpoint')
            filename = str(entry.get('file', ''))
            page = int(entry.get('page', 0))
            if not REVIEW_FILE.fullmatch(filename) or page not in skipped:
                raise ValueError('invalid review-page artifact')
            artifact = output / filename
            if artifact.is_symlink() or not artifact.is_file():
                raise ValueError('review-page artifact is missing')
            size = artifact.stat().st_size
            if int(entry.get('bytes', -1)) != size:
                raise ValueError('review-page artifact size changed')
            used += size
            review_pages.append(dict(page=page, file=filename, bytes=size,
                                     reason='no-recognized-forms'))
        manifest['review_pages'] = review_pages
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


def native_render_sizes(source, pages):
    """Avoid resampling a sole full-page scan before OCR; keep Poppler as renderer.

    A page containing anything beyond one ordinary image keeps the existing
    render size. In particular, image metadata alone cannot establish that a
    mixed page has no text, vector marks, annotations, masks or transformations.
    Metadata inspection is optional so an unavailable or damaged PDF reader
    cannot prevent the established Poppler path from processing the document.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(source)
        if len(reader.pages) != pages:
            return {}
    except Exception:
        return {}

    sizes = {}
    for index in range(1, pages + 1):
        try:
            page = reader.pages[index - 1]
            if page.get('/Rotate', 0) or page.get('/UserUnit', 1) != 1 or page.get('/Annots'):
                continue
            media, crop = tuple(map(float, page.mediabox)), tuple(map(float, page.cropbox))
            if not all(math.isfinite(value) for value in media + crop):
                continue
            if any(abs(a - b) > .01 for a, b in zip(media, crop)):
                continue
            operations = page.get_contents().operations
            if [operator for _, operator in operations] != [b'q', b'cm', b'Do', b'Q']:
                continue
            if operations[0][0] or operations[3][0] or len(operations[2][0]) != 1:
                continue
            matrix = tuple(map(float, operations[1][0]))
            expected = (media[2] - media[0], 0, 0, media[3] - media[1], media[0], media[1])
            if (len(matrix) != 6 or not all(math.isfinite(value) for value in matrix)
                    or any(abs(a - b) > .01 for a, b in zip(matrix, expected))):
                continue
            objects = page['/Resources']['/XObject'].get_object()
            if len(objects) != 1:
                continue
            image = objects[operations[2][0][0]].get_object()
            if (image.get('/Subtype') != '/Image' or image.get('/ImageMask')
                    or image.get('/Mask') is not None or image.get('/SMask') is not None):
                continue
            width, height = int(image['/Width']), int(image['/Height'])
            if width <= 0 or height <= 0 or min(expected[0], expected[3]) <= 0:
                continue
            if abs((width / height) / (expected[0] / expected[3]) - 1) > .005:
                continue
            sizes[index] = min(3300, max(width, height))
        except Exception:
            # Unrecognized page metadata uses the complete existing renderer.
            continue
    return sizes


def process(source, output, budget, *, origin='scan'):
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
    render_sizes = native_render_sizes(source, pages)

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
                    '-scale-to', str(render_sizes.get(page, 3300)), '-png', str(source), str(prefix),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=300,
            )
            pagefile = prefix.with_suffix('.png')
            with Image.open(pagefile) as image:
                raster = np.array(image.convert('RGB'))

            # Normalize small scan skew, then use the known form geometry
            # to correct a full 180-degree upside-down scan before cropping/OCR.
            raster = deskew_page(raster)
            raster = orient_work_order_page(raster)
            report_progress(output, 'crop', page, pages, len(manifest['items']))

            if is_dense_grid_page(raster):
                manifest['skipped'].append(page)
                used = retain_review_page(output, pagefile, page, manifest, used, budget)
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
                ocr_filename = f'{page:04d}-{part:03d}.ocr.png'
                ocr_path = output / ocr_filename
                try:
                    # A gallery PDF has one document date. Keep checking cards only
                    # until one reliable printed date is found, then reuse it.
                    reading = recognize(
                        path, work, known_date=pdf_date, debug_path=ocr_path,
                    )
                    usable_date = (origin == 'morning' or
                                   reading.get('mod_notes_present', True) is True)
                    if (usable_date and pdf_date is None and reading.get('date_status') == 'printed'
                            and reading.get('document_date')):
                        pdf_date = reading['document_date']
                except (OSError, ValueError, subprocess.SubprocessError):
                    ocr_path.unlink(missing_ok=True)
                    reading = dict(
                        text='',
                        lead_text='',
                        document_date=None,
                        date_status='needs-date',
                        work_order_candidates=(),
                        work_order_reads=(),
                        mod_notes_present=None,
                    )
                    manifest['warnings'].append(
                        f'Page {page} crop {part}: search text unavailable'
                    )
                if ocr_path.is_file():
                    used += ocr_path.stat().st_size
                    if used > budget:
                        raise OSError('Rendered crops exceed gallery storage budget')
                    reading['ocr_file'] = ocr_filename
                manifest['items'].append(
                    dict(file=filename, page=page, part=part, bytes=size, **reading)
                )

            if not count:
                manifest['skipped'].append(page)
                used = retain_review_page(output, pagefile, page, manifest, used, budget)
            pagefile.unlink(missing_ok=True)
            del raster
            report_progress(output, 'page-complete', page, pages, len(manifest['items']))
            save_checkpoint(output, pages, page, manifest, pdf_date)

    if not manifest['items'] and not manifest['review_pages']:
        raise ValueError('No reviewable pages were rendered from this PDF')

    if pdf_date:
        # Earlier crops may have been unreadable before a later crop established the
        # PDF date. Normalize every card to the same source-document date.
        for item in manifest['items']:
            item['document_date'] = pdf_date
            item['date_status'] = 'printed'
            if 'work_order_evidence' in item:
                # All cards share the independently established printed PDF
                # date, including cards read before that date was available.
                item['work_order_evidence']['dates'] = (pdf_date,)

    save_checkpoint(output, pages, pages, manifest, pdf_date)
    report_progress(output, 'publish', pages, pages, len(manifest['items']))
    write_json_atomic(output / MANIFEST, manifest)


if __name__ == '__main__':
    os.environ['OMP_THREAD_LIMIT'] = '1'
    cv2.setNumThreads(1)
    try:
        process(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]),
                origin=sys.argv[4] if len(sys.argv) > 4 else 'scan')
    except (subprocess.TimeoutExpired, OSError, MemoryError):
        # Runtime/tool/storage interruptions are not source-data failures.
        # The worker keeps the PDF plus every page-complete checkpoint and retries.
        raise SystemExit(RETRYABLE_EXIT)
)


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
    return {'items': [], 'skipped': [], 'warnings': [], 'review_pages': []}


def retain_review_page(output, pagefile, page, manifest, used, budget):
    """Keep one rendered page that produced no card so admins can inspect it."""
    filename = f'page-{page:04d}.review.png'
    target = output / filename
    shutil.copyfile(pagefile, target)
    size = target.stat().st_size
    used += size
    if used > budget:
        target.unlink(missing_ok=True)
        raise OSError('Rendered review pages exceed gallery storage budget')
    manifest['review_pages'].append(
        dict(page=page, file=filename, bytes=size, reason='no-recognized-forms')
    )
    return used


def clear_resume_state(output):
    for path in output.iterdir():
        if path.is_symlink():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif path.name in (CHECKPOINT, MANIFEST, '.' + CHECKPOINT + '.tmp',
                           '.' + MANIFEST + '.tmp') or CROP_FILE.fullmatch(path.name) or OCR_FILE.fullmatch(path.name) or REVIEW_FILE.fullmatch(path.name):
            path.unlink(missing_ok=True)


def cleanup_uncommitted(output, manifest):
    committed = {str(item.get('file', '')) for item in manifest['items']}
    committed.update(str(item.get('ocr_file', '')) for item in manifest['items'] if item.get('ocr_file'))
    committed.update(str(item.get('file', '')) for item in manifest.get('review_pages', ()))
    for path in output.iterdir():
        if path.is_symlink():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif ((CROP_FILE.fullmatch(path.name) or OCR_FILE.fullmatch(path.name) or REVIEW_FILE.fullmatch(path.name))
              and path.name not in committed):
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
                or not isinstance(manifest.get('warnings'), list)
                or not isinstance(manifest.get('review_pages'), list)):
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
            ocr_filename = str(item.get('ocr_file', '') or '')
            if ocr_filename:
                if not OCR_FILE.fullmatch(ocr_filename):
                    raise ValueError('invalid OCR diagnostic file')
                ocr_path = output / ocr_filename
                if ocr_path.is_symlink() or not ocr_path.is_file():
                    raise ValueError('OCR diagnostic file is missing')
                used += ocr_path.stat().st_size
        skipped = [int(value) for value in manifest['skipped']]
        if any(value < 1 or value > completed for value in skipped):
            raise ValueError('invalid skipped-page checkpoint')
        manifest['skipped'] = skipped
        review_pages = []
        for entry in manifest['review_pages']:
            if not isinstance(entry, dict):
                raise ValueError('invalid review-page checkpoint')
            filename = str(entry.get('file', ''))
            page = int(entry.get('page', 0))
            if not REVIEW_FILE.fullmatch(filename) or page not in skipped:
                raise ValueError('invalid review-page artifact')
            artifact = output / filename
            if artifact.is_symlink() or not artifact.is_file():
                raise ValueError('review-page artifact is missing')
            size = artifact.stat().st_size
            if int(entry.get('bytes', -1)) != size:
                raise ValueError('review-page artifact size changed')
            used += size
            review_pages.append(dict(page=page, file=filename, bytes=size,
                                     reason='no-recognized-forms'))
        manifest['review_pages'] = review_pages
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


def native_render_sizes(source, pages):
    """Avoid resampling a sole full-page scan before OCR; keep Poppler as renderer.

    A page containing anything beyond one ordinary image keeps the existing
    render size. In particular, image metadata alone cannot establish that a
    mixed page has no text, vector marks, annotations, masks or transformations.
    Metadata inspection is optional so an unavailable or damaged PDF reader
    cannot prevent the established Poppler path from processing the document.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(source)
        if len(reader.pages) != pages:
            return {}
    except Exception:
        return {}

    sizes = {}
    for index in range(1, pages + 1):
        try:
            page = reader.pages[index - 1]
            if page.get('/Rotate', 0) or page.get('/UserUnit', 1) != 1 or page.get('/Annots'):
                continue
            media, crop = tuple(map(float, page.mediabox)), tuple(map(float, page.cropbox))
            if not all(math.isfinite(value) for value in media + crop):
                continue
            if any(abs(a - b) > .01 for a, b in zip(media, crop)):
                continue
            operations = page.get_contents().operations
            if [operator for _, operator in operations] != [b'q', b'cm', b'Do', b'Q']:
                continue
            if operations[0][0] or operations[3][0] or len(operations[2][0]) != 1:
                continue
            matrix = tuple(map(float, operations[1][0]))
            expected = (media[2] - media[0], 0, 0, media[3] - media[1], media[0], media[1])
            if (len(matrix) != 6 or not all(math.isfinite(value) for value in matrix)
                    or any(abs(a - b) > .01 for a, b in zip(matrix, expected))):
                continue
            objects = page['/Resources']['/XObject'].get_object()
            if len(objects) != 1:
                continue
            image = objects[operations[2][0][0]].get_object()
            if (image.get('/Subtype') != '/Image' or image.get('/ImageMask')
                    or image.get('/Mask') is not None or image.get('/SMask') is not None):
                continue
            width, height = int(image['/Width']), int(image['/Height'])
            if width <= 0 or height <= 0 or min(expected[0], expected[3]) <= 0:
                continue
            if abs((width / height) / (expected[0] / expected[3]) - 1) > .005:
                continue
            sizes[index] = min(3300, max(width, height))
        except Exception:
            # Unrecognized page metadata uses the complete existing renderer.
            continue
    return sizes


def process(source, output, budget, *, origin='scan'):
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
    render_sizes = native_render_sizes(source, pages)

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
                    '-scale-to', str(render_sizes.get(page, 3300)), '-png', str(source), str(prefix),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=300,
            )
            pagefile = prefix.with_suffix('.png')
            with Image.open(pagefile) as image:
                raster = np.array(image.convert('RGB'))

            # Normalize small scan skew, then use the known form geometry
            # to correct a full 180-degree upside-down scan before cropping/OCR.
            raster = deskew_page(raster)
            raster = orient_work_order_page(raster)
            report_progress(output, 'crop', page, pages, len(manifest['items']))

            if is_dense_grid_page(raster):
                manifest['skipped'].append(page)
                used = retain_review_page(output, pagefile, page, manifest, used, budget)
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
                ocr_filename = f'{page:04d}-{part:03d}.ocr.png'
                ocr_path = output / ocr_filename
                try:
                    # A gallery PDF has one document date. Keep checking cards only
                    # until one reliable printed date is found, then reuse it.
                    reading = recognize(
                        path, work, known_date=pdf_date, debug_path=ocr_path,
                    )
                    usable_date = (origin == 'morning' or
                                   reading.get('mod_notes_present', True) is True)
                    if (usable_date and pdf_date is None and reading.get('date_status') == 'printed'
                            and reading.get('document_date')):
                        pdf_date = reading['document_date']
                except (OSError, ValueError, subprocess.SubprocessError):
                    ocr_path.unlink(missing_ok=True)
                    reading = dict(
                        text='',
                        lead_text='',
                        document_date=None,
                        date_status='needs-date',
                        work_order_candidates=(),
                        work_order_reads=(),
                        mod_notes_present=None,
                    )
                    manifest['warnings'].append(
                        f'Page {page} crop {part}: search text unavailable'
                    )
                if ocr_path.is_file():
                    used += ocr_path.stat().st_size
                    if used > budget:
                        raise OSError('Rendered crops exceed gallery storage budget')
                    reading['ocr_file'] = ocr_filename
                manifest['items'].append(
                    dict(file=filename, page=page, part=part, bytes=size, **reading)
                )

            if not count:
                manifest['skipped'].append(page)
                used = retain_review_page(output, pagefile, page, manifest, used, budget)
            pagefile.unlink(missing_ok=True)
            del raster
            report_progress(output, 'page-complete', page, pages, len(manifest['items']))
            save_checkpoint(output, pages, page, manifest, pdf_date)

    if not manifest['items'] and not manifest['review_pages']:
        raise ValueError('No reviewable pages were rendered from this PDF')

    if pdf_date:
        # Earlier crops may have been unreadable before a later crop established the
        # PDF date. Normalize every card to the same source-document date.
        for item in manifest['items']:
            item['document_date'] = pdf_date
            item['date_status'] = 'printed'
            if 'work_order_evidence' in item:
                # All cards share the independently established printed PDF
                # date, including cards read before that date was available.
                item['work_order_evidence']['dates'] = (pdf_date,)

    save_checkpoint(output, pages, pages, manifest, pdf_date)
    report_progress(output, 'publish', pages, pages, len(manifest['items']))
    write_json_atomic(output / MANIFEST, manifest)


if __name__ == '__main__':
    os.environ['OMP_THREAD_LIMIT'] = '1'
    cv2.setNumThreads(1)
    try:
        process(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]),
                origin=sys.argv[4] if len(sys.argv) > 4 else 'scan')
    except (subprocess.TimeoutExpired, OSError, MemoryError):
        # Runtime/tool/storage interruptions are not source-data failures.
        # The worker keeps the PDF plus every page-complete checkpoint and retries.
        raise SystemExit(RETRYABLE_EXIT)
