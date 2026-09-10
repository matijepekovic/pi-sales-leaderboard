"""LibreOffice receives only rebuilt, values-only workbooks, never the untrusted original."""
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from .contracts import ConversionError
from .pdfs import page_count
from .processes import safe_environment


def run_conversion(args, timeout):
    """Own the complete LibreOffice process group so timeout cannot leave children alive."""
    environment = safe_environment() | {'SAL_USE_VCLPLUGIN': 'svp'}
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, env=environment, start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


class LibreOfficeRenderer:
    def __init__(self, timeout=90):
        self.timeout = timeout

    def render(self, group, directory):
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        workbook_path = directory / 'report.xlsx'
        pdf_path = directory / 'report.pdf'
        book = Workbook()
        sheet = book.active
        sheet.title = 'Report'
        all_rows = [tuple(group.headers)] + [tuple(cell.value for cell in row) for row in group.rows]
        widths = []
        for index in range(len(group.headers)):
            width = min(32, max(10, max(len(str(row[index] if row[index] is not None else '')) for row in all_rows) + 2))
            widths.append(width)
            sheet.column_dimensions[get_column_letter(index + 1)].width = width
        for row_index, row in enumerate(all_rows, 1):
            lines = 1
            for column, value in enumerate(row, 1):
                cell = sheet.cell(row_index, column, value)
                if isinstance(value, str):
                    cell.data_type = 's'
                cell.font = Font(name='DejaVu Sans', size=9, bold=row_index == 1)
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                if row_index == 1:
                    cell.fill = PatternFill('solid', fgColor='E4E9EE')
                else:
                    cell.number_format = group.rows[row_index - 2][column - 1].number_format
                rendered_text = str(value if value is not None else '')
                lines = max(lines, sum(max(1, math.ceil(len(part) / max(1, widths[column - 1] - 2))) for part in rendered_text.split('\n')))
            sheet.row_dimensions[row_index].height = max(18, lines * 14)
        sheet.freeze_panes = 'A2'
        sheet.print_title_rows = '1:1'
        sheet.print_area = f'A1:{get_column_letter(len(group.headers))}{len(all_rows)}'
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = 'landscape'
        sheet.page_setup.paperSize = sheet.PAPERSIZE_TABLOID
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.page_margins = PageMargins(left=.25, right=.25, top=.3, bottom=.3, header=.1, footer=.1)
        sheet.print_options.horizontalCentered = True
        sheet.oddHeader.center.text = group.substatus.replace('&', '&&')[:120]
        sheet.oddHeader.center.size = 10
        book.save(workbook_path)
        book.close()
        pdf_path.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix='lo-', dir=directory) as temporary:
            profile = Path(temporary) / 'profile'
            user = profile / 'user'
            user.mkdir(parents=True)
            (user / 'registrymodifications.xcu').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
</oor:items>''')
            try:
                result = run_conversion(['libreoffice', f'-env:UserInstallation={profile.as_uri()}', '--headless', '--nologo', '--nodefault', '--nofirststartwizard', '--norestore', '--convert-to', 'pdf:calc_pdf_Export', '--outdir', str(directory), str(workbook_path)], self.timeout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ConversionError('EXCEL CONVERSION FAILED: ' + type(exc).__name__) from exc
            if result.returncode or not pdf_path.is_file():
                detail = ' '.join((result.stdout + ' ' + result.stderr).split())[-1500:]
                raise ConversionError('EXCEL CONVERSION FAILED: ' + (detail or 'LibreOffice produced no usable PDF'))
        page_count(pdf_path)
        return workbook_path, pdf_path
