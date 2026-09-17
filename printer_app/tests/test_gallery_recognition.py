"""Synthetic regressions: OCR adapter, existing-image repair and source order."""
import hashlib
from pathlib import Path

import pytest

from printer_app.gallery.bootstrap import build
from printer_app.gallery.policy import printed_lead
from printer_app.gallery.recognition import tsv_words, search_text, lead_cell_text


def seed(service, page=1, part=1, text='Lead Name: Jordan Example Address: 10 Example St', **extra):
    service.initialize()
    source = 'a'*64
    ident = hashlib.sha256(f'{page}:{part}'.encode()).hexdigest()
    service.repository.enqueue(source, 'synthetic.pdf')
    service.repository.finish(source, [dict(id=ident, import_id=source,filename='synthetic.pdf',
        page=page,part=part,text=text,document_date='2026-09-16',date_status='printed',
        bytes=12,created=1000-page*10-part,**extra)])
    service.files.path('crops',ident).write_bytes(b'preserved-png')
    return ident


def test_tsv_quotes_cannot_swallow_rows_or_leak_geometry():
    value = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    value += '5\t1\t1\t1\t1\t1\t20\t30\t5\t10\t91\t"\n'
    value += '4\t1\t1\t1\t2\t0\t100\t120\t200\t15\t-1\t\n'
    value += '5\t1\t1\t1\t2\t1\t100\t120\t60\t15\t88\t02275180\n'
    value += '5\t1\t1\t1\t2\t2\t170\t120\t60\t15\t88\tExample\n'
    value += '5\t1\t1\t1\t3\t1\t100\t140\t5\t15\t88\t"\n'
    words = tsv_words(value)
    assert len(words) == 4
    assert search_text(words) == '"\n02275180 Example\n"'
    assert '200' not in search_text(words)  # Layout records are never document text.


def test_header_geometry_works_when_address_label_is_unreadable():
    cv2 = pytest.importorskip('cv2')
    import numpy as np
    gray = np.full((900,1000),255,np.uint8)
    for x in (20,400,980): cv2.line(gray,(x,0),(x,200),0,3)
    for y in (0,30,90,180): cv2.line(gray,(20,y),(980,y),0,3)
    def word(text,x,y,w=45):
        return dict(text=text,left=x,top=y,width=w,height=16,page_num=1,block_num=1,par_num=1,line_num=1,conf=90)
    words = [word('Lead',30,45),word('Name:',80,45),word('JORDAN',135,45,75),
             word('EXAMPLE',220,45,100),word('eet',415,45),word('6311',470,45),
             word('Lead',30,500),word('Name:',80,500),word('Someone',135,500)]
    assert printed_lead(lead_cell_text(words,gray)) == 'JORDAN EXAMPLE'
    # Arbitrary handwriting/rep names without an explicit header are not used.
    assert lead_cell_text(words[2:],gray) == ''


def test_new_normalized_header_is_used_without_address_or_number_guessing(tmp_path):
    service=build(tmp_path)
    ident=seed(service,text='Lead Name: JORDAN EXAMPLE eet 6311 Street Phone: 123',
               lead_text='Lead Name: JORDAN EXAMPLE',recognition_revision=1)
    assert service.item(ident)['lead_name']=='JORDAN EXAMPLE'
    assert service.related(ident)['total']==1
    assert service.repository.recognition_candidate(10**12) is None


