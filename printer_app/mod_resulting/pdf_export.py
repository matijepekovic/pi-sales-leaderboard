"""Overlay digital ink on the exact PDF produced by Printer's MOD renderer.

Never changes the existing renderer or its three-sheets-per-page layout.
"""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth

from ..mod_sheet_contract import ModSheetRecord
from ..mod_sheets.pdf_renderer import MOD_TABLE_WIDTH, MOD_ROW_HEIGHTS, render_mod_pdf
from .contract import (
    clean_draft, final_redline_text, note_runs_for_display,
    prices, format_money, deposit_payment_text,
)


COL_WIDTH = MOD_TABLE_WIDTH / 10
LEFT = (letter[0] - MOD_TABLE_WIDTH) / 2
FIRST_TOP = 0.55 * cm + 6
SHEET_SPACING = sum(MOD_ROW_HEIGHTS) + 18


def _location(index, column, row):
    top = FIRST_TOP + (index % 3) * SHEET_SPACING + sum(MOD_ROW_HEIGHTS[:row])
    return LEFT + column * COL_WIDTH, top


def _erase(c, index, col, row, cols=1, rows=1):
    x, top = _location(index,col,row)
    height = sum(MOD_ROW_HEIGHTS[row:row+rows])
    c.setFillColor(colors.white)
    c.rect(x+1.2, letter[1]-(top+height)+1.2,
           COL_WIDTH*cols-2.4,height-2.4,stroke=0,fill=1)
    c.setFillColor(colors.black)


def _write(c, x, top, text, size=8.5, bold=False, color=colors.black):
    c.setFont('Times-Bold' if bold else 'Times-Roman',size)
    c.setFillColor(color)
    c.drawString(x,letter[1]-top-size,text)
    c.setFillColor(colors.black)


def _lines(text, font, size, width):
    result = []
    for raw in str(text or '').splitlines():
        if not raw.strip():
            result.append('')
            continue
        current = ''
        for word in raw.split():
            attempt = (current+' '+word).strip()
            if stringWidth(attempt,font,size) <= width:
                current=attempt
                continue
            if current:
                result.append(current)
                current=''
            if stringWidth(word,font,size) <= width:
                current=word
                continue
            # Long unbroken sale amounts/notes must not cross the table edge.
            chunk=''
            for character in word:
                if chunk and stringWidth(chunk+character,font,size) > width:
                    result.append(chunk)
                    chunk=character
                else:
                    chunk+=character
            current=chunk
        if current: result.append(current)
    return result


def _fit_lines(c, text, x, top, width, height, *, bold=False, red=False, start=10):
    font='Times-Bold' if bold else 'Times-Roman'
    for size in (start,start-1,start-2,start-3,start-4,6.5):
        if size <= 0: continue
        lines=_lines(text,font,size,width)
        leading=size*1.2
        if len(lines)*leading <= height: break
    # Keep every glyph within the MOD Notes cell. Never overwrite borders.
    c.saveState()
    clip=c.beginPath()
    clip.rect(x-0.2,letter[1]-(top+height),width+0.4,height)
    c.clipPath(clip,stroke=0,fill=0)
    for index,line in enumerate(lines):
        _write(c,x,top+index*leading,line,size,bold,
               colors.HexColor('#bb0707') if red else colors.black)
    c.restoreState()


def _bottom_redline_layout(text, width, max_height):
    """Wrap and shrink generated notes until they fit the lower-right box."""
    font='Times-Bold'
    for size in (11,10,9,8,7,6,5,4,3,2,1.5):
        lines=_lines(text,font,size,width)
        leading=size*1.2
        if len(lines)*leading <= max_height:
            return lines,size,leading
    # The physical paper has finite space. This last-resort size is still
    # clipped by the original border, never drawn into the next Work Order.
    return lines,size,leading


