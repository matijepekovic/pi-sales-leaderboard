"""Printed observations survive storage without becoming customer contact data."""
import json

import pytest

from printer_app.gallery.policy import normalize_work_order_evidence
from printer_app.gallery.repository import GalleryRepository


DAY = '2026-09-21'
NUMBER = '02278850'
EVIDENCE = {
    'names': ['Printed Customer'],
    'dates': [DAY],
    'times': ['10:30'],
    'phones': ['360-555-1212'],
}
ABSENT = object()


@pytest.fixture
def repository(tmp_path):
    repo = GalleryRepository(tmp_path / 'gallery.db')
    repo.initialize()
    return repo


def _save(repo, *, number='', candidates=(NUMBER,), evidence=EVIDENCE,
          image='image-one', replace=False, batch='batch', legacy=False):
    repo.enqueue(batch, 'cards.pdf')
    entry = dict(id='card', import_id=batch, page=1, part=1, filename='card.png',
                 text='Work Order Number: ' + number, document_date=DAY,
                 date_status='printed', bytes=100, created=1.0,
                 work_order_number=number, recognition_revision=1,
                 image_revision=image, replace_existing=replace)
    if not legacy:
        entry['work_order_candidates'] = candidates
    if evidence is not ABSENT:
        entry['work_order_evidence'] = evidence
    repo.finish(batch, [entry])


def _accept(repo, *, candidates=(NUMBER,), **guards):
    return repo.apply_validated_work_order_reference(
        'card', candidates, NUMBER, 'source-work-order',
        'Work Order Number: ' + NUMBER + '\nLead Name: Source Customer',
        'Source Customer', 'Source Address', 'Source Rep', DAY, 'source-lead', 'Sold',
        **guards,
    )


def test_evidence_roundtrips_all_repository_views_without_populating_identity(repository):
    _save(repository)
    expected = normalize_work_order_evidence(EVIDENCE)
    reopened = GalleryRepository(repository.path)
    reopened.initialize()

    pending = reopened.work_order_candidate_items()[0]
    views = [pending, reopened.reference_item('card'), reopened.import_item('batch', 'card'),
             reopened.import_job('batch')['items'][0]]
    assert all(row['work_order_evidence'] == expected for row in views)
    assert all(row['image_revision'] == 'image-one' for row in views)
    assert pending['candidates'] == (NUMBER,)
    assert 'Printed Customer' not in pending['text']
    assert '360' not in pending['text']
    assert reopened.reference_item('card')['lead_name'] == ''
    assert reopened.reference_item('card')['work_order_number'] == ''
    assert reopened.reference_item('card')['state'] == 'REVIEW'
    reopened.approve_import_item('batch', 'card')
    assert reopened.item('card')['work_order_evidence'] == expected


def test_new_scan_image_replaces_evidence_even_when_new_payload_omits_it(repository):
    _save(repository, number=NUMBER, candidates=())
    repository.add_note('card', 'note', 'Office', 'Keep this note')

    _save(repository, number=NUMBER, candidates=(), evidence=ABSENT,
          image='image-two', replace=True, batch='replacement')

    row = repository.item('card')
    assert row['image_revision'] == 'image-two'
    assert row['work_order_evidence'] == normalize_work_order_evidence({})
    assert row['notes'][0]['body'] == 'Keep this note'


def test_status_and_source_enrichment_preserve_printed_evidence(repository):
    _save(repository, number=NUMBER, candidates=())
    expected = repository.item('card')['work_order_evidence']
    repository.replace_work_order_lead_statuses([NUMBER], [dict(
        work_order_number=NUMBER, lead_source_id='source-lead', sales_lead_status='Sold')], 100)
    repository.apply_work_order_reference(
        'card', NUMBER, 'source-work-order', 'Lead Name: Renamed Customer',
        'Renamed Customer', 'Source Address', '', '', 'source-lead', 'Sold')

    row = repository.item('card')
    assert row['lead_name'] == 'Renamed Customer'
    assert row['work_order_evidence'] == expected
    assert row['sales_lead_status'] == 'Sold'


