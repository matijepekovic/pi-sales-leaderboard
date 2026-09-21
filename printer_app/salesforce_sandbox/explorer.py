"""Salesforce metadata and safe query policy for the read-only object explorer.

This module has no transport or application state. Queries can use only names,
fields, and operators admitted by a described Salesforce object.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import re


PAGE_SIZE = 50
MAX_COLUMNS = 20
MAX_FILTERS = 10
_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,254}', re.ASCII)
_RECORD_ID = re.compile(r'[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?', re.ASCII)
_NUMERIC_TYPES = frozenset({'int', 'long', 'double', 'currency', 'percent'})
_TEXT_TYPES = frozenset({'string', 'textarea', 'email', 'phone', 'url'})
_EMPTY = ('is_empty', 'not_empty')


def identifier(value, label='Object'):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f'{label} name is invalid.')
    return value


def record_id(value):
    if not isinstance(value, str) or not _RECORD_ID.fullmatch(value):
        raise ValueError('Record ID must contain 15 or 18 letters and numbers.')
    return value


def operators(field_type, filterable):
    if not filterable:
        return []
    if field_type in _TEXT_TYPES:
        return ['eq', 'ne', 'contains', 'starts_with', *_EMPTY]
    if field_type in _NUMERIC_TYPES or field_type in ('date', 'datetime'):
        return ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'between', *_EMPTY]
    if field_type in ('id', 'reference', 'boolean', 'picklist', 'encryptedstring'):
        return ['eq', 'ne', *_EMPTY]
    if field_type == 'multipicklist':
        return ['includes', 'excludes', *_EMPTY]
    return []


def describe_metadata(raw, requested_name):
    """Normalize a describe response; never fetch referenced object schemas."""
    if not isinstance(raw, dict) or not isinstance(raw.get('fields'), list):
        raise ValueError('Salesforce returned invalid object metadata.')
    name = identifier(raw.get('name'))
    if name.casefold() != requested_name.casefold():
        raise ValueError('Salesforce returned metadata for a different object.')
    fields = []
    seen = set()
    for source in raw['fields']:
        if not isinstance(source, dict):
            raise ValueError('Salesforce returned invalid field metadata.')
        if source.get('deprecatedAndHidden'):
            continue
        field_name = identifier(source.get('name'), 'Field')
        if field_name in seen:
            raise ValueError('Salesforce returned duplicate field metadata.')
        seen.add(field_name)
        field_type = str(source.get('type') or '').lower()
        filterable = source.get('filterable') is True
        references = source.get('referenceTo') or []
        if not isinstance(references, list):
            raise ValueError('Salesforce returned invalid reference metadata.')
        values = source.get('picklistValues') or []
        if not isinstance(values, list):
            raise ValueError('Salesforce returned invalid picklist metadata.')
        fields.append({
            'name': field_name,
            'label': str(source.get('label') or field_name),
            'type': field_type,
            'filterable': filterable,
            'sortable': source.get('sortable') is True,
            'reference_to': [identifier(target) for target in references],
            'picklist_values': [
                {'label': str(value.get('label') or value['value']), 'value': str(value['value'])}
                for value in values if isinstance(value, dict) and value.get('value') is not None
            ],
            'operators': operators(field_type, filterable),
        })
    relationships = []
    for source in raw.get('childRelationships') or []:
        if not isinstance(source, dict) or not source.get('relationshipName'):
            continue
        if source.get('deprecatedAndHidden'):
            continue
        relationship = identifier(source['relationshipName'], 'Relationship')
        relationships.append({
            'name': relationship,
            'label': relationship,
            'object': identifier(source.get('childSObject')),
            'field': identifier(source.get('field'), 'Field'),
        })
    # A short useful starting view; every other described field remains selectable.
    defaults = ['Id'] if 'Id' in seen else []
    for source in raw['fields']:
        field_name = source.get('name')
        if field_name in seen and (source.get('nameField') or source.get('autoNumber')):
            if field_name not in defaults:
                defaults.append(field_name)
    for field_name in ('Name', 'Subject', 'Status', 'CreatedDate', 'LastModifiedDate'):
        if field_name in seen and field_name not in defaults:
            defaults.append(field_name)
    return {
        'object': {
            'name': name, 'label': str(raw.get('label') or name),
            'queryable': raw.get('queryable') is True,
        },
        'fields': fields,
        'relationships': relationships,
        'default_columns': defaults[:5],
    }


def quoted(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError('Text filter values must contain at most 2,000 characters.')
    if any(ord(char) < 32 and char not in '\n\r\t\b\f' for char in value):
        raise ValueError('Text filter contains an unsupported control character.')
    escaped = value.replace('\\', '\\\\').replace("'", "\\'")
    for char, replacement in (('\n', '\\n'), ('\r', '\\r'), ('\t', '\\t'), ('\b', '\\b'), ('\f', '\\f')):
        escaped = escaped.replace(char, replacement)
    return "'" + escaped + "'"


def literal(field, value):
    kind = field['type']
    if kind == 'boolean':
        if type(value) is not bool:
            raise ValueError('Boolean filters must be true or false.')
        return 'true' if value else 'false'
    if kind in _NUMERIC_TYPES:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError('Enter a valid number for this filter.')
        text = str(value).strip()
        if len(text) > 128 or not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?', text, re.ASCII):
            raise ValueError('Enter a valid number for this filter.')
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError('Enter a valid number for this filter.') from exc
        if not number.is_finite() or abs(number.adjusted()) > 100:
            raise ValueError('The filter number is outside the supported range.')
        if kind in ('int', 'long') and number != number.to_integral_value():
            raise ValueError('Enter a whole number for this filter.')
        return format(number, 'f')
    if kind == 'date':
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value, re.ASCII):
            raise ValueError('Use YYYY-MM-DD for date filters.')
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise ValueError('Enter a valid calendar date.') from exc
    if kind == 'datetime':
        if not isinstance(value, str) or not re.fullmatch(
                r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value, re.ASCII):
            raise ValueError('Date and time filters must include a timezone.')
        try:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
        except ValueError as exc:
            raise ValueError('Enter a valid date and time.') from exc
        if stamp.microsecond:
            raise ValueError('Date and time filters support whole seconds.')
        return stamp.isoformat(timespec='seconds').replace('+00:00', 'Z')
    if kind in ('id', 'reference'):
        record_id(value)
    return quoted(value)


def condition(field, operator, value=None, value2=None):
    if operator not in field['operators']:
        raise ValueError(f'That operator is not supported for {field["label"]}.')
    name = field['name']
    if operator in _EMPTY:
        return f'{name} {"=" if operator == "is_empty" else "!="} null'
    if operator in ('contains', 'starts_with'):
        if not isinstance(value, str):
            raise ValueError('Enter text for this filter.')
        # SOQL uses a single backslash for LIKE wildcards. Escape input string
        # characters first so these operator escapes are not doubled afterward.
        pattern = quoted(value)[1:-1].replace('%', '\\%').replace('_', '\\_')
        pattern = ('%' if operator == 'contains' else '') + pattern + '%'
        return f"{name} LIKE '{pattern}'"
    if operator in ('includes', 'excludes'):
        if not isinstance(value, str) or ';' in value:
            raise ValueError('Choose one picklist value for this filter.')
        return f'{name} {operator.upper()} ({quoted(value)})'
    first = literal(field, value)
    if operator == 'between':
        second = literal(field, value2)
        return f'({name} >= {first} AND {name} <= {second})'
    symbol = {'eq': '=', 'ne': '!=', 'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<='}[operator]
    return f'{name} {symbol} {first}'


def query_for(schema, columns=None, filters=None, match='all', after=''):
    if not schema['object']['queryable']:
        raise ValueError('This object does not support record searches.')
    fields = {field['name']: field for field in schema['fields']}
    id_field = fields.get('Id')
    if not id_field or not id_field['filterable'] or not id_field['sortable']:
        raise ValueError('This object does not support safe record pagination by ID.')
    if columns is None:
        columns = schema['default_columns']
    if not isinstance(columns, list) or len(columns) > MAX_COLUMNS:
        raise ValueError(f'Choose at most {MAX_COLUMNS} columns.')
    selected = ['Id']
    for name in columns:
        if not isinstance(name, str) or name not in fields:
            raise ValueError('Choose columns from this object’s fields.')
        if name not in selected:
            selected.append(name)
    if len(selected) > MAX_COLUMNS:
        raise ValueError(f'Choose at most {MAX_COLUMNS} columns including Record ID.')
    if filters is None:
        filters = []
    if not isinstance(filters, list) or len(filters) > MAX_FILTERS:
        raise ValueError(f'Use at most {MAX_FILTERS} filters.')
    if match not in ('all', 'any'):
        raise ValueError('Filter matching must be all or any.')
    conditions = []
    for value in filters:
        if not isinstance(value, dict) or not isinstance(value.get('field'), str) or value['field'] not in fields:
            raise ValueError('Choose filters from this object’s fields.')
        conditions.append(condition(fields[value['field']], value.get('operator'), value.get('value'), value.get('value2')))
    where = []
    if conditions:
        where.append('(' + (' AND ' if match == 'all' else ' OR ').join(conditions) + ')')
    if after:
        where.append(f'Id > {quoted(record_id(after))}')
    query = 'SELECT ' + ', '.join(selected) + ' FROM ' + schema['object']['name']
    if where:
        query += ' WHERE ' + ' AND '.join(where)
    query += f' ORDER BY Id ASC LIMIT {PAGE_SIZE + 1}'
    return query, [fields[name] for name in selected]
