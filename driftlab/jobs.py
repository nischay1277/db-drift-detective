"""Bounded asynchronous comparisons with persisted history and cancellation."""
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid

from . import ROOT
from .database import configured
from .engine import run_case
from .export import export_bundle
from .model import validate
from .reduce import minimize

ACTIVE = ('queued', 'running', 'cancelling')


class Manager:
    def __init__(self, root=None):
        self.root = (Path(root) if root else ROOT / 'runs' / 'dashboard').resolve()
        if self.root.drive.lower() != 'd:':
            raise ValueError('History must stay on D:')
        self.history = self.root / 'jobs'
        self.history.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.records, self.events, self.closed = {}, {}, False
        for file in self.history.glob('*.json'):
            item = json.loads(file.read_text(encoding='utf-8'))
            self.records[item['id']] = item
            if item['status'] in ACTIVE:
                item.update(status='interrupted', error='Server stopped; replay the case explicitly.')
                self.persist(item)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='driftlab')

    def persist(self, item):
        file = self.history / (item['id'] + '.json')
        temporary = file.with_suffix('.tmp')
        temporary.write_text(json.dumps(item, indent=2), encoding='utf-8')
        temporary.replace(file)

    def get(self, identifier):
        with self.lock:
            if identifier not in self.records:
                raise KeyError(identifier)
            return copy.deepcopy(self.records[identifier])

    def list(self):
        with self.lock:
            return [{'id': item['id'], 'name': item['case']['name'], 'status': item['status'],
                     'kind': item['kind'], 'created_at': item['created_at'], 'rows': len(item['case']['rows'])}
                    for item in sorted(self.records.values(), key=lambda x: x['created_at'], reverse=True)[:100]]

    def submit(self, raw, kind='compare'):
        case = validate(raw)
        if kind not in ('compare', 'reduce'):
            raise ValueError('kind must be compare or reduce')
        if not configured():
            raise ValueError('PostgreSQL is not configured')
        with self.lock:
            if self.closed or sum(r['status'] in ACTIVE for r in self.records.values()) >= 6:
                raise RuntimeError('Experiment queue is unavailable or full')
            identifier = uuid.uuid4().hex
            item = {'id': identifier, 'kind': kind, 'case': case, 'status': 'queued',
                    'created_at': datetime.now(timezone.utc).isoformat()}
            self.records[identifier], self.events[identifier] = item, threading.Event()
            self.persist(item)
            self.pool.submit(self.execute, identifier)
            return copy.deepcopy(item)

    def execute(self, identifier):
        event = self.events[identifier]
        try:
            with self.lock:
                if event.is_set():
                    raise InterruptedError('Cancelled before execution')
                item = self.records[identifier]
                item['status'] = 'running'
                self.persist(item)
                case, kind = copy.deepcopy(item['case']), item['kind']
            result = (minimize(case, self.root / 'reductions', event) if kind == 'reduce'
                      else run_case(case, self.root / 'comparisons', event))
            if event.is_set():
                raise InterruptedError('Cancelled before export')
            bundle = export_bundle(result)
            with self.lock:
                item.update(status=result['status'], result=result, bundle=bundle)
                self.persist(item)
        except Exception as error:
            with self.lock:
                item = self.records[identifier]
                item.update(status='cancelled' if isinstance(error, InterruptedError) else 'error', error=str(error))
                self.persist(item)
        finally:
            with self.lock:
                self.events.pop(identifier, None)

    def cancel(self, identifier):
        with self.lock:
            item = self.get(identifier)
            if item['status'] not in ACTIVE:
                raise ValueError('Only queued/running jobs can be cancelled')
            self.events[identifier].set()
            self.records[identifier]['status'] = 'cancelling'
            self.persist(self.records[identifier])
            return self.get(identifier)

    def close(self):
        with self.lock:
            self.closed = True
            for event in self.events.values():
                event.set()
        self.pool.shutdown(wait=True)