def test_existing_repair_preserves_ids_images_notes_dates_and_confirmation(tmp_path):
    service=build(tmp_path)
    ident=seed(service,text='Lead Name: JORDAN EXAMPLE eet 6311 Street Phone: 123\n4 1 1 1 16 0 1152')
    assert not service.item(ident)['lead_name']
    service.note(ident,'e'*32,'Office','Jordan Example follow-up')
    service.date(ident,'2026-09-15')
    before=service.item(ident)
    calls=[]
    def reader(path):
        calls.append(path)
        return dict(text='Lead Name: JORDAN EXAMPLE Address: 6311 Street',lead_text='Lead Name: JORDAN EXAMPLE')
    assert service.repair_one(reader)
    after=service.item(ident)
    for key in ('id','import_id','notes','document_date','date_status','bytes','created','page','part'):
        assert after[key]==before[key]
    assert after['lead_name']=='JORDAN EXAMPLE'
    assert '1152' not in after['text']
    assert service.files.path('crops',ident).read_bytes()==b'preserved-png'
    assert not build(tmp_path).repair_one(reader)
    assert len(calls)==1
    other=seed(service,2)
    def concurrent_edit(path):
        service.lead(other,'Confirmed By User')
        return reader(path)
    assert service.repair_one(concurrent_edit)
    assert service.item(other)['lead_name']=='Confirmed By User'
    assert service.item(other)['lead_status']=='confirmed'


def test_repair_failure_is_durable_bounded_and_expiry_wins(tmp_path):
    service=build(tmp_path); ident=seed(service)
    def broken(path): raise OSError('missing local tool')
    assert service.repair_one(broken)
    assert not service.repair_one(broken)  # No tight retry loop.
    assert service.item(ident)['recognition_attempts']==1
    with service.repository.connect() as c:
        c.execute('UPDATE items SET recognition_retry_at=0,recognition_attempts=3')
    assert not service.repair_one(broken)
    second=seed(service,2)
    def expired(path):
        with service.repository.connect() as c: c.execute("UPDATE items SET state='DELETING' WHERE id=?",(second,))
        return dict(text='different text',lead_text='Lead Name: Someone Else')
    assert service.repair_one(expired)
    with service.repository.connect() as c:
        assert c.execute('SELECT recognition_revision FROM items WHERE id=?',(second,)).fetchone()[0]==0


def test_empty_repair_cannot_erase_existing_search_text(tmp_path):
    service=build(tmp_path); ident=seed(service)
    before=service.item(ident)
    assert service.repair_one(lambda path: dict(text='',lead_text=''))
    after=service.item(ident)
    assert after['text']==before['text']
    assert after['lead_name']==before['lead_name']
    assert after['recognition_revision']==0
    assert after['recognition_attempts']==1


def test_existing_source_order_is_page_then_part_across_pagination(tmp_path):
    service=build(tmp_path)
    for page in reversed(range(1,16)):
        for part in (2,1): seed(service,page,part)
    rows=service.search('',0)['items']+service.search('',24)['items']
    assert [(row['page'],row['part']) for row in rows]==[(p,n) for p in range(1,16) for n in (1,2)]
    assert len({row['id'] for row in rows})==30
    anchor=rows[0]['id']
    assert service.related(anchor)['items']==service.search('',0)['items']
    assert build(tmp_path).search('',0)['items']==service.search('',0)['items']


def test_recognition_and_navigation_have_explicit_owners():
    root=Path(__file__).resolve().parents[1]
    for name in ('gallery/service.py','gallery/web.py','static/gallery.js','static/gallery_navigation.js'):
        s=(root/name).read_text()
        assert 'SELECT ' not in s and 'cv2' not in s and 'tesseract' not in s
    s=(root/'static/gallery_navigation.js').read_text()
    assert 'fetch(' not in s and 'history.pushState' in s and 'popstate' in s
    s=(root/'gallery/recognition.py').read_text()
    assert 'printer_app' not in s and 'gmail' not in s.lower()
    assert 'csv.QUOTE_NONE' in s

    access_service=(root/'gallery/access_service.py').read_text()
    access_repository=(root/'gallery/access_repository.py').read_text()
    gallery_ui=(root/'static/gallery.js').read_text()
    offline_runtime=(root/'static/gallery_offline.js').read_text()
    assert 'sqlite3' not in access_service and 'flask' not in access_service
    assert 'flask' not in access_repository
    assert 'indexedDB' not in gallery_ui and 'localStorage' not in gallery_ui
    assert 'indexedDB' in offline_runtime and '/gallery/api/offline/index' in offline_runtime
