"""Reproduce a sourced historical failure and validate a non-destructive remedy."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from driftlab.chat_import import as_case, fixture, run_preflight, ISSUE, SOURCE
from driftlab.engine import run_case
from driftlab.export import export_bundle
from driftlab.reduce import minimize


def main():
    folder = ROOT / 'case_studies' / 'openwebui_nul' / 'evidence' / uuid.uuid4().hex
    folder.mkdir(parents=True)
    original = folder / 'sample-export.json'
    original.write_text(json.dumps(fixture(100), indent=2), encoding='utf-8')
    before = run_case(as_case(fixture(100)), folder / 'comparisons')
    assert all(step['accepted'] for engine in before['engines'].values()
               for step in engine['steps'] if step['source'] == 'seed')
    assert before['engines']['postgres']['steps'][-1]['error']['code'] == '22P05'
    assert before['engines']['sqlite']['steps'][-1]['accepted']
    reduction = minimize(before['case'], folder / 'reductions')
    assert (reduction['remaining_rows'], reduction['remaining_operations']) == (1, 1)
    assert reduction['one_minimal_verified']
    audit = run_preflight(original, repair=True, verify=True, output_root=folder / 'preflight')
    after_path = Path(audit['verification']['after_report'])
    after = json.loads(after_path.read_text())
    assert after['compatible']
    assert len(after['engines']['postgres']['steps'][-1]['rows']) == 1
    assert len(after['engines']['sqlite']['steps'][-1]['rows']) == 1
    minimal_bundle = Path(export_bundle(reduction))
    fixed_bundle = Path(export_bundle(after))
    commands = []
    for label, script, expected in [
        ('minimal_reproduction', minimal_bundle.parent / 'export' / 'reproduce.py', 0),
        ('unfixed_compatibility_test', minimal_bundle.parent / 'export' / 'test_regression.py', 1),
        ('fixed_compatibility_test', fixed_bundle.parent / 'export' / 'test_regression.py', 0)]:
        completed = subprocess.run([sys.executable, '-B', str(script)], capture_output=True, text=True)
        assert completed.returncode == expected, completed.stderr
        commands.append({'check': label, 'exit_code': completed.returncode, 'expected_exit_code': expected})
    result = {'issue_url': ISSUE, 'source_version': 'v0.6.15', 'source_model_url': SOURCE,
              'scope': 'Database-level reproduction with synthetic chats; full Open WebUI application not run; no upstream fix claimed',
              'imported_chats': 100, 'all_imports_accepted_on_both_engines': True,
              'before_postgres_search_error': '22P05', 'before_sqlite_matching_chats': 1,
              'minimal_chats': 1, 'minimal_operations': 1, 'one_minimal_verified': True,
              'repair_policy': 'Decoded NUL -> explicit [NUL] marker in a separate copy',
              'after_both_searches_succeed': True, 'after_matching_chats': 1,
              'before_report': str(Path(before['run_dir']) / 'report.json'),
              'reduction_report': str(Path(reduction['run_dir']) / 'reduction.json'),
              'audit_report': str(Path(audit['run_dir']) / 'audit.json'),
              'after_report': str(after_path), 'reproduction_bundle': str(minimal_bundle),
              'fixed_bundle': str(fixed_bundle), 'regression_checks': commands}
    (folder / 'study.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (ROOT / 'case_studies' / 'openwebui_nul' / 'latest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
