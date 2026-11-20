"""Compare outcomes without mistaking unspecified row ordering for drift."""
import json


def canonical(value):
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


def rows_equal(left, right, ordered):
    left, right = canonical(left), canonical(right)
    if ordered:
        return left == right
    # Sorted encodings preserve duplicate multiplicity, unlike set comparison.
    return sorted(json.dumps(row, sort_keys=True) for row in left) == sorted(json.dumps(row, sort_keys=True) for row in right)


def compare(case, left, right):
    if len(left['steps']) != len(right['steps']):
        raise RuntimeError('Engine step counts differ; the comparison is incomplete')
    findings = []
    operation_map = {op['id']: op for op in case['operations']}
    for a, b in zip(left['steps'], right['steps']):
        kind = None
        if a['accepted'] != b['accepted']:
            kind = 'acceptance'
        elif not a['accepted'] and a['error']['category'] != b['error']['category']:
            kind = 'error_category'
        elif a['accepted']:
            if a['type'] == 'select':
                ordered = operation_map[a['id']]['comparison'] == 'ordered'
                if not rows_equal(a['rows'], b['rows'], ordered):
                    kind = 'rows'
            elif a['affected_rows'] != b['affected_rows']:
                kind = 'affected_rows'
        if kind:
            signature = {'source': a['source'], 'step_id': a['id'], 'kind': kind}
            findings.append({'signature': signature, 'table': a['table'], 'sqlite': a, 'postgres': b})
    for table in case['tables']:
        name = table['name']
        a, b = left['state'][name], right['state'][name]
        if not rows_equal(a['rows'], b['rows'], False):
            findings.append({'signature': {'source': 'final_state', 'step_id': name, 'kind': 'state'},
                             'table': name, 'sqlite': a, 'postgres': b})
    return findings


def advice(case, finding):
    signature = finding['signature']
    if signature['kind'] == 'acceptance' and finding['postgres'].get('error', {}).get('category') == 'encoding':
        return 'JSON can be accepted at import yet fail during PostgreSQL text extraction. Preflight decoded strings for actual NUL code points; preserve originals and repair only an explicit copy.'
    if signature['kind'] == 'rows':
        op = next((op for op in case['operations'] if op['id'] == signature['step_id']), {})
        if op.get('order_by') and any('nulls' not in term for term in op['order_by']):
            return 'Make NULL placement explicit in order_by; keep the primary-key tie breaker.'
        if any(term['op'] == 'like' for term in op.get('where', [])):
            return 'Define a case-sensitivity policy explicitly. SQLite LIKE folds ASCII case by default; PostgreSQL LIKE does not.'
    if signature['kind'] == 'acceptance':
        error = finding['postgres'].get('error', {}).get('category')
        if error == 'datatype':
            return 'Validate input types, or evaluate SQLite STRICT tables during development.'
        if error == 'foreign_key':
            return 'Enable SQLite foreign_keys for every connection and validate referenced records.'
        if error == 'encoding':
            return 'Reject or deliberately normalize embedded NUL characters before storing text.'
    return 'Inspect the paired outcomes and declare the intended behavior before changing the application.'
