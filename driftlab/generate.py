"""Seeded, documented compatibility witnesses rather than arbitrary SQL fuzzing."""
import random
from .model import validate

FAMILIES = ('null_order', 'flexible_typing', 'foreign_keys', 'like_case', 'nul_text', 'compatible', 'openwebui_json_search')


def generate(family='null_order', count=100, seed=7, fixed=False):
    if family not in FAMILIES or type(count) is not int or not 2 <= count <= 1000 or type(seed) is not int:
        raise ValueError('Choose a supported family, 2..1000 rows, and an integer seed')
    if fixed and family not in ('null_order', 'flexible_typing', 'foreign_keys', 'compatible', 'openwebui_json_search'):
        raise ValueError('No built-in fixed variant for this family; edit the case explicitly')
    if family == 'openwebui_json_search':
        from .chat_import import fixture, preflight, as_case
        document = fixture(count)
        if fixed:
            document = preflight(document, True)['document']
        return as_case(document, name='Open WebUI historical JSON search' + (' · repaired copy' if fixed else ' · original input'))
    rng = random.Random(seed)
    table = {'name': 'records', 'columns': [
        {'name': 'id', 'type': 'INTEGER', 'primary_key': True},
        {'name': 'priority', 'type': 'INTEGER'}, {'name': 'label', 'type': 'TEXT'}]}
    rows = [{'id': 'seed_' + str(i), 'table': 'records', 'values': {
        'id': i, 'priority': rng.randint(2, 100), 'label': 'row_' + str(i)}} for i in range(1, count + 1)]
    case = {'version': 1, 'name': family.replace('_', ' ').title() + (' · explicit policy' if fixed else ''),
            'tables': [table], 'rows': rows, 'operations': [], 'sqlite': {'foreign_keys': True, 'strict': False}}
    if family == 'null_order':
        rows[0]['values']['priority'] = None
        rows[1]['values']['priority'] = 1
        order = [{'column': 'priority'}, {'column': 'id'}]
        if fixed:
            order[0]['nulls'] = 'last'
        case['operations'] = [{'id': 'first_record', 'type': 'select', 'table': 'records',
            'columns': ['id', 'priority'], 'order_by': order, 'limit': 1},
            {'id': 'noise_read', 'type': 'select', 'table': 'records', 'columns': ['label']}]
    elif family == 'flexible_typing':
        case['sqlite']['strict'] = fixed
        case['operations'] = [{'id': 'bad_integer', 'type': 'insert', 'table': 'records',
            'values': {'id': count + 1, 'priority': 'many', 'label': 'invalid input'}}]
    elif family == 'foreign_keys':
        case['sqlite']['foreign_keys'] = fixed
        parents = {'name': 'parents', 'columns': [{'name': 'id', 'type': 'INTEGER', 'primary_key': True}]}
        table['columns'].append({'name': 'parent_id', 'type': 'INTEGER',
                                  'references': {'table': 'parents', 'column': 'id'}})
        case['tables'].insert(0, parents)
        for row in rows:
            row['values']['parent_id'] = 1
        rows.insert(0, {'id': 'parent_seed', 'table': 'parents', 'values': {'id': 1}})
        if len(rows) > 1000:
            rows.pop()
        case['operations'] = [{'id': 'orphan_insert', 'type': 'insert', 'table': 'records',
            'values': {'id': count + 1, 'parent_id': 999999, 'priority': 3, 'label': 'orphan'}}]
    elif family == 'like_case':
        rows[0]['values']['label'] = 'ALPHA'
        rows[1]['values']['label'] = 'alpha'
        case['operations'] = [{'id': 'prefix_search', 'type': 'select', 'table': 'records',
            'columns': ['id', 'label'], 'where': [{'column': 'label', 'op': 'like', 'value': 'alpha%'}]}]
    elif family == 'nul_text':
        rows[0]['values']['label'] = 'left\x00right'
    else:
        case['operations'] = [{'id': 'update_label', 'type': 'update', 'table': 'records',
            'values': {'label': 'updated'}, 'where': [{'column': 'id', 'op': 'eq', 'value': 1}]},
            {'id': 'read_all', 'type': 'select', 'table': 'records', 'order_by': [{'column': 'id'}]}]
    return validate(case)
