import copy
import unittest
from driftlab.generate import generate
from driftlab.model import validate
from driftlab.compare import rows_equal


class ModelTests(unittest.TestCase):
    def test_seeded_generation_is_repeatable(self):
        self.assertEqual(generate(count=40, seed=5), generate(count=40, seed=5))
        self.assertNotEqual(generate(count=40, seed=5), generate(count=40, seed=6))

    def test_rejects_raw_sql_and_ambiguous_limit(self):
        case = generate(count=4)
        case['operations'][0]['sql'] = 'DROP DATABASE something'
        with self.assertRaises(ValueError):
            validate(case)
        case = generate(count=4)
        case['operations'][0]['order_by'] = [{'column': 'priority'}]
        with self.assertRaises(ValueError):
            validate(case)

    def test_rejects_identifier_injection(self):
        case = generate(count=4)
        case['tables'][0]['name'] = 'records; DROP TABLE records'
        with self.assertRaises(ValueError):
            validate(case)

    def test_bag_comparison_preserves_multiplicity(self):
        self.assertTrue(rows_equal([[1], [2]], [[2.0], [1]], False))
        self.assertFalse(rows_equal([[1], [1], [2]], [[1], [2], [2]], False))
        self.assertFalse(rows_equal([[1], [2]], [[2], [1]], True))
        self.assertFalse(rows_equal([['1']], [[1]], False))

    def test_boolean_version_and_excessive_input_rejected(self):
        case = generate(count=4)
        case['version'] = True
        with self.assertRaises(ValueError):
            validate(case)
        with self.assertRaises(ValueError):
            generate(count=1001)
