import argparse
import json
from pathlib import Path
import sys
from . import ROOT
from .engine import run_case
from .generate import FAMILIES, generate
from .model import load
from .reduce import minimize
from .export import export_bundle


def show(report):
    print('{} | rows={} | operations={} | findings={}'.format(report['status'].upper(),
        report['row_count'], report['operation_count'], len(report['findings'])))
    print('Report: ' + str(Path(report['run_dir']) / 'report.json'))


def main():
    parser = argparse.ArgumentParser(description='SQLite / PostgreSQL behavioral drift detector')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('demo')
    sub.add_parser('doctor')
    run = sub.add_parser('run'); run.add_argument('case', type=Path)
    replay = sub.add_parser('replay'); replay.add_argument('report', type=Path)
    gen = sub.add_parser('generate'); gen.add_argument('--family', choices=FAMILIES, default='null_order')
    gen.add_argument('--rows', type=int, default=100); gen.add_argument('--seed', type=int, default=7)
    gen.add_argument('--fixed', action='store_true'); gen.add_argument('--output', type=Path, required=True)
    reduce = sub.add_parser('reduce'); reduce.add_argument('case', type=Path)
    export = sub.add_parser('export'); export.add_argument('report', type=Path)
    serve = sub.add_parser('serve'); serve.add_argument('--port', type=int, default=8766)
    preflight = sub.add_parser('chat-preflight')
    preflight.add_argument('input', type=Path)
    preflight.add_argument('--repair', action='store_true')
    preflight.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'doctor':
            from .database import configured, connect_postgres
            import sqlite3
            result = {'sqlite_version': sqlite3.sqlite_version, 'postgres_configured': configured(), 'root': str(ROOT)}
            if configured():
                with connect_postgres() as db:
                    result['postgres_version'] = db.execute('SHOW server_version').fetchone()[0]
                    result['database'], result['role'] = db.execute('SELECT current_database(),current_user').fetchone()
            print(json.dumps(result, indent=2)); return 0
        if args.command == 'serve':
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(), host='127.0.0.1', port=args.port); return 0
        if args.command == 'chat-preflight':
            from .chat_import import run_preflight
            audit = run_preflight(args.input, args.repair, args.verify)
            print(json.dumps(audit, indent=2, ensure_ascii=False))
            return 0 if audit['output_passes_nul_policy'] else 1
        if args.command == 'generate':
            path = args.output.resolve()
            if path.drive.lower() != 'd:':
                raise ValueError('Generated cases must stay on D:')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(generate(args.family, args.rows, args.seed, args.fixed), indent=2), encoding='utf-8')
            print('Case: ' + str(path)); return 0
        if args.command == 'demo':
            reports = [run_case(generate(family, 12)) for family in FAMILIES]
            reports.append(run_case(generate('null_order', 12, fixed=True)))
            for report in reports:
                print(report['case']['name']); show(report)
            expected = [False] * 5 + [True, False, True]
            return 0 if [r['compatible'] for r in reports] == expected else 2
        if args.command == 'export':
            print(export_bundle(json.loads(args.report.read_text(encoding='utf-8')))); return 0
        if args.command == 'reduce':
            result = minimize(load(args.case))
            archive = export_bundle(result)
            print('Reduced {} rows / {} operations to {} rows / {} operations; verified: {}'.format(
                result['original_rows'], result['original_operations'], result['remaining_rows'],
                result['remaining_operations'], result['one_minimal_verified']))
            print('Bundle: ' + archive); return 0
        if args.command == 'replay':
            prior = json.loads(args.report.read_text(encoding='utf-8'))
            result = run_case(prior['case'])
            print('Same signatures:', [f['signature'] for f in result['findings']] == [f['signature'] for f in prior['findings']])
        else:
            result = run_case(load(args.case))
        show(result)
        return 0 if result['compatible'] else 1
    except (ValueError, TypeError, RuntimeError, OSError, KeyError) as error:
        print('HARNESS ERROR: ' + str(error), file=sys.stderr); return 2


if __name__ == '__main__':
    raise SystemExit(main())
