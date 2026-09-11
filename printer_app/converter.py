"""Workbook-to-PDF boundary. Source bytes/layout are never reconstructed."""
from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from pypdf import PdfReader

from .config import Config


class ConversionError(ValueError):
    pass


def page_count(path: Path) -> int:
    try:
        with path.open('rb') as stream:
            reader = PdfReader(stream, strict=False)
            if reader.is_encrypted:
                raise ConversionError('ENCRYPTED PDF IS NOT PRINTABLE')
            count = len(reader.pages)
            if count < 1:
                raise ConversionError('NO PRINTABLE PDF PAGES FOUND')
            return count
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError('INVALID PDF: ' + type(exc).__name__) from exc



def convert(workbook: Path, directory: Path, cfg: Config) -> Path:
    suffix = workbook.suffix.lower()
    if suffix not in ('.xls', '.xlsx', '.xlsm'):
        raise ConversionError('UNSUPPORTED WORKBOOK TYPE')
    if suffix != '.xls':
        # Container safety only, not report/table parsing or content rewriting.
        try:
            with zipfile.ZipFile(workbook) as archive:
                entries = archive.infolist()
                if len(entries) > 10000 or sum(i.file_size for i in entries) > 128 * 1024 * 1024:
                    raise ConversionError('WORKBOOK EXCEEDS SAFE EXPANSION LIMIT')
        except zipfile.BadZipFile as exc:
            raise ConversionError('INVALID EXCEL WORKBOOK') from exc
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / 'report.pdf'
    with tempfile.TemporaryDirectory(prefix='lo-', dir=directory) as temp:
        home = Path(temp).resolve()
        source = home / ('source' + suffix)
        shutil.copyfile(workbook, source)
        output = home / 'report.pdf'
        request = home / 'render.json'
        request.write_text(json.dumps(dict(source=str(source), target=str(output), home=str(home),
                          binary=cfg.libreoffice, options=cfg.print_options.snapshot())))
        # Only this small adapter needs the system UNO binding. No Gmail secrets,
        # user Office profile or unrelated application paths are inherited.
        command = ['/usr/bin/python3', '-m', 'printer_app.libreoffice_renderer', str(request)]
        env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(home), 'LANG': 'C.UTF-8',
               'TMPDIR': str(home), 'PYTHONDONTWRITEBYTECODE': '1'}
        try:
            process = subprocess.Popen(command, cwd=Path(__file__).resolve().parent.parent,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, start_new_session=True)
            try:
                process.wait(timeout=cfg.conversion_timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise ConversionError('EXCEL CONVERSION TIMED OUT')
            finally:
                # Also clean up office children if the adapter failed unexpectedly.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except OSError as exc:
            raise ConversionError('LIBREOFFICE RENDERER COULD NOT START') from exc
        if process.returncode != 0 or not output.is_file():
            raise ConversionError('EXCEL CONVERSION FAILED')
        page_count(output)
        output.replace(target)
    return target
