"""Overlay digital ink on the exact PDF produced by Printer's MOD renderer.

Never changes the existing renderer or its three-sheets-per-page layout.
"""
from __future__ import annotations

from io import BytesIO
from decimal import Decimal
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
    prices, format_money, sold_products, individual_product_sales,
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
            if current: result.append(current)
            current=word
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

    # Keep the original price row. Explicit cell overrides take precedence;
    # otherwise show the values derived from Numbers or sold-product deposits.
    automatic=prices(d['numbers'])
    start=d['start_price_override'] or automatic['highest']
    final=d['final_price_override'] or automatic['lowest']
    sold=(sold_products(d) if d['dispo']=='sale' else individual_product_sales(d))
    total=str(sum((Decimal(item['deposit']) for item in sold), Decimal('0'))) if sold else ''
    deposit=d['deposit_override'] or total
    for column, amount in ((4,start),(6,final),(8,deposit)):
        if not amount:
            continue
        x,t=_location(index,column,4)
        value=format_money(amount)
        width=stringWidth(value,'Times-Roman',6.5)
        # Preserve printed field labels and existing box borders.
        _write(c,x+COL_WIDTH*2-width-3,t+2,value,6.5)

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
    # Redlines are entries typed after Dispo in the same user Notes field.
    # A selected Dispo never recolors earlier black notes.
    runs = note_runs_for_display(d)
    user_notes = ''.join(part['text'] for part in runs)
    generated = final_redline_text(dict(d, redlines=''))
    if generated:
        line_count = len(_lines(user_notes, 'Times-Roman', 9, text_width))
        comment_height = min(notes_height*.75, max(13, line_count*11)) if user_notes else 0
    else:
        comment_height = notes_height
    if user_notes:
        _fit_mixed_notes(c, runs, text_x, t+13, text_width,
                         max(13, comment_height))
    # DNR and sale lines are generated from checkboxes/products, not a second
    # notes input. Keep them below the user's note without double printing.
    if generated:
        generated_top=t+13+comment_height+(2 if user_notes else 0)
        _fit_lines(c,generated,text_x,generated_top,text_width,
                   max(8,notes_height-comment_height-2),
                   bold=True,red=True,start=12)


def render_resulting_pdf(sheets):
    """Exactly the Printer sheet as base, with no rebuilt or duplicate template."""
    if not sheets:
        raise ValueError('Choose at least one sheet for PDF.')
    records=[ModSheetRecord(**dict(
        item['snapshot'],
        assigned_service_resources=tuple(item['snapshot'].get('assigned_service_resources',()))
    )) for item in sheets]
    original=PdfReader(BytesIO(render_mod_pdf(records)))
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
