"""Replaceable LibreOffice adapter, executed by system Python with python3-uno.

Open the original workbook; change only explicitly selected page settings.
Never rebuild cells, detect headers, split statuses, or save over the source.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .print_options import PrintOptions

# LibreOffice page dimensions are hundredths of a millimetre (portrait order).
PAPER = {'tabloid': (27940, 43180), 'letter': (21590, 27940),
         'legal': (21590, 35560), 'a4': (21000, 29700), 'a3': (29700, 42000)}
FILTERS = {'.xls': 'MS Excel 97', '.xlsx': 'Calc MS Excel 2007 XML',
           '.xlsm': 'Calc MS Excel 2007 VBA XML'}


def configure_pages(document, options: PrintOptions) -> None:
    styles = document.getStyleFamilies().getByName('PageStyles')
    seen = set()
    for sheet in document.getSheets():
        name = sheet.PageStyle
        if name in seen:
            continue
        seen.add(name)
        style = styles.getByName(name)
        landscape = style.IsLandscape if options.orientation == 'source' else options.orientation == 'landscape'
        if options.paper != 'source':
            width, height = PAPER[options.paper]
            style.Width, style.Height = (height, width) if landscape else (width, height)
        elif options.orientation != 'source' and style.IsLandscape != landscape:
            style.Width, style.Height = style.Height, style.Width
        if options.orientation != 'source' or options.paper != 'source':
            style.IsLandscape = landscape
        if options.excel_scale != 'source':
            # These are mutually exclusive page-style modes; clear inherited fit
            # limits before applying exactly the user's selected one.
            style.ScaleToPages = 0
            style.ScaleToPagesX = 0
            style.ScaleToPagesY = 0
            style.PageScale = 100
            if options.excel_scale == 'fit-width':
                style.ScaleToPagesX = 1
            elif options.excel_scale == 'fit-page':
                style.ScaleToPagesX = 1
                style.ScaleToPagesY = 1
            else:
                style.PageScale = options.scale_percent
        if options.margins != 'source':
            margin = {'narrow': 635, 'normal': 1270, 'none': 0}[options.margins]
            for name in ('LeftMargin', 'RightMargin', 'TopMargin', 'BottomMargin'):
                style.setPropertyValue(name, margin)


def render(source: Path, target: Path, home: Path, binary: str, options: PrintOptions) -> None:
    # Kept out of the application's venv; UNO belongs solely to this adapter.
    import uno
    import unohelper
    from com.sun.star.task import XInteractionHandler, XInteractionAbort
    from com.sun.star.document.MacroExecMode import NEVER_EXECUTE
    from com.sun.star.document.UpdateDocMode import NO_UPDATE

    class AbortInteraction(unohelper.Base, XInteractionHandler):
        def handle(self, request):
            for continuation in request.getContinuations():
                if continuation.queryInterface(uno.getTypeByName('com.sun.star.task.XInteractionAbort')):
                    continuation.select()
                    return

    def prop(name, value):
        p = uno.createUnoStruct('com.sun.star.beans.PropertyValue')
        p.Name, p.Value = name, value
        return p

    profile = home / 'profile'
    (profile / 'user').mkdir(parents=True)
    # No trusted locations, macros, DDE/OLE activation, plugin content or link updates.
    # ScRecalcOptions.RECALC_NEVER = 1 (LibreOffice sc/inc/calcconfig.hxx).
    # Cached formula results and original row heights are preferred over a hard recalc.
    (profile / 'user/registrymodifications.xcu').write_text('''<?xml version="1.0"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting">
<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
<prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>
<prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>
</item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load">
<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>1</value></prop>
<prop oor:name="RecalcOptimalRowHeightMode" oor:op="fuse"><value>1</value></prop>
</item>
</oor:items>''', encoding='utf-8')
    pipe = 'printer_' + uuid.uuid4().hex
    command = [binary, '-env:UserInstallation=' + profile.as_uri(), '--headless',
               '--nologo', '--nodefault', '--norestore', '--nofirststartwizard',
               '--accept=pipe,name=' + pipe + ';urp;StarOffice.ComponentContext']
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    document, desktop = None, None
    try:
        context = uno.getComponentContext()
        resolver = context.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', context)
        remote = None
        for _ in range(200):
            if process.poll() is not None:
                raise RuntimeError('LibreOffice exited before connecting')
            try:
                remote = resolver.resolve('uno:pipe,name=' + pipe + ';urp;StarOffice.ComponentContext')
                break
            except Exception:
                time.sleep(.05)
        if remote is None:
            raise RuntimeError('LibreOffice connection timed out')
        desktop = remote.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', remote)
        # Sheet visibility cannot be changed in a read-only Calc document. Only
        # active-sheet selection needs a writable in-memory TEMPORARY copy.
        # The original attachment is never loaded writable or overwritten.
        document = desktop.loadComponentFromURL(source.as_uri(), '_blank', 0, (
            prop('Hidden', True), prop('ReadOnly', options.sheets != 'active'), prop('UpdateDocMode', NO_UPDATE),
            prop('MacroExecutionMode', NEVER_EXECUTE), prop('InteractionHandler', AbortInteraction()),
            prop('FilterName', FILTERS[source.suffix.lower()]), prop('PickListEntry', False),
            prop('RepairPackage', False)))
        if document is None or not document.supportsService('com.sun.star.sheet.SpreadsheetDocument'):
            raise RuntimeError('Not a readable Excel workbook')
        document.enableAutomaticCalculation(False)
        configure_pages(document, options)
        data = [prop('ExportBookmarks', False), prop('ExportFormFields', False),
                prop('ExportLinksRelativeFsys', False), prop('IsSkipEmptyPages', True)]
        if options.sheets == 'active':
            sheet = document.getCurrentController().getActiveSheet()
            if not sheet.IsVisible:
                raise RuntimeError('Saved active sheet is hidden')
            # Select sheets in the temporary document without deleting them or
            # invalidating formulas. Never save this visibility change to source.
            for other in document.getSheets():
                if other.Name != sheet.Name and other.IsVisible:
                    other.IsVisible = False
        # Respect print ranges, hidden rows/sheets, outlines and source formatting.
        document.storeToURL(target.as_uri(), (prop('FilterName', 'calc_pdf_Export'),
                              prop('FilterData', tuple(data)), prop('Overwrite', True)))
    finally:
        if document is not None:
            try:
                document.close(True)
            except Exception:
                pass
        if desktop is not None:
            try:
                desktop.terminate()
            except Exception:
                pass
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    try:
        request = json.loads(Path(sys.argv[1]).read_text())
        render(Path(request['source']), Path(request['target']), Path(request['home']),
               request['binary'], PrintOptions(**request['options']))
    except Exception:
        # Workbook strings, paths and link credentials must never escape to logs/UI.
        print('EXCEL CONVERSION FAILED', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
