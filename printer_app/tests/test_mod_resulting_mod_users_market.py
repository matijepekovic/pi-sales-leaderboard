"""Select MOD is market-specific sales manager choice, never every Salesforce User."""
import json
from types import SimpleNamespace

import pytest

from printer_app.mod_resulting.salesforce_adapter import (
    ResultingSalesforceAdapter, ResultingSalesforceError,
)


def test_market_selected_from_daily_mod_import_restricts_users_to_sales_managers():
    commands = []
    rows = [
        {'Id':'005000000000001AAA','Name':'Olympia Manager',
         'Title':'Sales Manager','Department':'Olympia','Division':'West',
         'UserRole':{'Name':'Sales Manager'}, 'Profile':{'Name':'Employee'},
         'Market__c':'Olympia'},
        {'Id':'005000000000002AAA','Name':'Seattle Manager',
         'Title':'Sales Manager','Department':'Seattle','Division':'West',
         'UserRole':{'Name':'Sales Manager'}, 'Profile':{'Name':'Employee'},
         'Market__c':'Seattle'},
        {'Id':'005000000000003AAA','Name':'Olympia Rep',
         'Title':'Sales Representative','Department':'Olympia','Division':'West',
         'UserRole':{'Name':'Sales Rep'}, 'Profile':{'Name':'Employee'},
         'Market__c':'Olympia'},
        {'Id':'005000000000004AAA','Name':'Role-Located Olympia Manager',
         'Title':'','Department':'','Division':'',
         'UserRole':{'Name':'Sales Manager - Olympia'},
         'Profile':{'Name':'Employee'},'Market__c':''},
    ]
    def runner(command, **kwargs):
        commands.append(command)
        if command[1:3] == ['sobject','describe']:
            result = {'name':'User','fields':[
                {'name':'Market__c','type':'string'}]}
        else:
            assert command[1:3] == ['data','query']
            query = command[command.index('--query')+1]
            assert 'WHERE IsActive = true' in query
            assert 'FROM User ' in query and 'UserRole.Name' in query
            result = {'records':rows,'done':True}
        return SimpleNamespace(
            stdout=json.dumps({'status':0,'result':result}),stderr='',returncode=0)
    adapter = ResultingSalesforceAdapter(runner=runner)
    assert adapter.mod_users('Olympia') == [
        {'id':'005000000000001AAA','name':'Olympia Manager'},
        {'id':'005000000000004AAA','name':'Role-Located Olympia Manager'},
    ]
    assert adapter.mod_users('Seattle') == [
        {'id':'005000000000002AAA','name':'Seattle Manager'}]
    assert len(commands) == 3  # one describe, two read-only market lookups


@pytest.mark.parametrize('market',['', ' ', 'Olympia\nSeattle'])
def test_unknown_market_never_falls_back_to_company_wide_mod_users(market):
    adapter = ResultingSalesforceAdapter(runner=lambda *_args, **_kw:
                                         (_ for _ in ()).throw(AssertionError(
                                             'No Salesforce query without a market')))
    with pytest.raises(ResultingSalesforceError,match='Select a market'):
        adapter.mod_users(market)
