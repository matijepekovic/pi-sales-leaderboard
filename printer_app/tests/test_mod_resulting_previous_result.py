"""Previous Result must come from historical Salesforce Work Orders only."""
import pytest

from printer_app.mod_resulting.historical_result import historical_previous_result
from printer_app.mod_resulting.salesforce_adapter import ResultingSalesforceError


CURRENT = '0WO000000000001AAA'
OLDER = '0WO000000000002AAA'
OLDEST = '0WO000000000003AAA'
FUTURE = '0WO000000000004AAA'
TZ = 'America/Los_Angeles'


def work(ident, when, dispo=None, date_only=''):
    return {
        'Id':ident,
        'Dispo__c':dispo,
        'Appointment_Date_Time__c':when,
        'Appointment_Date__c':date_only,
        'LastModifiedDate':'2026-10-31T12:00:00Z',
    }


def resolve(rows, **kwargs):
    return historical_previous_result(
        rows, CURRENT, timezone_name=TZ, **kwargs
    )


@pytest.mark.parametrize('dispo,expected', [
    ('PNS','Pitch No Sale'), ('Pitch No Sale','Pitch No Sale'),
    ('No Pitch','No Pitch'), ('NP','No Pitch'),
    ('NRA','No Rep Available'), ('No Rep Available','No Rep Available'),
    ('Sale',None), ('CXL',None), ('OOS',None),
])
def test_latest_older_result_only_and_restricted_picklist(dispo, expected):
    rows = [
        work(CURRENT, '2026-10-27T19:00:00Z', 'NRA'),
        work(OLDER, '2026-10-25T19:00:00Z', dispo),
        work(OLDEST, '2026-10-01T19:00:00Z', 'PNS'),
    ]
    assert resolve(rows) == expected


def test_fresh_lead_has_blank_previous_result_not_todays_dispo():
    assert resolve([work(CURRENT,'2026-10-27T19:00:00Z', 'PNS')]) is None


def test_immediately_previous_unresulted_appointment_clears_previous_result():
    assert resolve([
        work(CURRENT,'2026-10-27T19:00:00Z'),
        work(OLDER,'2026-10-26T19:00:00Z'),
        work(OLDEST,'2026-10-25T19:00:00Z','NRA'),
    ]) is None


def test_newer_unresulted_appointment_cannot_use_an_older_result():
    assert resolve([
        work(CURRENT,'2026-10-27T19:00:00Z'),
        work(OLDER,'2026-10-26T19:00:00Z',None),
        work(OLDEST,'2026-10-25T19:00:00Z','PNS'),
    ]) is None


def test_future_result_is_not_previous_even_if_modified_recently():
    assert resolve([
        work(CURRENT,'2026-10-27T19:00:00Z'),
        work(FUTURE,'2026-10-29T19:00:00Z','PNS'),
        work(OLDER,'2026-10-24T19:00:00Z','No Pitch'),
    ]) == 'No Pitch'


def test_equal_timestamp_is_not_an_earlier_appointment():
    assert resolve([
        work(CURRENT,'2026-10-27T19:00:00Z'),
        work(OLDER,'2026-10-27T19:00:00Z','PNS'),
    ]) is None


def test_older_date_only_and_precise_current():
    assert resolve([
        work(CURRENT,'2026-10-27T19:00:00Z'),
        work(OLDER,None,'PNS','2026-10-26'),
    ]) == 'Pitch No Sale'


def test_same_day_date_only_history_is_ambiguous_and_refused():
    with pytest.raises(ResultingSalesforceError,match='same-day Work Order'):
        resolve([
            work(CURRENT,'2026-10-27T19:00:00Z'),
            work(OLDER,None,'PNS','2026-10-27'),
        ])


def test_missing_current_or_previous_appointment_date_is_refused():
    with pytest.raises(ResultingSalesforceError,match='Current Work Order'):
        resolve([work(OLDER,'2026-10-25T19:00:00Z','PNS')])
    with pytest.raises(ResultingSalesforceError,match='no appointment date'):
        resolve([
            work(CURRENT,'2026-10-27T19:00:00Z'),
            work(OLDER,None,'PNS'),
        ])


def test_batch_result_older_than_current_is_eligible_before_sf_write():
    assert resolve([
        work(CURRENT,'2026-10-27T19:00:00Z'),
        work(OLDER,'2026-10-27T18:00:00Z'),
    ], pending_dispositions={OLDER:'PNS'}) == 'Pitch No Sale'


def test_duplicate_historical_ids_are_refused():
    with pytest.raises(ResultingSalesforceError,match='Duplicate historical'):
        resolve([
            work(CURRENT,'2026-10-27T19:00:00Z'),
            work(OLDER,'2026-10-26T19:00:00Z','PNS'),
            work(OLDER,'2026-10-25T19:00:00Z','PNS'),
        ])
