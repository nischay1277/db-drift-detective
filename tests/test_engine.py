from pathlib import Path
import json
import threading
import unittest

from driftlab import ROOT
from driftlab.database import connect_postgres
from driftlab.engine import run_case
from driftlab.generate import generate


class EngineTests(unittest.TestCase):
    def compare(self, case):
        return run_case(case, ROOT / 'runs' / 'tests')

    def test_all_known_difference_families(self):
        expected = {'null_order': 'rows', 'flexible_typing': 'acceptance', 'foreign_keys': 'acceptance',
                    'like_case': 'rows', 'nul_text': 'acceptance'}
        for family, kind in expected.items():
            with self.subTest(family=family):
                result = self.compare(generate(family, 8))
                self.assertFalse(result['compatible'])
                self.assertEqual(result['findings'][0]['signature']['kind'], kind)

    def test_fixed_variants_are_compatible(self):
        for family in ('null_order', 'flexible_typing', 'foreign_keys', 'compatible'):
            with self.subTest(family=family):
                self.assertTrue(self.compare(generate(family, 8, fixed=True))['compatible'])

    def test_rejected_write_does_not_abort_subsequent_operations(self):
        case = generate('compatible', 4)
        case['operations'].insert(0, {'id': 'duplicate_id', 'type': 'insert', 'table': 'records',
                                     'values': {'id': 1, 'label': 'duplicate'}})
        result = self.compare(case)
        self.assertTrue(result['compatible'])
        for engine in ('sqlite', 'postgres'):
            duplicate = next(s for s in result['engines'][engine]['steps'] if s['id'] == 'duplicate_id')
            self.assertFalse(duplicate['accepted'])
            self.assertEqual(duplicate['error']['category'], 'unique')
            updated = next(row for row in result['engines'][engine]['state']['records']['rows'] if row[0] == 1)
            self.assertEqual(updated[2], 'updated')

    def test_postgres_schema_is_cleaned_and_case_replays(self):
        a = self.compare(generate('null_order', 5))
        b = self.compare(a['case'])
        self.assertEqual([f['signature'] for f in a['findings']], [f['signature'] for f in b['findings']])
        self.assertNotEqual(a['postgres_schema'], b['postgres_schema'])
        with connect_postgres() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (a['postgres_schema'],)).fetchone())
            self.assertEqual(db.execute('SELECT current_database()').fetchone()[0], 'driftlab')

    def test_bound_strings_cannot_become_sql(self):
        case = generate('compatible', 4)
        value = "x'); DROP TABLE records; --"
        case['rows'][1]['values']['label'] = value
        result = self.compare(case)
        self.assertTrue(result['compatible'])
        for engine in ('sqlite', 'postgres'):
            row = result['engines'][engine]['steps'][1]
            self.assertNotIn(value, row['sql'])
            self.assertIn(value, row['parameters'])

    def test_integer_range_drift(self):
        case = generate('compatible', 4)
        case['rows'][0]['values']['priority'] = 2**40
        result = self.compare(case)
        self.assertEqual(result['findings'][0]['signature']['kind'], 'acceptance')
        self.assertEqual(result['findings'][0]['postgres']['error']['category'], 'numeric_range')

    def test_filtered_delete_and_not_null_rejection(self):
        case = generate('compatible', 4)
        case['tables'][0]['columns'][2]['nullable'] = False
        case['operations'].extend([
            {'id': 'reject_null', 'type': 'insert', 'table': 'records', 'values': {'id': 99, 'label': None}},
            {'id': 'delete_one', 'type': 'delete', 'table': 'records',
             'where': [{'column': 'id', 'op': 'eq', 'value': 2}]},
            {'id': 'final_read', 'type': 'select', 'table': 'records', 'order_by': [{'column': 'id'}]}])
        report = self.compare(case)
        self.assertTrue(report['compatible'])
        for engine in ('sqlite', 'postgres'):
            rejected = next(s for s in report['engines'][engine]['steps'] if s['id'] == 'reject_null')
            self.assertEqual(rejected['error']['category'], 'not_null')
            self.assertEqual(len(report['engines'][engine]['state']['records']['rows']), 3)

    def test_cancel_and_forbidden_output_drive(self):
        event = threading.Event(); event.set()
        with self.assertRaises(InterruptedError):
            run_case(generate(count=4), ROOT / 'runs' / 'tests', event)
        with self.assertRaises(ValueError):
            run_case(generate(count=4), Path('C:/drift-forbidden'))
