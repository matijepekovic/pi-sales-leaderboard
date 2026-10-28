"""Select MOD uses previously verified Salesforce Home Branch and Sales Manager role."""
import json
from types import SimpleNamespace

import pytest

from printer_app.mod_resulting.salesforce_adapter import (
    ResultingSalesforceAdapter, ResultingSalesforceError,
)


USERS = [
    {'Id': '005000000000001AAA', 'Name': 'Olympia Manager',
     'Home_Branch__c': 'Olympia', 'UserRole': {'Name': 'Sales Manager'},
     'IsActive': True},
    {'Id': '005000000000002AAA', 'Name': 'Seattle Manager',
     'Home_Branch__c': 'Seattle', 'UserRole': {'Name': 'Sales Manager'},
     'IsActive': True},
    {'Id': '005000000000003AAA', 'Name': 'Olympia Rep',
     'Home_Branch__c': 'Olympia', 'UserRole': {'Name': 'Sales Rep'},
     'IsActive': True},
    {'Id': '005000000000004AAA', 'Name': 'Olympia SMIT',
     'Home_Branch__c': 'Olympia', 'UserRole': {'Name': 'SMIT'},
     'IsActive': True},
    {'Id': '005000000000005AAA', 'Name': 'Inactive Olympia Manager',
     'Home_Branch__c': 'Olympia', 'UserRole': {'Name': 'Sales Manager'},
     'IsActive': False},
]


def _adapter():
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        assert command[1:3] == ['data', 'query']  # No User describe or writes.
        soql = command[command.index('--query') + 1]
        assert 'SELECT Id,Name,IsActive,Home_Branch__c,UserRole.Name FROM User' in soql
        assert 'WHERE IsActive = true' in soql
        assert "UserRole.Name = 'Sales Manager'" in soql
        assert 'Home_Branch__c = ' in soql
        assert 'ORDER BY Name LIMIT 2000' in soql
        # Model Salesforce's server-side WHERE filtering.
        branch_value = soql.split('Home_Branch__c = ', 1)[1].split(' ORDER BY', 1)[0]
        assert branch_value.startswith("'") and branch_value.endswith("'")
        branch_value = branch_value[1:-1].replace("\\'", "'").replace("\\\\", "\\")
        result = [
            dict(user)
            for user in USERS if user['IsActive']
            and user['UserRole']['Name'] == 'Sales Manager'
            and user['Home_Branch__c'] == branch_value
        ]
        return SimpleNamespace(
            stdout=json.dumps({'status': 0, 'result': {
                'records': result, 'done': True
            }}), stderr='', returncode=0,
        )

    return ResultingSalesforceAdapter(runner=runner), commands


def test_manager_dropdown_scoped_to_imported_market_and_role():
    adapter, calls = _adapter()
    assert adapter.mod_users('Olympia') == [
        {'id': '005000000000001AAA', 'name': 'Olympia Manager'}
    ]
    assert adapter.mod_users('Seattle') == [
        {'id': '005000000000002AAA', 'name': 'Seattle Manager'}
    ]
    assert len(calls) == 2  # Market and role are filtered in the SOQL.


def test_untrusted_salesforce_results_cannot_bypass_market_or_role_gate():
    def runner(command, **kwargs):
        return SimpleNamespace(
            stdout=json.dumps({'status': 0, 'result': {
                'records': [dict(user)
                            for user in USERS], 'done': True,
            }}), stderr='', returncode=0,
        )
    adapter = ResultingSalesforceAdapter(runner=runner)
    assert adapter.mod_users('Olympia') == [
        {'id': '005000000000001AAA', 'name': 'Olympia Manager'}
    ]


@pytest.mark.parametrize('market', ['', ' ', 'Olympia\nSeattle'])
def test_unknown_import_market_never_queries_company_wide_users(market):
    adapter = ResultingSalesforceAdapter(
        runner=lambda *_args, **_kw:
        (_ for _ in ()).throw(AssertionError('No unscoped Salesforce query')))
    with pytest.raises(ResultingSalesforceError, match='market'):
        adapter.mod_users(market)


def test_market_filter_escapes_apostrophes():
    adapter, calls = _adapter()
    assert adapter.mod_users("King's Office") == []
    soql = calls[0][calls[0].index('--query') + 1]
    assert "Home_Branch__c = 'King\\'s Office'" in soql
