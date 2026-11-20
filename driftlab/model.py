"""A deliberately bounded schema/operation DSL, never arbitrary SQL."""
import copy
import json
import math
from pathlib import Path
import re

NAME = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
TYPES = ('INTEGER', 'TEXT', 'REAL', 'JSON')
OPS = ('eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'is_null', 'not_null', 'like', 'json_array_text_contains')


def fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError('Unexpected or missing fields; allowed: ' + ', '.join(allowed))


def identifier(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError('Identifiers must be lowercase letters, digits and underscores, max 32 characters')
    return value


def scalar(value):
    if value is None or type(value) is bool:
        return
    if type(value) is int and -(2**63) <= value < 2**63:
        return
    if type(value) is float and math.isfinite(value) and abs(value) <= 1e15:
        return
    if isinstance(value, str) and len(value) <= 2000:
        return
    raise ValueError('Values must be bounded JSON scalars')


def validate(raw):
    fields(raw, ('version', 'name', 'sqlite', 'tables', 'rows', 'operations'), ('version', 'tables', 'operations'))
    case = copy.deepcopy(raw)
    if type(case['version']) is not int or case['version'] != 1:
        raise ValueError('version must be integer 1')
    name = case.setdefault('name', 'Untitled comparison')
    if not isinstance(name, str) or not 1 <= len(name) <= 120:
        raise ValueError('name must contain 1..120 characters')
    options = case.setdefault('sqlite', {})
    fields(options, ('foreign_keys', 'strict'))
    for key, default in [('foreign_keys', True), ('strict', False)]:
        if type(options.setdefault(key, default)) is not bool:
            raise ValueError('SQLite flags must be booleans')
    tables = case['tables']
    if not isinstance(tables, list) or not 1 <= len(tables) <= 4:
        raise ValueError('Provide 1..4 tables')
    registry = {}
    for table in tables:
        fields(table, ('name', 'columns'), ('name', 'columns'))
        key = identifier(table['name'])
        if key in registry:
            raise ValueError('Duplicate table name')
        if not isinstance(table['columns'], list) or not 1 <= len(table['columns']) <= 10:
            raise ValueError('Provide 1..10 columns per table')
        columns = {}
        for column in table['columns']:
            fields(column, ('name', 'type', 'nullable', 'primary_key', 'unique', 'references'), ('name', 'type'))
            column_name = identifier(column['name'])
            if column_name in columns or column['type'] not in TYPES:
                raise ValueError('Duplicate column or unsupported type')
            for flag, default in [('primary_key', False), ('nullable', True), ('unique', False)]:
                if type(column.setdefault(flag, default)) is not bool:
                    raise ValueError('Column flags must be booleans')
            if column['primary_key']:
                column['nullable'] = False
            if column['type'] == 'JSON' and (column['primary_key'] or column['unique']):
                raise ValueError('JSON columns cannot be primary or unique keys in this bounded DSL')
            ref = column.get('references')
            if ref is not None:
                fields(ref, ('table', 'column'), ('table', 'column'))
                if ref['table'] not in registry:
                    raise ValueError('Referenced tables must precede dependent tables')
                target = registry[ref['table']]['columns'].get(ref['column'])
                if not target or not (target['primary_key'] or target['unique']) or target['type'] != column['type']:
                    raise ValueError('Reference must target a compatible primary/unique column')
            columns[column_name] = column
        primary = [c['name'] for c in table['columns'] if c['primary_key']]
        if len(primary) != 1:
            raise ValueError('Each table needs exactly one primary key for deterministic comparison')
        registry[key] = {'columns': columns, 'pk': primary[0]}

    def values(table, data):
        if not isinstance(data, dict) or not data or set(data) - set(registry[table]['columns']):
            raise ValueError('Values must name existing columns')
        for key, value in data.items():
            if registry[table]['columns'][key]['type'] == 'JSON' and isinstance(value, str) and len(value) <= 65536:
                pass
            else:
                scalar(value)
            if registry[table]['columns'][key]['type'] == 'JSON' and value is not None:
                if not isinstance(value, str):
                    raise ValueError('JSON column values must be serialized JSON strings')
                try:
                    json.loads(value, parse_constant=lambda v: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
                except (ValueError, RecursionError):
                    raise ValueError('Invalid JSON column value') from None

    def conditions(table, where):
        if not isinstance(where, list) or len(where) > 8:
            raise ValueError('where must contain at most 8 conditions')
        for condition in where:
            fields(condition, ('column', 'op', 'value', 'path', 'field'), ('column', 'op'))
            if condition['column'] not in registry[table]['columns'] or condition['op'] not in OPS:
                raise ValueError('Unsupported condition')
            if condition['op'] == 'json_array_text_contains':
                if registry[table]['columns'][condition['column']]['type'] != 'JSON':
                    raise ValueError('JSON search requires a JSON column')
                path = condition.get('path')
                if not isinstance(path, list) or not 1 <= len(path) <= 3:
                    raise ValueError('JSON path must contain 1..3 identifier keys')
                for key in path:
                    identifier(key)
                identifier(condition.get('field'))
                if not isinstance(condition.get('value'), str) or not condition['value'].isascii() or not condition['value']:
                    raise ValueError('JSON text search currently needs a nonempty ASCII search term')
            elif 'path' in condition or 'field' in condition:
                raise ValueError('Only JSON array searches take path/field')
            if condition['op'] in ('is_null', 'not_null'):
                if 'value' in condition:
                    raise ValueError('Null predicates do not take a value')
            else:
                if 'value' not in condition:
                    raise ValueError('Condition needs a value')
                scalar(condition['value'])
                if condition['value'] is None:
                    raise ValueError('Use is_null/not_null for null predicates')

    seen = set()
    rows = case.setdefault('rows', [])
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError('At most 1000 seed rows')
    for row in rows:
        fields(row, ('id', 'table', 'values'), ('id', 'table', 'values'))
        identifier(row['id'])
        if row['id'] in seen or row['table'] not in registry:
            raise ValueError('Duplicate step ID or unknown table')
        seen.add(row['id'])
        values(row['table'], row['values'])
    operations = case['operations']
    if not isinstance(operations, list) or len(operations) > 40:
        raise ValueError('At most 40 operations')
    for op in operations:
        fields(op, ('id', 'type', 'table', 'values', 'columns', 'where', 'order_by', 'limit', 'comparison'), ('id', 'type', 'table'))
        identifier(op['id'])
        table = op['table']
        if op['id'] in seen or table not in registry or op['type'] not in ('select', 'insert', 'update', 'delete'):
            raise ValueError('Duplicate step ID, unknown table, or unsupported operation')
        seen.add(op['id'])
        if op['type'] in ('insert', 'update'):
            values(table, op.get('values'))
        elif 'values' in op:
            raise ValueError('Only insert/update take values')
        if op['type'] != 'insert':
            conditions(table, op.setdefault('where', []))
        elif 'where' in op:
            raise ValueError('Insert does not take where')
        if op['type'] == 'select':
            selected = op.setdefault('columns', list(registry[table]['columns']))
            if not isinstance(selected, list) or not selected or any(c not in registry[table]['columns'] for c in selected) or len(selected) != len(set(selected)):
                raise ValueError('Select columns must be distinct known columns')
            ordering = op.setdefault('order_by', [])
            if not isinstance(ordering, list) or len(ordering) > 10:
                raise ValueError('Invalid order_by')
            for term in ordering:
                fields(term, ('column', 'direction', 'nulls'), ('column',))
                if term['column'] not in registry[table]['columns'] or term.setdefault('direction', 'asc') not in ('asc', 'desc'):
                    raise ValueError('Invalid order column/direction')
                if 'nulls' in term and term['nulls'] not in ('first', 'last'):
                    raise ValueError('nulls must be first or last')
            total_order = registry[table]['pk'] in [t['column'] for t in ordering]
            if op.setdefault('comparison', 'ordered' if total_order else 'bag') not in ('ordered', 'bag'):
                raise ValueError('comparison must be ordered or bag')
            if op['comparison'] == 'ordered' and not total_order:
                raise ValueError('Ordered comparison needs the primary key in order_by to avoid ambiguous ties')
            if 'limit' in op and (type(op['limit']) is not int or not 1 <= op['limit'] <= 1000 or not total_order):
                raise ValueError('limit requires 1..1000 and a deterministic primary-key tie breaker')
        elif any(k in op for k in ('columns', 'order_by', 'limit', 'comparison')):
            raise ValueError('Only selects take projection/order/limit/comparison')
    return case


def load(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8')))
