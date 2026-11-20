import json
from pathlib import Path
import subprocess
import sys
import unittest
import zipfile

from driftlab import ROOT
from driftlab.engine import run_case
from driftlab.export import export_bundle
from driftlab.generate import generate
from driftlab.reduce import minimize


class ReductionExportTests(unittest.TestCase):
    def test_reduces_noise_rows_and_operations(self):
        result = minimize(generate('null_order', 32), ROOT / 'runs' / 'tests' / 'reductions')
        self.assertEqual(result['remaining_rows'], 2)
        self.assertEqual(result['remaining_operations'], 1)
        self.assertTrue(result['one_minimal_verified'])
        self.assertEqual(result['target_signature'], {'source': 'operation', 'step_id': 'first_record', 'kind': 'rows'})

    def test_reduces_write_failure_to_operation_without_seed_rows(self):
        result = minimize(generate('flexible_typing', 8), ROOT / 'runs' / 'tests' / 'reductions')
        self.assertEqual(result['remaining_rows'], 0)
        self.assertEqual(result['remaining_operations'], 1)
        self.assertTrue(result['one_minimal_verified'])

    def test_refuses_passing_case(self):
        with self.assertRaisesRegex(ValueError, 'reproducible finding'):
            minimize(generate('compatible', 4), ROOT / 'runs' / 'tests' / 'reductions')

    def test_export_reproduces_and_regression_catches_drift(self):
        result = run_case(generate('null_order', 4), ROOT / 'runs' / 'tests')
        archive = Path(export_bundle(result))
        folder = archive.parent / 'export'
        reproduce = subprocess.run([sys.executable, '-B', str(folder / 'reproduce.py')], capture_output=True, text=True)
        self.assertEqual(reproduce.returncode, 0, reproduce.stderr)
        regression = subprocess.run([sys.executable, '-B', str(folder / 'test_regression.py')], capture_output=True, text=True)
        self.assertEqual(regression.returncode, 1)
        self.assertIn('Migration drift', regression.stderr)
        password = json.loads((ROOT / '.secrets' / 'postgres.json').read_text())['password']
        with zipfile.ZipFile(archive) as bundle:
            self.assertIn('postgres-bindings.json', bundle.namelist())
            self.assertFalse(any(password.encode() in bundle.read(name) for name in bundle.namelist()),
                             'Private connection credentials must not be exported')

    def test_exported_compatible_regression_passes(self):
        result = run_case(generate('compatible', 4), ROOT / 'runs' / 'tests')
        archive = Path(export_bundle(result))
        check = subprocess.run([sys.executable, '-B', str(archive.parent / 'export' / 'test_regression.py')], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
