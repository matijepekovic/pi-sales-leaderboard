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


def test_related_uses_one_character_name_or_exact_address_and_global_rename(tmp_path):
    service=build(tmp_path)
    anchor=seed(service,1,1,
        text='Lead Name: Darryll Mitchell Address: 792 Park Ave NE, OCEAN SHORES, WA, 98569 Phone: 3609829374')
    one_letter_name=seed(service,2,1,
        text='Lead Name: Darryl Mitchell Address: 10 Different Rd, Aberdeen, WA 98520 Phone: 1')
    exact_address=seed(service,3,1,
        text='Lead Name: Completely Different Address: 792 PARK AVE NE, ocean shores, WA 98569 Phone: 2')
    two_letter_name=seed(service,4,1,
        text='Lead Name: Daryl Mitchel Address: 400 Other Rd, Aberdeen, WA 98520 Phone: 3')
    one_letter_address=seed(service,5,1,
        text='Lead Name: Another Person Address: 793 Park Ave NE, OCEAN SHORES, WA, 98569 Phone: 4')
    expanded_address=seed(service,6,1,
        text='Lead Name: Different Customer Address: 792 Park Avenue Northeast, OCEAN SHORES, WA, 98569 Phone: 5')
    unrelated=seed(service,7,1,
        text='Lead Name: Other Person Address: 500 Main St, Olympia, WA 98501 Phone: 6')

    related=service.related(anchor)
    ids={row['id'] for row in related['items']}
    assert anchor in ids
    assert one_letter_name in ids
    assert exact_address in ids
    assert two_letter_name not in ids
    assert one_letter_address not in ids
    assert expanded_address not in ids
    assert unrelated not in ids
    assert related['address'].startswith('792 Park Ave')

    changed=service.lead(anchor,'Darryl Mitchell')
    assert changed=={'updated':3,'scope':'related'}
    assert service.item(anchor)['lead_name']=='Darryl Mitchell'
    assert service.item(one_letter_name)['lead_name']=='Darryl Mitchell'
    assert service.item(exact_address)['lead_name']=='Darryl Mitchell'
    assert service.item(two_letter_name)['lead_name']=='Daryl Mitchel'
    assert service.item(one_letter_address)['lead_name']=='Another Person'
    assert service.item(expanded_address)['lead_name']=='Different Customer'
    assert service.item(unrelated)['lead_name']=='Other Person'


def test_review_card_can_be_named_from_job_page_without_auto_approval(tmp_path):
    service=build(tmp_path)
    source='a'*64
    ident=seed(service,20,1,text='Address: 10 Example St Phone: 123')
    before=service.import_item(source,ident)
    assert before['state']=='REVIEW'
    assert before['lead_name']==''

    changed=service.import_item_lead(source,ident,'Jordan Example')
    assert changed['state']=='REVIEW'
    after=service.import_item(source,ident)
    assert after['lead_name']=='Jordan Example'
    assert after['lead_status']=='confirmed'
    assert after['state']=='REVIEW'
    assert service.item(ident) is None

    service.approve_import_item(source,ident)
    assert service.item(ident)['lead_name']=='Jordan Example'


def test_first_name_on_approved_unnamed_card_is_local_then_future_edits_are_global(tmp_path):
    service=build(tmp_path)
    source='a'*64
    unnamed=seed(service,21,1,text='Address: 55 Exact Rd Phone: 1')
    service.approve_import_item(source,unnamed)
    other=seed(service,22,1,text='Lead Name: Other Person Address: 55 Exact Rd Phone: 2')

    first=service.lead(unnamed,'Jordan Example')
    assert first=={'updated':1,'scope':'single'}
    assert service.item(unnamed)['lead_name']=='Jordan Example'
    assert service.item(other)['lead_name']=='Other Person'

    second=service.lead(unnamed,'Jordan Example Jr')
    assert second=={'updated':2,'scope':'related'}
    assert service.item(unnamed)['lead_name']=='Jordan Example Jr'
    assert service.item(other)['lead_name']=='Jordan Example Jr'


def test_related_name_matching_uses_letters_only_but_address_keeps_numbers(tmp_path):
    service=build(tmp_path)
    anchor=seed(service,30,1,
        text="Lead Name: D'Arcy-7 O'Neil Address: 101 First Ave, Lacey, WA Phone: 1")
    same_letters=seed(service,31,1,
        text='Lead Name: Darcy ONeil Address: 999 Other Rd, Lacey, WA Phone: 2')
    one_letter=seed(service,32,1,
        text='Lead Name: Darcy X ONeil Address: 998 Other Rd, Lacey, WA Phone: 3')
    two_letters=seed(service,33,1,
        text='Lead Name: Darcy XX ONeil Address: 997 Other Rd, Lacey, WA Phone: 4')
    exact_address=seed(service,34,1,
        text='Lead Name: Completely Different Address: 101 FIRST AVE, Lacey, WA Phone: 5')
    wrong_house=seed(service,35,1,
        text='Lead Name: Unrelated Person Address: 102 First Ave, Lacey, WA Phone: 6')

    ids={row['id'] for row in service.related(anchor)['items']}
    assert anchor in ids
    assert same_letters in ids  # apostrophe, hyphen and digit do not affect name identity
    assert one_letter in ids
    assert two_letters not in ids
    assert exact_address in ids  # exact normalized address fallback remains
    assert wrong_house not in ids  # house numbers still matter for address identity


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
    template=(root/'gallery/form_template.py').read_text()
    processing=(root/'gallery/processing.py').read_text()
    assert 'printer_app' not in s and 'gmail' not in s.lower()
    assert 'csv.QUOTE_NONE' in s
    assert 'sqlite3' not in template and 'flask' not in template and 'gmail' not in template.lower()
    assert 'Image.fromarray(crop).save(path, optimize=True)' in processing

    access_service=(root/'gallery/access_service.py').read_text()
    access_repository=(root/'gallery/access_repository.py').read_text()
    gallery_ui=(root/'static/gallery.js').read_text()
    offline_runtime=(root/'static/gallery_offline.js').read_text()
    network_runtime=(root/'static/gallery_network.js').read_text()
    service_worker=(root/'static/gallery_sw.js').read_text()
    assert 'sqlite3' not in access_service and 'flask' not in access_service
    assert 'flask' not in access_repository
    assert "'edit_identity'" in access_service
    web_source=(root/'gallery/web.py').read_text()
    assert "require('edit_identity')" in web_source
    assert "'gallery.import_item_lead_name'" in web_source
    assert "if (!selected?.id || !editIdentityCapability()) return;" in gallery_ui
    assert 'indexedDB' not in gallery_ui and 'localStorage' not in gallery_ui
    assert 'indexedDB' in offline_runtime and '/gallery/api/offline/index' in offline_runtime
    assert 'const nameLetters' in offline_runtime
    assert "unicodedata.category(c).startswith('L')" in (root/'gallery/policy.py').read_text()
    assert 'navigator.onLine' not in gallery_ui and 'navigator.onLine' not in offline_runtime
    assert 'class GalleryNetwork' in network_runtime and 'AbortController' in network_runtime
    assert "gallery_network.js" in service_worker and "serviceWorker.register" in offline_runtime
