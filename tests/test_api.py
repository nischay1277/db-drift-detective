import json
import time
import unittest
import uuid
import driftlab
from fastapi.testclient import TestClient
from driftlab import ROOT
from driftlab.api import create_app
from driftlab.generate import generate
from driftlab.jobs import Manager


class APITests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'runs' / 'tests' / 'api' / uuid.uuid4().hex

    def wait(self, client, identifier):
        deadline = time.perf_counter() + 40
        while time.perf_counter() < deadline:
            item = client.get('/api/jobs/' + identifier).json()
            if item['status'] not in ('queued', 'running', 'cancelling'):
                return item
            time.sleep(.04)
        self.fail('Job did not finish')

    def test_compare_replay_bundle_and_persisted_history(self):
        with TestClient(create_app(self.root)) as client:
            self.assertEqual(client.get('/').status_code, 200)
            self.assertEqual(client.get('/static/app.js').status_code, 200)
            response = client.post('/api/jobs', json={'case': generate(count=4)})
            self.assertEqual(response.status_code, 202)
            first = self.wait(client, response.json()['id'])
            self.assertEqual(first['status'], 'drift')
            replay = self.wait(client, client.post('/api/jobs/' + first['id'] + '/replay').json()['id'])
            self.assertEqual(first['result']['findings'][0]['signature'], replay['result']['findings'][0]['signature'])
            bundle = client.get('/api/jobs/' + first['id'] + '/bundle')
            self.assertEqual(bundle.status_code, 200)
            self.assertTrue(bundle.content.startswith(b'PK'))
        with TestClient(create_app(self.root)) as client:
            self.assertEqual(len(client.get('/api/jobs').json()), 2)

    def test_generation_and_invalid_inputs(self):
        with TestClient(create_app(self.root)) as client:
            case = client.post('/api/generate', json={'family': 'like_case', 'rows': 12, 'seed': 4})
            self.assertEqual(case.status_code, 200)
            self.assertEqual(len(case.json()['rows']), 12)
            self.assertEqual(client.post('/api/jobs', json={'case': {'version': 1}}).status_code, 422)
            self.assertEqual(client.post('/api/jobs', json={'case': generate(count=4)},
                                        headers={'origin': 'https://unrelated.example'}).status_code, 403)
            self.assertEqual(client.post('/api/generate', json={'rows': 10000}).status_code, 422)
            self.assertEqual(client.get('/api/jobs/unknown').status_code, 404)

    def test_cancellation_and_interrupted_restart(self):
        with TestClient(create_app(self.root)) as client:
            response = client.post('/api/jobs', json={'case': generate(count=300), 'kind': 'reduce'})
            identifier = response.json()['id']
            self.assertEqual(client.post('/api/jobs/' + identifier + '/cancel').status_code, 200)
            self.assertEqual(self.wait(client, identifier)['status'], 'cancelled')
        identifier = uuid.uuid4().hex
        (self.root / 'jobs' / (identifier + '.json')).write_text(json.dumps({'id': identifier,
            'kind': 'compare', 'status': 'running', 'created_at': '2026-01-01T00:00:00Z', 'case': generate(count=4)}))
        manager = Manager(self.root)
        try:
            self.assertEqual(manager.get(identifier)['status'], 'interrupted')
        finally:
            manager.close()
