"""Chunk deletion followed by explicit one-deletion checks, with fixed schema."""
import copy
import json
from pathlib import Path
import time
import uuid

from . import ROOT
from .engine import run_case
from .model import validate


def minimize(raw, output_root=None, cancel=None, max_evaluations=180):
    case = validate(raw)
    base = (Path(output_root) if output_root else ROOT / 'runs' / 'reductions').resolve()
    if base.drive.lower() != 'd:':
        raise ValueError('Reduction outputs must stay on D:')
    folder = base / uuid.uuid4().hex
    folder.mkdir(parents=True)
    started = time.perf_counter()
    evaluations = []
    target = None

    def probe(candidate):
        if cancel is not None and cancel.is_set():
            raise InterruptedError('Reduction cancelled')
        if len(evaluations) >= max_evaluations:
            raise RuntimeError('Reduction evaluation budget exhausted')
        entry = {'rows': len(candidate['rows']), 'operations': len(candidate['operations'])}
        evaluations.append(entry)
        try:
            result = run_case(candidate, folder / 'trials', cancel)
            entry['report'] = str(Path(result['run_dir']) / 'report.json')
            entry['reproduces'] = bool(result['findings']) if target is None else any(
                finding['signature'] == target for finding in result['findings'])
            return entry, result
        except InterruptedError:
            raise
        except (ValueError, RuntimeError, OSError) as error:
            entry.update(reproduces=False, inconclusive=True, error=str(error))
            return entry, None

    try:
        baseline, first = probe(case)
        if not baseline['reproduces']:
            raise ValueError('Reduction needs a case with a reproducible finding')
        target = first['findings'][0]['signature']
        current = copy.deepcopy(case)
        # Chunk reduction handles hundreds of noise rows without testing each first.
        for field in ('rows', 'operations'):
            granularity = 2
            while current[field]:
                size = max(1, (len(current[field]) + granularity - 1) // granularity)
                changed = False
                for start in range(0, len(current[field]), size):
                    candidate = copy.deepcopy(current)
                    del candidate[field][start:start + size]
                    if probe(candidate)[0]['reproduces']:
                        current, changed = candidate, True
                        granularity = max(2, granularity - 1)
                        break
                if changed:
                    continue
                if size == 1:
                    break
                granularity = min(len(current[field]), granularity * 2)
        # Revisit across both dimensions until no one-deletion removal succeeds.
        while True:
            proof, changed = [], False
            for field in ('rows', 'operations'):
                for index, item in enumerate(current[field]):
                    candidate = copy.deepcopy(current)
                    del candidate[field][index]
                    entry, _ = probe(candidate)
                    proof.append({'field': field, 'id': item['id'],
                                  'reproduces': entry['reproduces'],
                                  'inconclusive': entry.get('inconclusive', False)})
                    if entry['reproduces']:
                        current, changed = candidate, True
                        break
                if changed:
                    break
            if not changed:
                break
        # Independent final repetition checks signature stability after reduction.
        final1, final_report = probe(current)
        final2, _ = probe(current)
        verified = all(not p['reproduces'] and not p['inconclusive'] for p in proof)
        verified = verified and final1['reproduces'] and final2['reproduces']
        result = {'version': 1, 'status': 'reduced', 'original': case, 'reduced': current,
                  'target_signature': target, 'original_rows': len(case['rows']),
                  'remaining_rows': len(current['rows']), 'original_operations': len(case['operations']),
                  'remaining_operations': len(current['operations']), 'one_minimal_verified': bool(verified),
                  'proof': proof, 'evaluations': evaluations, 'final_report': final_report,
                  'duration_seconds': round(time.perf_counter() - started, 4), 'run_dir': str(folder)}
        for name, value in [('original.json', case), ('minimal.json', current), ('reduction.json', result)]:
            (folder / name).write_text(json.dumps(value, indent=2), encoding='utf-8')
        return result
    except BaseException as error:
        (folder / 'error.json').write_text(json.dumps({'error': str(error), 'evaluations': evaluations}, indent=2), encoding='utf-8')
        raise
