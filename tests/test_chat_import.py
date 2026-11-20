import copy
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from driftlab import ROOT
from driftlab.chat_import import as_case, fixture, parse, preflight, run_preflight
from driftlab.database import connect_postgres
from driftlab.engine import run_case
from driftlab.model import validate
from driftlab.reduce import minimize


class ChatImportTests(unittest.TestCase):
    def test_json_import_succeeds_but_postgres_search_fails(self):
        result = run_case(as_case(fixture(8)), ROOT / 'runs' / 'tests')
        self.assertFalse(result['compatible'])
        for engine in ('sqlite', 'postgres'):
            self.assertTrue(all(s['accepted'] for s in result['engines'][engine]['steps'] if s['source'] == 'seed'))
        sqlite = result['engines']['sqlite']['steps'][-1]
        postgres = result['engines']['postgres']['steps'][-1]
        self.assertTrue(sqlite['accepted'])
        self.assertEqual(len(sqlite['rows']), 1)
        self.assertFalse(postgres['accepted'])
        self.assertEqual(postgres['error']['code'], '22P05')
        self.assertEqual(postgres['error']['category'], 'encoding')
        self.assertEqual(len(result['findings']), 1)

    def test_repaired_copy_preserves_search_and_normal_text(self):
        document = fixture(4)
        document[0]['chat']['messages'][0]['content'] = 'தமிழ் / Кириллица / literal \\u0000 / newline\n'
        original = copy.deepcopy(document)
        result = preflight(document, True)
        self.assertEqual(document, original)
        self.assertFalse(result['input_passes_nul_policy'])
        self.assertTrue(result['output_passes_nul_policy'])
        self.assertEqual(result['document'][0], document[0])
        report = run_case(as_case(result['document']), ROOT / 'runs' / 'tests')
        self.assertTrue(report['compatible'])
        self.assertEqual(len(report['engines']['postgres']['steps'][-1]['rows']), 1)

    def test_dry_run_never_alters_input(self):
        doc = fixture(2)
        result = preflight(doc)
        self.assertEqual(doc, result['document'])
        self.assertFalse(result['repair_applied'])
        self.assertFalse(result['output_passes_nul_policy'])

    def test_literal_escape_is_not_an_actual_nul(self):
        document = [{'messages': [{'content': r'literal \u0000 remains'}]}]
        result = preflight(document, True)
        self.assertTrue(result['input_passes_nul_policy'])
        self.assertEqual(result['document'], document)
        self.assertEqual(result['nul_occurrences'], 0)

    def test_duplicate_keys_and_repair_collision_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON keys'):
            parse('{"messages":[],"messages":[]}')
        document = {'messages': [], 'metadata': {'x\x00': 1, 'x[NUL]': 2}}
        with self.assertRaisesRegex(ValueError, 'key collision'):
            preflight(document, True)

    def test_original_file_and_audit_remain_available(self):
        folder = ROOT / 'runs' / 'tests' / 'imports' / uuid.uuid4().hex
        folder.mkdir(parents=True)
        source = folder / 'input.json'
        original = json.dumps(fixture(3)).encode()
        source.write_bytes(original)
        result = run_preflight(source, True, True, folder / 'outputs')
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual((Path(result['run_dir']) / 'original.json').read_bytes(), original)
        self.assertFalse(result['verification']['before_compatible'])
        self.assertTrue(result['verification']['after_compatible'])
        self.assertTrue((Path(result['run_dir']) / 'audit.json').is_file())

    def test_reduces_real_failure_to_one_poisoned_chat_and_search(self):
        result = minimize(as_case(fixture(16)), ROOT / 'runs' / 'tests' / 'reductions')
        self.assertEqual((result['remaining_rows'], result['remaining_operations']), (1, 1))
        self.assertTrue(result['one_minimal_verified'])
        self.assertEqual(result['target_signature']['step_id'], 'search_chat_messages')

    def test_json_model_rejects_invalid_paths_and_keys(self):
        case = as_case(fixture(2))
        case['operations'][0]['where'][0]['path'] = ["messages'); DROP TABLE chat; --"]
        with self.assertRaises(ValueError):
            validate(case)

    def test_client_driver_error_is_not_reported_as_database_drift(self):
        from driftlab.database import operation
        def broken(op, engine):
            if engine == 'postgres' and op['type'] == 'select':
                return 'SELECT %q', []
            return operation(op, engine)
        with patch('driftlab.database.operation', broken):
            with self.assertRaisesRegex(RuntimeError, 'not a compatibility finding'):
                run_case(as_case(fixture(2)), ROOT / 'runs' / 'tests')

    def test_json_predicate_values_are_bound_and_percent_safe(self):
        case = as_case(fixture(2))
        case['operations'][0]['where'][0]['value'] = "semax' OR 1=1 --"
        result = run_case(case, ROOT / 'runs' / 'tests')
        for engine in ('sqlite', 'postgres'):
            search = result['engines'][engine]['steps'][-1]
            self.assertNotIn("OR 1=1", search['sql'])
            self.assertIn("%semax' or 1=1 --%", search['parameters'])
        case = as_case(fixture(2))
        case['tables'][0]['columns'][2]['unique'] = True
        with self.assertRaises(ValueError):
            validate(case)
