"""Explorer HTTP boundaries: explicit reads, administrator access and no side effects."""
import json
from pathlib import Path

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.salesforce_sandbox.adapter import SalesforceAdapterError
from printer_app.tests.auth_helpers import gallery_client, login_admin


ROOT = '/salesforce-sandbox/api/explorer'
RECORD = '001000000000001AAA'


class ExplorerSource:
    def __init__(self):
        self.calls = []
        self.failure = None

    def read(self, action, **parameters):
        self.calls.append((action, parameters))
        if self.failure:
            raise self.failure
        return {'requested': action, 'parameters': parameters}

    def status(self, **unused):
        raise AssertionError('Explorer must not run the MOD connection workflow')

    def portal_field(self, *args, **kwargs):
        raise AssertionError('Explorer must not load MOD filter data')

    def mod_sheets(self, **unused):
        raise AssertionError('Explorer must not query or generate MOD sheets')

    def explorer_objects(self):
        return self.read('objects')

    def explorer_object(self, name):
        return self.read('object', name=name)

    def explorer_search(self, name, **parameters):
        return self.read('search', name=name, **parameters)

    def explorer_record(self, name, record_id):
        return self.read('record', name=name, record_id=record_id)

    def explorer_related(self, name, record_id, relationship, after=''):
        return self.read('related', name=name, record_id=record_id,
                         relationship=relationship, after=after)


@pytest.fixture
def rig(tmp_path):
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path / 'data', env_file=env,
                            secret_key='e' * 64, email_enabled=False))
    app.testing = True
    source = ExplorerSource()
    app.extensions['salesforce_sandbox'].adapter = source
    client = app.test_client()
    csrf = login_admin(client)
    return app, source, client, csrf


def test_page_shell_does_not_connect_or_fetch_any_source_data(rig):
    app, source, client, _ = rig
    response = client.get('/salesforce-sandbox/explorer')
    assert response.status_code == 200
    assert b'Object Explorer' in response.data
    assert b'data-mod-sheet-runtime' not in response.data
    assert b'mod_sheets/runtime.js' not in response.data
    assert source.calls == []
    assert response.headers['Cache-Control'] == 'no-store'
    assert app.extensions['printer_db'].rows('SELECT * FROM jobs') == []


def test_each_read_route_only_requests_its_selected_exploration_step(rig):
    _, source, client, _ = rig
    cases = [
        ('/objects', 'objects', {}),
        ('/objects/Account', 'object', {'name': 'Account'}),
        (f'/objects/Account/records/{RECORD}', 'record', {'name': 'Account', 'record_id': RECORD}),
        (f'/objects/Account/records/{RECORD}/related/Contacts?after={RECORD}', 'related',
         {'name': 'Account', 'record_id': RECORD, 'relationship': 'Contacts', 'after': RECORD}),
    ]
    for path, action, parameters in cases:
        source.calls.clear()
        response = client.get(ROOT + path)
        assert response.status_code == 200
        assert response.json == {'ok': True, 'requested': action, 'parameters': parameters}
        assert source.calls == [(action, parameters)]
        assert response.headers['Cache-Control'] == 'no-store'


def test_explicit_search_preserves_typed_filters_and_only_reads_records(rig):
    app, source, client, csrf = rig
    filters = [{'field': 'IsWon', 'operator': 'eq', 'value': False},
               {'field': 'Amount', 'operator': 'between', 'value': '100.50', 'value2': '300'}]
    response = client.post(ROOT + '/objects/Opportunity/search', data={
        'csrf': csrf, 'columns': json.dumps(['Id', 'IsWon', 'Amount']),
        'filters': json.dumps(filters), 'match': 'any', 'after': RECORD,
    })
    assert response.status_code == 200
    assert source.calls == [('search', dict(name='Opportunity', columns=['Id', 'IsWon', 'Amount'],
                                          filters=filters, match='any', after=RECORD))]
    db = app.extensions['printer_db']
    for table in ('jobs', 'commands', 'print_attempts', 'print_queue_releases'):
        assert db.rows('SELECT * FROM ' + table) == []


@pytest.mark.parametrize('path', ['/salesforce-sandbox/explorer', ROOT + '/objects',
                                 ROOT + '/objects/Account', ROOT + f'/objects/Account/records/{RECORD}'])
def test_explorer_requires_printer_admin_not_gallery_access(rig, path):
    app, source, _, _ = rig
    for client in (app.test_client(), gallery_client(app)):
        response = client.get(path)
        assert response.status_code == 302
        assert '/login?' in response.headers['Location']
    assert source.calls == []


def test_search_uses_existing_csrf_and_origin_protection(rig):
    _, source, client, csrf = rig
    path = ROOT + '/objects/Account/search'
    assert client.post(path, data={}).status_code == 400
    assert client.post(path, data={'csrf': csrf}, headers={'Origin': 'https://other.example'}).status_code == 403
    assert client.post(path, data={'csrf': csrf}, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.get(path).status_code == 405
    assert client.delete(ROOT + f'/objects/Account/records/{RECORD}').status_code == 405
    assert source.calls == []


@pytest.mark.parametrize(('columns', 'filters'), [('not json', '[]'), ('{}', '[]'),
                                                 ('[]', '{}'), ('[]', '['),
                                                 ('[]', ' ' * 20001)],
                         ids=['invalid-columns-json', 'columns-object', 'filters-object',
                              'invalid-filters-json', 'oversized-filters'])
def test_malformed_search_never_calls_source(rig, columns, filters):
    _, source, client, csrf = rig
    response = client.post(ROOT + '/objects/Account/search', data={
        'csrf': csrf, 'columns': columns, 'filters': filters,
    })
    if len(filters) > 20000:
        # The application's global request-size limit rejects this even before
        # the explorer route parses its filters.
        assert response.status_code == 413
    else:
        assert response.status_code == 400
        assert response.json['ok'] is False
    assert source.calls == []


@pytest.mark.parametrize(('failure', 'status'), [(ValueError('Choose a valid field.'), 400),
                                                (SalesforceAdapterError('Source is unavailable.'), 503)])
def test_source_errors_are_clear_and_never_look_like_empty_results(rig, failure, status):
    _, source, client, _ = rig
    source.failure = failure
    response = client.get(ROOT + '/objects/Account')
    assert response.status_code == status
    assert response.json == {'ok': False, 'error': str(failure)}


def test_unknown_service_action_does_not_dispatch_arbitrary_adapter_methods(rig):
    app, source, _, _ = rig
    snapshot = app.extensions['salesforce_sandbox'].explore('_run')
    assert snapshot.invalid and snapshot.error
    assert source.calls == []


def test_explorer_keeps_queries_and_source_access_inside_integration_boundary():
    root = Path(__file__).resolve().parents[1]
    for name in ('salesforce_sandbox/web.py', 'salesforce_sandbox/service.py'):
        text = (root / name).read_text()
        assert 'SELECT ' not in text and 'subprocess' not in text
    script = (root / 'static/salesforce_explorer/explorer.js').read_text()
    assert 'innerHTML' not in script
    assert 'localStorage' not in script and 'indexedDB' not in script
    # Exploring data must never become a second writer or MOD source pipeline.
    assert '/mod-sheet' not in script and '/api/field/' not in script
