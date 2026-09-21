"""Field search uses stored card identities and the existing search index."""
import json
from pathlib import Path
import time

import pytest

from printer_app.gallery.bootstrap import build
from printer_app.gallery.policy import search_expression


FIXTURE = json.loads(Path(__file__).with_name('gallery_search_cases.json').read_text(encoding='utf-8'))


def seed(service, cards=FIXTURE['cards']):
    service.initialize()
    for card in cards:
        ident = card['id']
        service.repository.enqueue(ident, 'Hiddenonly.pdf')
        service.repository.finish(ident, [dict(
            id=ident, import_id=ident, filename='Hiddenonly.png', page=1, part=1,
            text=f"Lead Name: {card['lead_name']}\nAddress: {card['address']}\n{card['text']}",
            lead_text=f"Lead Name: {card['lead_name']}", document_date=card['document_date'],
            date_status='printed', bytes=1, created=time.time(),
        )])
        item = service.item(ident)
        service.repository.apply_reference(ident, ident, 'final', card['assigned_service_resource'],
                                           item['text'], card['lead_name'], card['address'])
    return service


@pytest.fixture
def gallery(tmp_path):
    service = seed(build(tmp_path))
    service.note('rep-card', 'a' * 32, 'Tester', 'Noteonly Oak')
    return service


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: f"{case['field']}:{case['q']}:{case.get('date', '')}")
def test_scoped_search_matches_shared_online_offline_cases(gallery, case):
    result = gallery.search(case['q'], 0, case.get('date', ''), field=case['field'])
    assert sorted(row['id'] for row in result['items']) == case['ids']
    assert result['total'] == len(case['ids'])


def test_date_buckets_and_pagination_stay_within_selected_field(gallery):
    cards = [dict(FIXTURE['cards'][0], id=f'rep-{index:02}', document_date='2026-09-20') for index in range(25)]
    seed(gallery, cards)
    first = gallery.search('Taylor', 0, field='rep')
    second = gallery.search('Taylor', 24, field='rep')
    assert first['total'] == second['total'] == 26
    assert len(first['items']) == 24 and len(second['items']) == 2
    assert not {row['id'] for row in first['items']} & {row['id'] for row in second['items']}
    filtered = gallery.search('Taylor', 0, '2026-09-21', field='rep')
    assert filtered['total'] == 1
    assert filtered['dates'] == [dict(date='2026-09-21', count=1), dict(date='2026-09-20', count=25)]


def test_existing_index_migrates_and_tracks_corrections_without_losing_notes(gallery):
    repository = gallery.repository
    before = gallery.item('rep-card')
    with repository.connect() as c:
        for event in ('insert', 'update', 'delete'):
            c.execute('DROP TRIGGER gallery_' + event)
        c.execute('DROP TABLE search')
        c.execute("""CREATE VIRTUAL TABLE search USING fts5(text,notes_text,filename,lead_name,
            content='items',content_rowid='rowid',tokenize='unicode61 remove_diacritics 2',prefix='2 3 4')""")
        c.execute("INSERT INTO search(search) VALUES('rebuild')")
    repository.initialize()
    repository.initialize()
    assert gallery.item('rep-card') == before
    for field, query in [('rep', 'Jose'), ('lead_name', 'Morgan'), ('address', 'Cedar')]:
        assert gallery.search(query, 0, field=field)['items'][0]['id'] == 'rep-card'
    repository.apply_reference('rep-card', 'updated', 'final', 'New Representative', before['text'],
                               'Corrected Customer', '999 Revised Avenue')
    for field, old, new in [('rep', 'Jose', 'New'), ('lead_name', 'Rivera', 'Corrected'), ('address', 'Cedar', 'Revised')]:
        assert gallery.search(old, 0, field=field)['total'] == 0
        assert gallery.search(new, 0, field=field)['items'][0]['id'] == 'rep-card'
    after = gallery.item('rep-card')
    assert after['notes'] == before['notes'] and after['document_date'] == before['document_date']
    assert 'rep-card' in repository.expiring('2026-09-21')
    repository.forget('rep-card')
    with repository.connect() as c:
        assert not c.execute("SELECT 1 FROM items WHERE id='rep-card'").fetchone()
        c.execute("INSERT INTO search(search,rank) VALUES('integrity-check',1)")
    assert gallery.search('New', 0, field='rep')['total'] == 0


@pytest.mark.parametrize('field', ['', 'notes', 'text', 'rep) OR text:', 'lead_name; DROP TABLE items'])
def test_search_field_is_whitelisted_even_for_blank_queries(field):
    for query in ('', 'Taylor'):
        with pytest.raises(ValueError, match='Choose Rep'):
            search_expression(query, field)


def test_http_defaults_to_customer_name_and_rejects_unknown_fields(tmp_path):
    from printer_app.app import create_app
    from printer_app.config import Config

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path, env_file=env, secret_key='s' * 64, email_enabled=False))
    seed(build(tmp_path))
    client = app.test_client()
    assert client.get('/gallery/api/items?field=rep&q=Taylor').status_code == 401
    token = app.extensions['gallery_access'].issue_full_invite()
    assert client.get('/gallery/access/' + token).status_code == 303
    result = client.get('/gallery/api/items?q=Taylor').get_json()
    assert [row['id'] for row in result['items']] == ['lead-card']
    for field, expected in [('rep', 'rep-card'), ('lead_name', 'lead-card'), ('address', 'address-card')]:
        response = client.get('/gallery/api/items', query_string=dict(field=field, q='Taylor'))
        assert response.status_code == 200
        assert [row['id'] for row in response.get_json()['items']] == [expected]
    for query in ('', 'Taylor'):
        response = client.get('/gallery/api/items', query_string=dict(field='notes', q=query))
        assert response.status_code == 400
    assert client.get('/gallery/api/items', query_string=dict(field='address', q='Taylor', date='2026-09-21')).get_json()['total'] == 0
