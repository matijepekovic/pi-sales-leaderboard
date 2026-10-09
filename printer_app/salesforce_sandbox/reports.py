"""Salesforce report discovery adapter. No printing or scheduling responsibilities."""
from __future__ import annotations

import re

from .adapter import SalesforceAdapterError


def search_reports(cli, term):
    term = str(term or '').strip()
    if len(term) > 100 or any(ord(c) < 32 for c in term):
        raise ValueError('Search must be at most 100 printable characters.')
    # Report is a Salesforce standard object; the authenticated CLI enforces
    # visibility, including private reports owned by the connected user.
    escaped = term.replace('\\', '\\\\').replace("'", "\\'")
    escaped = escaped.replace('%', '\\%').replace('_', '\\_')
    where = (" WHERE Name LIKE '%" + escaped + "%'") if term else ''
    soql = 'SELECT Id, Name, DeveloperName, FolderName FROM Report' + where + ' ORDER BY Name LIMIT 2000'
    result = cli._run(['data', 'query', '--query', soql, *cli._target_args()], timeout=60)
    rows = result.get('records') if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise SalesforceAdapterError('Salesforce did not return a report list.')
    output = []
    for row in rows:
        if not isinstance(row, dict):
            raise SalesforceAdapterError('Invalid report record.')
        identifier = str(row.get('Id') or '')
        if not re.fullmatch(r'00O[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?', identifier):
            raise SalesforceAdapterError('Invalid Salesforce report ID.')
        output.append(dict(id=identifier, name=str(row.get('Name') or ''),
                           folder=str(row.get('FolderName') or '')))
    return tuple(output)
