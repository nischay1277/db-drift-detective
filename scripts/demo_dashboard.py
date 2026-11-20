"""Exercise the running HTTP API and leave useful demonstrations in history."""
import io
import json
from pathlib import Path
import sys
import time
from urllib import request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from driftlab.generate import generate

BASE = 'http://127.0.0.1:8766'


def call(path, body=None, post=False):
    data = json.dumps(body).encode() if body is not None else (b'' if post else None)
    message = request.Request(BASE + path, data=data, headers={'Content-Type': 'application/json'})
    with request.urlopen(message, timeout=10) as response:
        return json.load(response)


def wait(identifier):
    deadline = time.perf_counter() + 90
    while time.perf_counter() < deadline:
        item = call('/api/jobs/' + identifier)
        if item['status'] not in ('queued', 'running', 'cancelling'):
            return item
        time.sleep(.1)
    raise RuntimeError('Dashboard job did not finish')


def main():
    assert call('/api/health')['postgres_configured']
    records = []
    for family, fixed, expected in [('flexible_typing', False, 'drift'), ('foreign_keys', False, 'drift'),
                                    ('null_order', True, 'compatible'), ('null_order', False, 'drift')]:
        case = generate(family, 500 if family == 'null_order' and not fixed else 20, fixed=fixed)
        item = wait(call('/api/jobs', {'case': case})['id'])
        assert item['status'] == expected, item.get('error', item['status'])
        records.append({'job_id': item['id'], 'case': item['case']['name'], 'status': item['status'],
                        'seed_rows': len(case['rows']), 'findings': len(item['result']['findings'])})
    reduction = wait(call('/api/jobs/' + item['id'] + '/reduce', post=True)['id'])
    assert reduction['status'] == 'reduced', reduction.get('error', reduction['status'])
    result = reduction['result']
    assert (result['remaining_rows'], result['remaining_operations']) == (2, 1)
    assert result['one_minimal_verified']
    with request.urlopen(BASE + '/api/jobs/' + reduction['id'] + '/bundle', timeout=10) as response:
        with zipfile.ZipFile(io.BytesIO(response.read())) as bundle:
            assert 'test_regression.py' in bundle.namelist()
            assert len(json.loads(bundle.read('case.json'))['rows']) == 2
    records.append({'job_id': reduction['id'], 'status': 'reduced', 'original_rows': result['original_rows'],
        'remaining_rows': result['remaining_rows'], 'remaining_operations': result['remaining_operations'],
        'evaluations': len(result['evaluations']), 'one_minimal_verified': result['one_minimal_verified']})
    (ROOT / 'DEMO_RESULTS.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(json.dumps(records, indent=2))


if __name__ == '__main__':
    main()
