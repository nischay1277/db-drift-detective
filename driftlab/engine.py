"""Execute the same case on real databases and retain reproducible evidence."""
import json
from pathlib import Path
import time
import uuid

from . import ROOT
from .model import validate
from .database import Adapter
from .sql import seed
from .compare import compare, advice


def run_case(raw, output_root=None, cancel=None):
    case = validate(raw)
    base = (Path(output_root) if output_root else ROOT / 'runs' / 'comparisons').resolve()
    if base.drive.lower() != 'd:':
        raise ValueError('Experiment outputs must stay on D:')
    folder = base / uuid.uuid4().hex
    folder.mkdir(parents=True)
    (folder / 'case.json').write_text(json.dumps(case, indent=2), encoding='utf-8')
    started = time.perf_counter()
    adapters, results = [], {}
    try:
        for engine in ('sqlite', 'postgres'):
            if cancel is not None and cancel.is_set():
                raise InterruptedError('Comparison cancelled')
            adapter = Adapter(engine, case, folder)
            adapters.append(adapter)
            steps = []
            for source, operations in [('seed', [seed(row) for row in case['rows']]), ('operation', case['operations'])]:
                for op in operations:
                    if cancel is not None and cancel.is_set():
                        raise InterruptedError('Comparison cancelled')
                    steps.append(adapter.step(op, source))
            results[engine] = {'version': adapter.version, 'steps': steps, 'state': adapter.snapshot()}
        findings = compare(case, results['sqlite'], results['postgres'])
        for finding in findings:
            finding['advice'] = advice(case, finding)
        result = {'version': 1, 'status': 'drift' if findings else 'compatible', 'compatible': not findings,
                  'case': case, 'findings': findings, 'engines': results,
                  'row_count': len(case['rows']), 'operation_count': len(case['operations']),
                  'duration_seconds': round(time.perf_counter() - started, 4), 'run_dir': str(folder),
                  'postgres_schema': adapters[-1].namespace, 'postgres_schema_retained': False}
    except BaseException as error:
        (folder / 'error.json').write_text(json.dumps({'status': 'cancelled' if isinstance(error, InterruptedError) else 'error',
            'error': str(error), 'run_dir': str(folder)}, indent=2), encoding='utf-8')
        raise
    finally:
        for adapter in reversed(adapters):
            adapter.close()
    (folder / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result
