"""Portable case evidence plus executable reproduction and compatibility test."""
import json
from pathlib import Path
import zipfile
from . import ROOT
from .sql import schema, operation, seed


def export_bundle(report, destination=None):
    reduced = report.get('status') == 'reduced'
    case = report['reduced'] if reduced else report['case']
    evidence = report['final_report'] if reduced else report
    if reduced:
        target = report['target_signature']
    else:
        target = evidence['findings'][0]['signature'] if evidence['findings'] else None
    folder = Path(destination) if destination else Path(report['run_dir']) / 'export'
    folder = folder.resolve()
    if folder.drive.lower() != 'd:':
        raise ValueError('Export output must stay on D:')
    folder.mkdir(parents=True, exist_ok=True)
    files = {'case.json': json.dumps(case, indent=2),
             'expected.json': json.dumps({'target_signature': target, 'compatible': evidence['compatible']}, indent=2),
             'report.json': json.dumps(evidence, indent=2)}
    for engine in ('sqlite', 'postgres'):
        lines = ['-- Parameterized statements: execute through the matching Python driver.',
                 '-- Bindings are in ' + engine + '-bindings.json; this file is not a psql script.']
        bindings = []
        if engine == 'sqlite':
            lines.append('PRAGMA foreign_keys=' + ('ON;' if case['sqlite']['foreign_keys'] else 'OFF;'))
        lines.extend(statement + ';' for statement in schema(case, engine))
        for op in [seed(row) for row in case['rows']] + case['operations']:
            statement, params = operation(op, engine)
            lines += ['-- ' + op['id'], statement + ';']
            bindings.append({'step_id': op['id'], 'parameters': params})
        files[engine + '.sql'] = '\n'.join(lines) + '\n'
        files[engine + '-bindings.json'] = json.dumps(bindings, indent=2)
    bootstrap = """import json, os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, os.environ.get('DRIFTLAB_ROOT', DEFAULT_ROOT))
from driftlab.engine import run_case
""".replace('DEFAULT_ROOT', repr(str(ROOT)))
    files['reproduce.py'] = bootstrap + """
case = json.loads((HERE / 'case.json').read_text(encoding='utf-8'))
expected = json.loads((HERE / 'expected.json').read_text())
report = run_case(case)
target = expected['target_signature']
matches = report['compatible'] if target is None else any(f['signature'] == target for f in report['findings'])
print('Expected behavior reproduced:', matches)
raise SystemExit(0 if matches else 1)
"""
    files['test_regression.py'] = bootstrap + """
import unittest

class MigrationCompatibilityTest(unittest.TestCase):
    def test_application_behavior_matches(self):
        case = json.loads((HERE / 'case.json').read_text(encoding='utf-8'))
        report = run_case(case)
        signatures = [f['signature'] for f in report['findings']]
        self.assertTrue(report['compatible'], 'Migration drift: ' + json.dumps(signatures))

if __name__ == '__main__':
    unittest.main()
"""
    files['README.md'] = '''# Reproduction bundle

Requires DB Drift Detective and its configured PostgreSQL test database.
Set DRIFTLAB_ROOT if the source checkout moved; keep output paths on D:.

`python -B reproduce.py` exits 0 if the saved finding is reproduced.
`python -B test_regression.py` requires compatibility and therefore intentionally
fails for a known drift case until its schema/configuration/operation is corrected.

The SQL files are driver templates, not directly runnable psql scripts. Bindings
are separate JSON to preserve exact values including embedded NUL characters.
Schema is fixed during reduction; minimality concerns row and operation deletion.
The private PostgreSQL credentials are not exported. Input data IS exported:
review case.json and report.json before sharing the bundle.
'''
    for name, content in files.items():
        (folder / name).write_text(content, encoding='utf-8')
    archive = folder.parent / 'reproduction.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in files:
            bundle.write(folder / name, name)
    return str(archive)
