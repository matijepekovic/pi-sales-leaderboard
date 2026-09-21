"""Persist source lead status separately from Gallery name confirmation."""
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


def _apply(repository, status='Sold', *, ident='card', lead_source_id='', **guards):
    row = repository.reference_item(ident)
    return repository.apply_reference(
        ident, 'appointment-7', 'final', 'Example Rep', row['text'],
        row['lead_name'], row['address'], sales_lead_status=status,
        lead_source_id=lead_source_id, **guards,
    )


def test_existing_database_migrates_with_blank_status_and_keeps_saved_data(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute("""INSERT INTO imports(id,filename,created,updated)
            VALUES('batch','cards.pdf',100,100)""")
        connection.execute("""INSERT INTO items(id,import_id,page,part,filename,text,
            document_date,date_status,bytes,created)
            VALUES('card','batch',1,1,'card.png','Lead Name: Jordan Example',
                   '2026-09-21','printed',123,100)""")
        connection.execute("""INSERT INTO appointment_references(day,kind,source_id,work_order_number)
            VALUES('2026-09-21','final','appointment-7','0007')""")

    repository = GalleryRepository(path)
    repository.initialize()
    repository.initialize()

    item = repository.item('card')
    assert item['sales_lead_status'] == ''
    assert item['lead_source_id'] == ''
    assert item['lead_name'] == 'Jordan Example'
    assert item['lead_status'] == 'printed'
    assert item['bytes'] == 123
    _, references = repository.reference_snapshot(DAY, 'final')
    assert references[0]['sales_lead_status'] == ''
    assert references[0]['lead_source_id'] == ''
    assert references[0]['work_order_number'] == '0007'


def test_new_cards_default_to_no_sales_status(repository):
    assert repository.item('card')['sales_lead_status'] == ''
    assert repository.item('card')['lead_status'] == 'printed'


def test_saved_status_and_name_confirmation_survive_reinitialization(repository):
    _apply(repository, 'Sold')
    repository.correct_lead('card', 'Jordan Example')
    before = repository.item('card')
    repository.initialize()
    repository.initialize()
    assert repository.item('card') == before


def test_reference_snapshots_keep_status_per_date_and_work_order(repository):
    repository.replace_reference_snapshot(DAY, 'final', [dict(
        source_id='appointment-7', work_order_number='0007', sales_lead_status='Sold',
        assigned_service_resources=['Example Rep'],
    )], 100)
    repository.replace_reference_snapshot('2026-09-22', 'final', [dict(
        source_id='appointment-8', work_order_number='0007', sales_lead_status='Open',
    )], 101)
    repository.initialize()

    _, references = repository.reference_snapshot(DAY, 'final')
    assert references[0]['sales_lead_status'] == 'Sold'
    assert references[0]['assigned_service_resources'] == ('Example Rep',)
    assert repository.reference_matches(DAY, 'final', '0007')[0]['sales_lead_status'] == 'Sold'
    assert repository.reference_matches('2026-09-22', 'final', '0007')[0]['sales_lead_status'] == 'Open'
    assert repository.reference_matches(DAY, 'final', '0008') == []

    repository.replace_reference_snapshot(DAY, 'final', [dict(
        source_id='appointment-7', work_order_number='0007',
    )], 102)
    assert repository.reference_matches(DAY, 'final', '0007')[0]['sales_lead_status'] == ''


def test_snapshot_presence_distinguishes_empty_capture_from_missing_day_or_kind(repository):
    assert not repository.has_reference_snapshot(DAY, 'final')
    repository.replace_reference_snapshot(DAY, 'morning', [], 100)
    assert repository.has_reference_snapshot(DAY, 'morning')
    assert not repository.has_reference_snapshot(DAY, 'final')
    assert not repository.has_reference_snapshot('2026-09-22', 'morning')

    repository.replace_reference_snapshot(DAY, 'final', [], 101)
    assert repository.has_reference_snapshot(DAY, 'final')
    assert not repository.has_reference_snapshot('2026-09-22', 'final')
    assert repository.reference_snapshot(DAY, 'final')[1] == []


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
    _apply(repository, 'Sold')
    assert projection(repository)['sales_lead_status'] == 'Sold'


def test_status_only_change_invalidates_offline_data_and_preserves_name_confirmation(repository):
    _apply(repository, 'Open')
    repository.correct_lead('card', 'Jordan Example')
    repository.add_note('card', 'note-1', 'Tester', 'Keep this note.')
    before = repository.item('card')

    assert _apply(repository, 'Sold') == 1
    after = repository.item('card')
    assert after['sales_lead_status'] == 'Sold'
    assert after['search_revision'] == before['search_revision'] + 1
    for field in ('text', 'lead_name', 'lead_status', 'address', 'document_date',
                  'work_order_number', 'notes', 'image_revision'):
        assert after[field] == before[field]
    assert after['lead_status'] == 'confirmed'
    assert _apply(repository, 'Sold') == 0
    assert repository.item('card')['search_revision'] == after['search_revision']


@pytest.mark.parametrize('explicit_empty', [True, False])
def test_empty_status_in_matched_reference_replaces_previous_value(repository, explicit_empty):
    _apply(repository, 'Sold')
    before = repository.item('card')
    if explicit_empty:
        changed = _apply(repository, '')
    else:
        changed = repository.apply_reference(
            'card', 'appointment-7', 'final', 'Example Rep', before['text'],
            before['lead_name'], before['address'],
        )
    assert changed == 1
    after = repository.item('card')
    assert after['sales_lead_status'] == ''
    assert after['search_revision'] == before['search_revision'] + 1


@pytest.mark.parametrize('state', ['ACTIVE', 'REVIEW'])
def test_unmatched_status_clear_is_idempotent_and_preserves_card_data(repository, state):
    _apply(repository, 'Canceled')
    repository.correct_lead('card', 'Jordan Example')
    before = repository.item('card')
    with repository.connect() as connection:
        connection.execute('UPDATE items SET state=? WHERE id=?', (state, 'card'))

    assert repository.refresh_sales_lead_status('card') == 1
    assert repository.refresh_sales_lead_status('card') == 0
    with repository.connect() as connection:
        after = dict(connection.execute("SELECT * FROM items WHERE id='card'").fetchone())
    assert after['sales_lead_status'] == ''
    assert after['search_revision'] == before['search_revision'] + 1
    assert after['lead_status'] == 'confirmed'
    assert after['text'] == before['text']
    assert after['work_order_number'] == '0007'
    assert after['state'] == state
    assert repository.refresh_sales_lead_status('missing') == 0


@pytest.mark.parametrize('original_day', [DAY, None])
def test_date_change_clears_status_before_new_date_can_be_matched(repository, original_day):
    with repository.connect() as connection:
        connection.execute('UPDATE items SET document_date=? WHERE id=?', (original_day, 'card'))
    _apply(repository, 'Sold')
    repository.correct_lead('card', 'Jordan Example')
    before = repository.item('card')

    repository.correct_date('card', '2026-09-22')
    after = repository.item('card')
    assert after['document_date'] == '2026-09-22'
    assert after['sales_lead_status'] == ''
    assert after['search_revision'] == before['search_revision'] + 1
    assert after['lead_status'] == 'confirmed'
    assert after['work_order_number'] == before['work_order_number']


def test_confirming_same_date_does_not_discard_matched_status(repository):
    _apply(repository, 'Sold')
    before = repository.item('card')
    repository.correct_date('card', DAY)
    after = repository.item('card')
    assert after['date_status'] == 'confirmed'
    assert after['sales_lead_status'] == 'Sold'
    assert after['search_revision'] == before['search_revision']


def _reference(lead_id='lead-1', status='Open', work_order='0007', source_id='appointment-7'):
    return dict(source_id=source_id, work_order_number=work_order,
                lead_name='Jordan Example', lead_source_id=lead_id, sales_lead_status=status)


def test_status_propagates_across_dates_and_work_orders_only_for_same_source_lead(repository):
    _seed(repository, day='2026-09-22', ident='second-order', work_order='0008')
    _seed(repository, day='2026-09-22', ident='same-name-other-lead', work_order='0009')
    _seed(repository, day='2026-09-22', ident='same-name-unlinked', work_order='0010')
    repository.replace_reference_snapshot(DAY, 'final', [
        _reference(), _reference('lead-2', 'New', '0009', 'appointment-9'),
    ], 100)
    _apply(repository, lead_source_id='lead-1')
    _apply(repository, ident='second-order', lead_source_id='lead-1')
    _apply(repository, ident='same-name-other-lead', lead_source_id='lead-2')
    before = {ident: repository.item(ident) for ident in (
        'card', 'second-order', 'same-name-other-lead', 'same-name-unlinked')}

    repository.replace_reference_snapshot('2026-09-23', 'final', [_reference(status='Sold')], 200)
    for ident in ('card', 'second-order'):
        after = repository.item(ident)
        assert after['sales_lead_status'] == 'Sold'
        assert after['search_revision'] == before[ident]['search_revision'] + 1
        for field in ('text', 'lead_name', 'lead_status', 'document_date', 'work_order_number'):
            assert after[field] == before[ident][field]
    assert repository.item('same-name-other-lead') == before['same-name-other-lead']
    assert repository.item('same-name-unlinked') == before['same-name-unlinked']

    unchanged = repository.item('second-order')
    repository.replace_reference_snapshot('2026-09-23', 'final', [_reference(status='Sold')], 201)
    assert repository.item('second-order') == unchanged
    assert repository.reference_matches(DAY, 'final', '0007')[0]['lead_source_id'] == 'lead-1'
    assert repository.reference_items(DAY)[0]['lead_source_id'] == 'lead-1'


def test_newest_lead_status_survives_old_captures_and_removal_of_appointment_snapshot(repository):
    repository.replace_reference_snapshot(DAY, 'morning', [_reference(status='Open')], 100)
    _apply(repository, lead_source_id='lead-1')
    repository.replace_reference_snapshot('2026-09-22', 'final', [_reference(status='Sold')], 200)
    repository.replace_reference_snapshot('2026-09-22', 'final', [], 300)
    repository.replace_reference_snapshot(DAY, 'morning', [_reference(status='Open')], 150)
    assert repository.sales_status_for_lead('lead-1') == 'Sold'
    assert repository.item('card')['sales_lead_status'] == 'Sold'
    assert repository.sales_status_for_lead('missing') == ''
    assert repository.sales_status_for_lead('') == ''
    repository.initialize()
    assert repository.sales_status_for_lead('lead-1') == 'Sold'


def test_current_blank_status_clears_every_card_linked_to_the_lead(repository):
    repository.replace_reference_snapshot(DAY, 'final', [_reference(status='Sold')], 100)
    _apply(repository, lead_source_id='lead-1')
    repository.replace_reference_snapshot('2026-09-22', 'final', [_reference(status='')], 200)
    assert repository.sales_status_for_lead('lead-1') == ''
    assert repository.item('card')['sales_lead_status'] == ''
    assert repository.item('card')['lead_source_id'] == 'lead-1'


@pytest.mark.parametrize('single_batch', [True, False])
def test_conflicting_statuses_at_same_capture_remain_unavailable_until_newer_observation(repository, single_batch):
    if single_batch:
        repository.replace_reference_snapshot(DAY, 'final', [
            _reference(status='Open'), _reference(status='Sold', source_id='appointment-8'),
        ], 100)
    else:
        repository.replace_reference_snapshot(DAY, 'morning', [_reference(status='Open')], 100)
        repository.replace_reference_snapshot(DAY, 'final', [_reference(status='Sold')], 100)
    assert repository.sales_status_for_lead('lead-1') == ''
    repository.replace_reference_snapshot('2026-09-22', 'final', [_reference(status='Sold')], 100)
    assert repository.sales_status_for_lead('lead-1') == ''
    repository.replace_reference_snapshot('2026-09-22', 'final', [_reference(status='Sold')], 101)
    assert repository.sales_status_for_lead('lead-1') == 'Sold'


def test_apply_uses_latest_shared_status_inside_transaction_instead_of_earlier_service_read(repository):
    repository.replace_reference_snapshot(DAY, 'final', [_reference(status='Open')], 100)
    stale_status = repository.sales_status_for_lead('lead-1')
    repository.replace_reference_snapshot(DAY, 'final', [_reference(status='Sold')], 200)
    _apply(repository, stale_status, lead_source_id='lead-1')
    assert repository.item('card')['sales_lead_status'] == 'Sold'


def test_refresh_preserves_confirmed_lead_identity_when_appointment_is_no_longer_present(repository):
    repository.replace_reference_snapshot(DAY, 'final', [_reference(status='Sold')], 100)
    _apply(repository, lead_source_id='lead-1')
    repository.replace_reference_snapshot(DAY, 'final', [], 200)
    with repository.connect() as connection:
        connection.execute("UPDATE items SET sales_lead_status='Open' WHERE id='card'")
    assert repository.refresh_sales_lead_status('card') == 1
    assert repository.item('card')['lead_source_id'] == 'lead-1'
    assert repository.item('card')['sales_lead_status'] == 'Sold'
    assert repository.refresh_sales_lead_status('card') == 0


@pytest.mark.parametrize('method', ['apply', 'refresh'])
@pytest.mark.parametrize('guard', [dict(expected_day='2026-09-20'), dict(expected_work_order_key='0008'),
                                   dict(expected_day=None)])
def test_identity_guard_prevents_delayed_status_write_after_card_identity_changed(repository, method, guard):
    _apply(repository, 'Open')
    before = repository.item('card')
    if method == 'apply':
        changed = _apply(repository, 'Sold', **guard)
    else:
        changed = repository.refresh_sales_lead_status('card', **guard)
    assert changed == 0
    assert repository.item('card') == before


def test_matching_identity_guard_allows_status_update_and_null_date_is_explicit(repository):
    before = repository.reference_item('card')
    assert _apply(repository, 'Sold', expected_day=DAY, expected_work_order_key=before['work_order_key']) == 1
    repository.correct_date('card', None)
    assert _apply(repository, 'Open', expected_day=None, expected_work_order_key=before['work_order_key']) == 1
    assert repository.refresh_sales_lead_status(
        'card', expected_day=None, expected_work_order_key=before['work_order_key']) == 1


def test_changing_date_clears_source_lead_association_before_later_status_propagation(repository):
    repository.replace_reference_snapshot(DAY, 'final', [_reference(status='Sold')], 100)
    _apply(repository, lead_source_id='lead-1')
    repository.correct_date('card', '2026-09-22')
    assert repository.item('card')['lead_source_id'] == ''
    repository.replace_reference_snapshot(DAY, 'final', [_reference(status='Open')], 200)
    assert repository.item('card')['sales_lead_status'] == ''


@pytest.mark.parametrize('work_order', ['0007', '0008'])
def test_recognition_work_order_change_clears_lead_association_but_same_identity_preserves_it(repository, work_order):
    repository.replace_reference_snapshot(DAY, 'final', [_reference(status='Sold')], 100)
    _apply(repository, lead_source_id='lead-1')
    repository.correct_lead('card', 'Jordan Example')
    before = repository.item('card')
    repository.repair_recognition(
        'card', before['text'].replace('0007', work_order), before['lead_name'], before['lead_key'],
        before['address'], before['address_key'], work_order, work_order,
    )
    after = repository.item('card')
    assert after['work_order_number'] == work_order
    assert after['lead_status'] == 'confirmed'
    if work_order == '0007':
        assert after['lead_source_id'] == 'lead-1'
        assert after['sales_lead_status'] == 'Sold'
        assert after['search_revision'] == before['search_revision']
    else:
        assert after['lead_source_id'] == after['sales_lead_status'] == ''
        assert after['search_revision'] == before['search_revision'] + 1
        assert repository.refresh_sales_lead_status('card') == 0


def test_housekeeping_retains_shared_status_for_cards_or_references_and_removes_orphans(repository):
    repository.replace_reference_snapshot(DAY, 'final', [_reference(status='Sold')], 100)
    _apply(repository, lead_source_id='lead-1')
    repository.replace_reference_snapshot(DAY, 'final', [], 200)
    repository.housekeeping(0)
    assert repository.sales_status_for_lead('lead-1') == 'Sold'

    repository.replace_reference_snapshot(DAY, 'final', [_reference(status='Sold')], 300)
    repository.expiring(DAY)
    repository.forget('card')
    repository.housekeeping(0)
    assert repository.sales_status_for_lead('lead-1') == 'Sold'

    repository.replace_reference_snapshot(DAY, 'final', [], 400)
    repository.housekeeping(0)
    assert repository.sales_status_for_lead('lead-1') == ''