def test_migration_adds_empty_evidence_without_rewriting_accepted_legacy_row(repository):
    _save(repository, number=NUMBER, legacy=True)
    repository.approve_import_item('batch', 'card')
    repository.add_note('card', 'note', 'Office', 'Keep legacy note')
    with repository.connect() as c:
        c.execute('ALTER TABLE items DROP COLUMN work_order_evidence')
        before = dict(c.execute("SELECT * FROM items WHERE id='card'").fetchone())

    repository.initialize()

    with repository.connect() as c:
        after = dict(c.execute("SELECT * FROM items WHERE id='card'").fetchone())
    assert after == dict(before, work_order_evidence='{}')
    assert repository.item('card')['notes'][0]['body'] == 'Keep legacy note'
    assert repository.save_work_order_candidates('card', (NUMBER,), evidence={}) == 0
    assert repository.item('card')['work_order_evidence'] == normalize_work_order_evidence({})


def test_recognition_retry_exposes_printed_batch_date_and_saves_new_evidence(repository):
    _save(repository, candidates=())
    before = repository.recognition_candidate(1000)
    assert (before['document_date'], before['date_status']) == (DAY, 'printed')
    assert before['image_revision'] == 'image-one'
    new_evidence = dict(EVIDENCE, names=['Second Observation'])

    assert repository.save_work_order_candidates(
        'card', (NUMBER,), expected_text=before['text'],
        expected_image_revision=before['image_revision'], evidence=new_evidence) == 1

    pending = repository.work_order_candidate_items()[0]
    assert pending['work_order_evidence'] == normalize_work_order_evidence(new_evidence)
    assert pending['state'] == 'REVIEW'


def test_legacy_recognition_retry_omitting_evidence_preserves_existing_observations(repository):
    _save(repository, candidates=())
    assert repository.save_work_order_candidates('card', (NUMBER,)) == 1
    assert repository.work_order_candidate_items()[0]['work_order_evidence'] == (
        normalize_work_order_evidence(EVIDENCE))


@pytest.mark.parametrize('guard', ['text', 'image'])
def test_recognition_retry_cannot_write_over_a_changed_snapshot(repository, guard):
    _save(repository, candidates=())
    before = repository.recognition_candidate(1000)
    options = dict(expected_text=before['text'], expected_image_revision=before['image_revision'])
    options['expected_text' if guard == 'text' else 'expected_image_revision'] = 'older-value'

    assert repository.save_work_order_candidates('card', (NUMBER,), evidence={}, **options) == 0
    assert repository.recognition_candidate(1000) == before


@pytest.mark.parametrize('changed', ['evidence', 'image', 'candidates'])
def test_source_validation_rejects_changed_proof_without_mutating_card(repository, changed):
    _save(repository)
    before = repository.work_order_candidate_items()[0]
    guards = dict(expected_evidence=before['work_order_evidence'],
                  expected_image_revision=before['image_revision'])
    if changed == 'evidence':
        guards['expected_evidence'] = dict(EVIDENCE, times=['11:30'])
    if changed == 'image':
        guards['expected_image_revision'] = 'earlier-image'
    candidates = ('02345678',) if changed == 'candidates' else before['candidates']

    assert _accept(repository, candidates=candidates, **guards) == 0
    assert repository.work_order_candidate_items()[0] == before


def test_source_validation_keeps_evidence_after_accepting_exact_snapshot(repository):
    _save(repository)
    before = repository.work_order_candidate_items()[0]

    assert _accept(repository, expected_evidence=before['work_order_evidence'],
                   expected_image_revision=before['image_revision']) == 1

    row = repository.item('card')
    assert row['work_order_evidence'] == before['work_order_evidence']
    assert row['work_order_number'] == NUMBER
    assert row['lead_name'] == 'Source Customer'
    assert repository.work_order_candidate_items() == []


def test_evidence_guard_compares_normalized_payload_not_json_formatting(repository):
    _save(repository)
    with repository.connect() as c:
        c.execute("UPDATE items SET work_order_evidence=? WHERE id='card'",
                  (json.dumps(dict(reversed(list(EVIDENCE.items()))), indent=2),))
    assert _accept(repository, expected_evidence=normalize_work_order_evidence(EVIDENCE),
                   expected_image_revision='image-one') == 1


@pytest.mark.parametrize('stored', ['not-json', 'null', '[]', '{"names": "not-a-list"}'])
def test_malformed_stored_evidence_is_empty_at_repository_boundary(repository, stored):
    _save(repository)
    with repository.connect() as c:
        c.execute("UPDATE items SET work_order_evidence=? WHERE id='card'", (stored,))
    assert repository.import_item('batch', 'card')['work_order_evidence'] == (
        normalize_work_order_evidence({}))
    assert repository.work_order_candidate_items()[0]['work_order_evidence'] == (
        normalize_work_order_evidence({}))
