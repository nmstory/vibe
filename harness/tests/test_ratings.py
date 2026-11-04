import argparse
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import ratings


def write_sheet(path, scores):
    """A sheet with every row of the real sample; scores: {row id: (mood_fit, seed_fit)} as strings."""
    items = json.loads(ratings.SAMPLE_PATH.read_text(encoding='utf-8'))['items']
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=ratings.SHEET_COLUMNS)
        writer.writeheader()
        for item in items:
            mood_fit, seed_fit = scores.get(item['id'], ('', ''))
            writer.writerow({'id': item['id'], 'mood': item['mood'], 'mood_fit': mood_fit, 'seed_fit': seed_fit})


class SpearmanTest(unittest.TestCase):
    def test_same_and_opposite_order(self):
        self.assertAlmostEqual(ratings.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1)
        self.assertAlmostEqual(ratings.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1)

    def test_ties_share_an_average_rank(self):
        self.assertEqual(ratings.ranks([5, 1, 5, 3]), [3.5, 1.0, 3.5, 2.0])

    def test_needs_three_points(self):
        self.assertIsNone(ratings.spearman([1, 2], [1, 2]))


class ReadRatingsTest(unittest.TestCase):
    def test_valid_blank_and_invalid_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / 'sheet.csv'
            write_sheet(sheet, {'R001': ('4', '2'), 'R002': ('6', ''), 'R003': ('', '5')})
            _, parsed, problems = ratings.read_ratings(sheet)

        self.assertEqual(parsed['R001'], {'mood_fit': 4, 'seed_fit': 2})
        self.assertEqual(parsed['R002'], {})  # 6 is invalid, the blank is skipped
        self.assertEqual(parsed['R003'], {'seed_fit': 5})
        self.assertEqual(problems, ["R002 mood_fit: '6' is not 1-5"])

    def test_missing_sheet_is_a_clear_error(self):
        with self.assertRaises(SystemExit):
            ratings.read_ratings(Path(tempfile.gettempdir()) / 'no-such-sheet.csv')


class SampleGuardTest(unittest.TestCase):
    def test_refuses_to_overwrite_an_existing_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / 'sheet.csv'
            sheet.write_text('may hold ratings', encoding='utf-8')
            with mock.patch.object(ratings, 'SHEET_PATH', sheet):
                with self.assertRaises(SystemExit) as raised:
                    ratings.sample_command(argparse.Namespace(force=False, run=None, per_case=3))
            self.assertEqual(sheet.read_text(encoding='utf-8'), 'may hold ratings')
        self.assertIn('already exists', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