def _fit_mixed_notes(c, runs, x, top, width, height):
    """One MOD Notes text field with preserved black/red character formatting."""
    if not runs:
        return
    for size in (10, 9, 8, 7, 6.5):
        parts = []
        for run in runs:
            ink = '#b00000' if run['red'] else '#000000'
            font_size = size * 1.18 if run['red'] else size
            content = escape(run['text']).replace('\n', '<br/>')
            parts.append(
                '<font color="' + ink + '" size="' + str(font_size) + '">'
                + content + '</font>'
            )
        markup = ''.join(parts)
        style = ParagraphStyle('MODNotesMixed', fontName='Times-Roman',
                               fontSize=size, leading=size * 1.32,
                               spaceBefore=0, spaceAfter=0,
                               allowWidows=0, allowOrphans=0)
        paragraph = Paragraph(markup, style)
        _, actual_height = paragraph.wrap(width, 10000)
        if actual_height <= height or size == 6.5:
            break
    c.saveState()
    clip = c.beginPath()
    clip.rect(x-0.2, letter[1]-(top+height), width+0.4, height)
    c.clipPath(clip, stroke=0, fill=0)
    paragraph.drawOn(c, x, letter[1]-top-actual_height)
    c.restoreState()


def _check(c,x,top,value, label,*, size=8.5):
    _write(c,x,top,label,size,bold=True)
    if value:
        _write(c,x+stringWidth(label,'Times-Bold',size)+4,top,'X',size,bold=True)


