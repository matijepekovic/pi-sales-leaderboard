"""Work-order identity and one shared Lead status, independent of appointments."""
import sqlite3

import pytest

from printer_app.gallery.repository import GalleryRepository, SCHEMA


DAY = '2026-09-21'


def _seed(repository, *, day=DAY, ident='card', work_order='0007'):
    batch = 'batch' if ident == 'card' else 'batch-' + ident
    repository.enqueue(batch, 'cards.pdf')
    repository.finish(batch, [dict(
        id=ident, import_id=batch, filename='card.png', page=1, part=1,
        text=f'Work Order Number: {work_order}\nLead Name: Jordan Example\nAddress: 123 Main St',
        document_date=day, date_status='printed', bytes=123, created=100,
    )])


@pytest.fixture
def repository(tmp_path):
    result = GalleryRepository(tmp_path / 'gallery.db')
    result.initialize()
    _seed(result)
    return result


def _record(number='0007', lead='lead-1', status='Sold'):
    return dict(work_order_number=number, lead_source_id=lead, sales_lead_status=status)


def _publish(repository, status='Sold', *, number='0007', lead='lead-1', captured=100):
    return repository.replace_work_order_lead_statuses([number], [_record(number, lead, status)], captured)


def test_existing_database_migrates_without_changing_saved_cards(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute("""INSERT INTO imports(id,filename,created,updated)
            VALUES('batch','cards.pdf',100,100)""")
        connection.execute("""INSERT INTO items(id,import_id,page,part,filename,text,
            document_date,date_status,bytes,created)
            VALUES('card','batch',1,1,'card.png','Lead Name: Jordan Example',
                   '2026-09-21','printed',123,100)""")
    repository = GalleryRepository(path)
    repository.initialize()
    item = repository.item('card')
    assert item['sales_lead_status'] == item['lead_source_id'] == ''
    assert item['lead_name'] == 'Jordan Example'
    assert item['lead_status'] == 'printed'
    assert item['bytes'] == 123
    repository.initialize()
    assert repository.item('card') == item


def test_existing_displayed_status_survives_until_successful_direct_lookup(repository):
    with repository.connect() as c:
        c.execute("UPDATE items SET lead_source_id='legacy-lead',sales_lead_status='Sold' WHERE id='card'")
        c.execute('DROP TABLE work_order_leads')
    repository.initialize()
    before = repository.item('card')
    assert repository.refresh_sales_lead_status('card') == 0
    repository.replace_reference_snapshot(DAY, 'final', [], 200)
    assert repository.item('card')['sales_lead_status'] == 'Sold'
    assert repository.item('card')['lead_source_id'] == 'legacy-lead'
    assert repository.replace_work_order_lead_statuses(['0007'], [], 201) == 1
    assert repository.item('card')['sales_lead_status'] == repository.item('card')['lead_source_id'] == ''
    assert repository.item('card')['text'] == before['text']


@pytest.mark.parametrize('projection', [
    lambda repository: repository.item('card'),
    lambda repository: repository.list_items()['items'][0],
    lambda repository: repository.offline_items()[0],
    lambda repository: repository.related_candidates()[0],
    lambda repository: repository.import_job('batch')['items'][0],
    lambda repository: repository.import_item('batch', 'card'),
    lambda repository: repository.reference_items(DAY)[0],
    lambda repository: repository.reference_item('card'),
], ids=['detail', 'list', 'offline', 'related', 'import-list', 'import-detail', 'reference-list', 'reference-detail'])
def test_sales_status_is_available_in_every_card_projection(repository, projection):
    _publish(repository)
    assert projection(repository)['sales_lead_status'] == 'Sold'


def test_status_only_change_invalidates_offline_data_and_preserves_card_content(repository):
    _publish(repository, 'Open')
    repository.correct_lead('card', 'Jordan Example')
    repository.add_note('card', 'note-1', 'Tester', 'Keep this note.')
    before = repository.item('card')
    assert _publish(repository, captured=101) == 1
    after = repository.item('card')
    assert after['sales_lead_status'] == 'Sold'
    assert after['search_revision'] == before['search_revision'] + 1
    for field in ('text', 'lead_name', 'lead_status', 'address', 'document_date',
                  'work_order_number', 'notes', 'image_revision'):
        assert after[field] == before[field]
    assert after['lead_status'] == 'confirmed'
    assert _publish(repository, captured=102) == 0
    assert repository.item('card') == after
    repository.initialize()
    assert repository.item('card') == after


def test_status_propagates_across_all_dates_and_orders_of_same_lead_only(repository):
    for ident, number, day in [('old', '0008', '2020-01-01'), ('future', '0007', '2030-01-01'),
                               ('undated', '0008', None), ('different-lead', '0009', DAY),
                               ('unlinked', '0010', DAY)]:
        _seed(repository, ident=ident, work_order=number, day=day)
    with repository.connect() as c:
        c.execute("UPDATE items SET state='REVIEW' WHERE id='undated'")
    repository.replace_work_order_lead_statuses(['0007', '0008', '0009'], [
        _record(status='Open'), _record('0008', status='Open'), _record('0009', 'lead-2', 'New'),
    ], 100)
    assert _publish(repository, captured=200) == 4
    for ident in ('card', 'old', 'future', 'undated'):
        row = repository.reference_item(ident)
        assert row['sales_lead_status'] == 'Sold'
        assert row['lead_source_id'] == 'lead-1'
    assert repository.item('different-lead')['sales_lead_status'] == 'New'
    assert repository.item('unlinked')['sales_lead_status'] == ''
    assert repository.item('old')['document_date'] == '2020-01-01'


@pytest.mark.parametrize('replacement', ['missing', 'blank-id', 'ambiguous'])
def test_completed_lookup_clears_unknown_order_mapping_but_not_other_orders(repository, replacement):
    _seed(repository, ident='other-order', work_order='0008')
    repository.replace_work_order_lead_statuses(['0007', '0008'], [_record(), _record('0008')], 100)
    rows = [] if replacement == 'missing' else [_record(lead='')] if replacement == 'blank-id' else [
        _record(), _record(lead='another-lead')]
    assert repository.replace_work_order_lead_statuses(['0007'], rows, 200) == 1
    assert repository.item('card')['lead_source_id'] == repository.item('card')['sales_lead_status'] == ''
    assert repository.item('other-order')['sales_lead_status'] == 'Sold'
    assert repository.replace_work_order_lead_statuses(['0007'], rows, 201) == 0


def test_blank_current_status_clears_all_cards_but_keeps_lead_identity(repository):
    _seed(repository, ident='other-order', work_order='0008')
    repository.replace_work_order_lead_statuses(['0007', '0008'], [_record(), _record('0008')], 100)
    assert _publish(repository, '', captured=200) == 2
    for ident in ('card', 'other-order'):
        assert repository.item(ident)['sales_lead_status'] == ''
        assert repository.item(ident)['lead_source_id'] == 'lead-1'


def test_older_results_cannot_restore_missing_mapping_or_overwrite_current_status(repository):
    _publish(repository, 'Open', captured=100)
    _publish(repository, captured=200)
    assert _publish(repository, 'Open', captured=150) == 0
    assert repository.item('card')['sales_lead_status'] == 'Sold'
    repository.replace_work_order_lead_statuses(['0007'], [], 300)
    assert _publish(repository, captured=250) == 0
    assert repository.item('card')['lead_source_id'] == repository.item('card')['sales_lead_status'] == ''
    assert _publish(repository, captured=301) == 1


@pytest.mark.parametrize('single_batch', [True, False])
def test_conflicting_status_at_same_capture_stays_unavailable_until_newer_result(repository, single_batch):
    if single_batch:
        repository.replace_work_order_lead_statuses(['0007'], [_record(status='Open'), _record()], 100)
    else:
        _publish(repository, 'Open', captured=100)
        _publish(repository, captured=100)
    assert repository.item('card')['sales_lead_status'] == ''
    _publish(repository, captured=100)
    assert repository.item('card')['sales_lead_status'] == ''
    _publish(repository, captured=101)
    assert repository.item('card')['sales_lead_status'] == 'Sold'


def test_conflicting_mapping_at_same_capture_does_not_guess_an_identity(repository):
    _publish(repository)
    _publish(repository, lead='lead-2')
    assert repository.item('card')['lead_source_id'] == ''
    _publish(repository)
    assert repository.item('card')['lead_source_id'] == ''
    _publish(repository, captured=101)
    assert repository.item('card')['lead_source_id'] == 'lead-1'


def test_unrequested_records_cannot_change_cached_associations(repository):
    _publish(repository)
    repository.replace_work_order_lead_statuses(['0008'], [_record(lead='wrong-lead', status='New')], 200)
    assert repository.item('card')['sales_lead_status'] == 'Sold'
    assert repository.item('card')['lead_source_id'] == 'lead-1'


def test_late_card_uses_cached_mapping_and_latest_shared_status_without_appointment(repository):
    _publish(repository, 'Open', number='0008')
    _publish(repository, captured=200)
    _seed(repository, ident='late', work_order='0008', day=None)
    assert repository.item('late')['sales_lead_status'] == 'Sold'
    assert repository.item('late')['lead_source_id'] == 'lead-1'


@pytest.mark.parametrize('new_day', ['2026-09-22', DAY, None])
def test_date_correction_preserves_lead_identity_and_status(repository, new_day):
    _publish(repository)
    repository.correct_date('card', new_day)
    assert repository.item('card')['lead_source_id'] == 'lead-1'
    assert repository.item('card')['sales_lead_status'] == 'Sold'
    _publish(repository, 'Open', captured=200)
    assert repository.item('card')['sales_lead_status'] == 'Open'


@pytest.mark.parametrize('work_order,expected_lead,expected_status', [
    ('0007', 'lead-1', 'Sold'), ('0008', 'lead-2', 'New'), ('0009', '', ''),
])
def test_corrected_work_order_reattaches_its_own_cached_lead(repository, work_order, expected_lead, expected_status):
    _publish(repository)
    _publish(repository, 'New', number='0008', lead='lead-2')
    repository.correct_lead('card', 'Jordan Example')
    before = repository.item('card')
    repository.repair_recognition('card', before['text'].replace('0007', work_order),
        before['lead_name'], before['lead_key'], before['address'], before['address_key'], work_order, work_order)
    after = repository.item('card')
    assert after['lead_source_id'] == expected_lead
    assert after['sales_lead_status'] == expected_status
    assert after['lead_status'] == 'confirmed'
    _publish(repository, 'Canceled', captured=200)
    if work_order != '0007':
        assert repository.item('card')['sales_lead_status'] == expected_status


def test_delayed_refresh_guard_ignores_old_work_order_but_never_requires_date(repository):
    _publish(repository)
    with repository.connect() as c:
        c.execute("UPDATE items SET sales_lead_status='Open' WHERE id='card'")
    assert repository.refresh_sales_lead_status('card', expected_work_order_key='0008') == 0
    assert repository.item('card')['sales_lead_status'] == 'Open'
    repository.correct_date('card', None)
    assert repository.refresh_sales_lead_status('card', expected_work_order_key='0007') == 1
    assert repository.item('card')['sales_lead_status'] == 'Sold'


def test_appointment_snapshots_and_enrichment_cannot_change_shared_lead_status(repository):
    _publish(repository)
    repository.replace_reference_snapshot(DAY, 'final', [dict(
        source_id='appointment', **_record(lead='wrong-lead', status='Open'))], 200)
    row = repository.reference_item('card')
    repository.apply_reference('card', 'appointment', 'final', 'Example Rep', row['text'],
                               row['lead_name'], row['address'], expected_day=DAY, expected_work_order_key='0007')
    assert repository.item('card')['sales_lead_status'] == 'Sold'
    assert repository.item('card')['lead_source_id'] == 'lead-1'
    assert repository.sales_status_for_lead('wrong-lead') == ''
    assert repository.reference_matches(DAY, 'final', '0007')[0]['sales_lead_status'] == ''


def test_requested_work_orders_include_all_retained_cards_but_not_expired_reference_history(repository):
    _seed(repository, ident='undated', day=None, work_order='0008')
    _seed(repository, ident='future', day='2030-01-01', work_order='0009')
    _seed(repository, ident='duplicate', day='2020-01-01', work_order='0007')
    _seed(repository, ident='deleted', work_order='0010')
    with repository.connect() as c:
        c.execute("UPDATE items SET state='REVIEW' WHERE id='undated'")
        c.execute("UPDATE items SET state='DELETING' WHERE id='deleted'")
    repository.replace_reference_snapshot('2020-01-01', 'morning', [dict(source_id='ref', work_order_number='0011')], 100)
    assert repository.work_order_numbers() == ['0007', '0008', '0009']


def test_housekeeping_keeps_reference_only_mapping_for_later_scan_and_removes_orphans(repository):
    _publish(repository)
    _publish(repository, number='0008')
    repository.replace_reference_snapshot(DAY, 'morning', [dict(source_id='ref', work_order_number='0008')], 100)
    repository.housekeeping(0)
    _seed(repository, ident='late', work_order='0008')
    assert repository.item('late')['sales_lead_status'] == 'Sold'
    repository.replace_reference_snapshot(DAY, 'morning', [], 200)
    for ident in repository.expiring(DAY):
        repository.forget(ident)
    repository.housekeeping(0)
    assert repository.sales_status_for_lead('lead-1') == ''