def _overlay_one(c,index,draft):
    d=clean_draft(draft)
    # Replace only the user-approved label. Keep the original exterior and
    # interior borders, spacing, column widths, and other Salesforce values.
    _erase(c,index,9,3)
    x,t=_location(index,9,3)
    _write(c,x+2,t+1,'Result Detail:',7,bold=True)
    if d['result_detail']:
        _fit_lines(c,d['result_detail'],x+2,t+10,COL_WIDTH-4,
                   MOD_ROW_HEIGHTS[3]-12,start=7)

    # Preserve the three fixed lower checklist cells. Docs replaces Fin
    # Checklist; Bid Sheets, Promo, and Review share the existing middle cell.
    _erase(c,index,0,6)
    x,t=_location(index,0,6)
    _check(c,x+2,t+2,d['docs'],'Docs')
    _erase(c,index,1,6,2)
    x,t=_location(index,1,6)
    # Match the on-sheet checklist without changing any original box borders.
    slot = (COL_WIDTH * 2 - 4) / 3.5
    for offset, label, key in ((0, 'Bid Sheets', 'bid_sheets'),
                               (1.5, 'Promo', 'promotion'),
                               (2.5, 'Review', 'review')):
        check_x = x + 2 + offset * slot
        _write(c,check_x,t+2,label,8.5,bold=True)
        check_y = letter[1] - (t + 20)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        c.rect(check_x,check_y,6,6,stroke=1,fill=0)
        if d[key]:
            c.setLineWidth(0.8)
            c.line(check_x+1,check_y+3,check_x+2.5,check_y+1.5)
            c.line(check_x+2.5,check_y+1.5,check_x+5,check_y+4.5)
    if d['pictures']:
        x,t=_location(index,3,6)
        _check(c,x+3,t+11,True,'')

    _erase(c,index,0,7,4)
    x,t=_location(index,0,7)
    _write(c,x+2,t+1,'Dispo:',8.5,bold=True)
    options={'sale':'Sale','pns':'Pitch No Sale','np':'No Pitch',
             'cxl':'CXL','nra':'NRA','oos':'OOS'}
    _write(c,x+36,t+1,options.get(d['dispo'],''),8)
    _check(c,x+COL_WIDTH*2+2,t+1,d['one_leg'],'1 Leg',size=7.5)
    _check(c,x+COL_WIDTH*3+4,t+1,d['free_lead'],'Free Lead',size=7.5)
    # Only the split requested by the user is added to the existing row.
    c.setLineWidth(1.34)
    c.line(x+COL_WIDTH*2,letter[1]-t,x+COL_WIDTH*2,
           letter[1]-(t+MOD_ROW_HEIGHTS[7]))

    for row,label,key in [(8,'Call 1:','call_1'),(9,'Call 2:','call_2')]:
        _erase(c,index,0,row)
        x,t=_location(index,0,row)
        _write(c,x+2,t+1,label,7.5,bold=True)
        if d[key]: _write(c,x+2,t+9,d[key],6.6)

    # 90 Min and DNR share the existing tall field with one new horizontal line.
    _erase(c,index,0,10)
    x,t=_location(index,0,10)
    half=MOD_ROW_HEIGHTS[10]/2
    c.setLineWidth(1.34)
    c.line(x,letter[1]-(t+half),x+COL_WIDTH,letter[1]-(t+half))
    _check(c,x+2,t+1,d['ninety_min'],'90 Min:',size=8)
    _check(c,x+2,t+half+1,d['dnr'],'DNR:',size=8)

    for col,row,cols,rows,key in [(1,8,3,2,'need'),(1,10,3,1,'want')]:
        if not d[key]: continue
        x,t=_location(index,col,row)
        _fit_lines(c,d[key],x+3,t+12,COL_WIDTH*cols-6,
                   sum(MOD_ROW_HEIGHTS[row:row+rows])-14,start=8.5)

    # The Work Order Deposit/Payment field is one slash-separated text value
    # in the sheet, PDF, and Salesforce. Never add a currency symbol.
    automatic=prices(d['numbers'])
    start=d['start_price_override'] or automatic['highest']
    final=d['final_price_override'] or automatic['lowest']
    deposit_payment=deposit_payment_text(d)
    for column, amount, combined in ((4,start,False),(6,final,False),
                                     (8,deposit_payment,True)):
        if not amount:
            continue
        x,t=_location(index,column,4)
        value=amount if combined else format_money(amount)
        max_width=COL_WIDTH*2-6
        size=min(6.5,6.5*max_width/max(1,stringWidth(value,'Times-Roman',6.5)))
        width=stringWidth(value,'Times-Roman',size)
        # Preserve printed field labels, borders and the full combined value.
        _write(c,x+COL_WIDTH*2-width-3,t+2,value,size)

    # Ink is placed inside the renderer's one and only MOD Notes area.
    x,t=_location(index,4,5)
    full_width=COL_WIDTH*6
    numbers_width=full_width*.21
    for line_index,line in enumerate(d['numbers'].splitlines()):
        if line_index >= 10: break
        _write(c,x+2,t+13+line_index*9,line.strip(),8)
    text_x=x+numbers_width+2
    text_width=full_width-numbers_width-7
    notes_height=sum(MOD_ROW_HEIGHTS[5:])-15
    # Legacy mixed runs remain readable; new manual redlines are separate
    # from the black Notes and belong with generated Sale/Result redlines.
    runs = note_runs_for_display(dict(d, redlines=''))
    user_notes = ''.join(part['text'] for part in runs)
    generated = final_redline_text(d)
    # Reserve space for black notes above the bottom-anchored redlines.
    if generated:
        reserve = min(notes_height*.28, 30) if user_notes else 0
        lines,size,leading = _bottom_redline_layout(
            generated, text_width, max(8, notes_height-reserve-5))
        red_height = len(lines)*leading
        comment_height = max(8, notes_height-red_height-6)
    else:
        lines = []
        red_height = 0
        comment_height = notes_height
    if user_notes:
        _fit_mixed_notes(c, runs, text_x, t+13, text_width, comment_height)
    # DNR, manual redlines and Sale lines stay anchored to the bottom of the
    # original MOD Notes area. Fit them above the border, independently of how
    # much black-note space remains.
    if generated:
        red_top=t+13+notes_height-3-red_height
        c.saveState()
        clip=c.beginPath()
        clip.rect(text_x-0.2, letter[1]-(t+13+notes_height-1),
                  text_width+0.4, red_height+2)
        c.clipPath(clip,stroke=0,fill=0)
        for line_index,line in enumerate(lines):
            _write(c,text_x,red_top+line_index*leading,line,size,bold=True,
                   color=colors.HexColor('#bb0707'))
        c.restoreState()


def render_resulting_pdf(sheets, *, color_code=False):
    """Exactly the Printer sheet as base, with no rebuilt or duplicate template."""
    if not sheets:
        raise ValueError('Choose at least one sheet for PDF.')
    records=[ModSheetRecord(**dict(
        item['snapshot'],
        assigned_service_resources=tuple(item['snapshot'].get('assigned_service_resources',()))
    )) for item in sheets]
    original=PdfReader(BytesIO(render_mod_pdf(records, color_code=color_code)))
    overlay_pdf=BytesIO()
    c=canvas.Canvas(overlay_pdf,pagesize=letter)
    for index,item in enumerate(sheets):
        _overlay_one(c,index,item['draft'])
        if (index+1)%3==0 and index+1<len(sheets):
            c.showPage()
    c.save()
    overlay_pdf.seek(0)
    overlay=PdfReader(overlay_pdf)
    output=PdfWriter()
    for index,page in enumerate(original.pages):
        page.merge_page(overlay.pages[index])
        output.add_page(page)
    result=BytesIO()
    output.write(result)
    return result.getvalue()
