import unittest

from harness.stats import bootstrap_ci, compare_runs, match_cases, paired_diffs, verdict


def case(seed_set, mood, **scores):
    # A run case holding only what the comparison reads; unset metrics are None
    from harness.metrics import METRICS
    return {'seed_set': seed_set, 'mood': mood, 'scores': {name: scores.get(name) for name in METRICS}}


class BootstrapCITest(unittest.TestCase):
    def test_constant_values_give_zero_width_ci(self):
        self.assertEqual(bootstrap_ci([0.5] * 20), (0.5, 0.5))

    def test_ci_contains_mean_and_is_reproducible(self):
        values = [i / 10 for i in range(11)]
        low, high = bootstrap_ci(values)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)
        self.assertEqual(bootstrap_ci(values), (low, high))

    def test_none_values_are_skipped(self):
        self.assertEqual(bootstrap_ci([None, 0.3, None, 0.3]), (0.3, 0.3))
        self.assertIsNone(bootstrap_ci([None, None]))


class PairedDiffTest(unittest.TestCase):
    def test_matched_cases_pair_by_seed_set_and_mood(self):
        before = [case('a', 'happy', mood_fit=0.5), case('a', 'sad', mood_fit=0.6)]
        after = [case('a', 'sad', mood_fit=0.7), case('a', 'happy', mood_fit=0.6)]  # other order
        pairs = match_cases(before, after)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(sorted(round(d, 6) for d in paired_diffs(pairs, 'mood_fit')), [0.1, 0.1])

    def test_mismatched_cases_return_none(self):
        before = [case('a', 'happy'), case('a', 'sad')]
        self.assertIsNone(match_cases(before, [case('a', 'happy'), case('a', 'calm')]))
        self.assertIsNone(match_cases(before, [case('a', 'happy')]))
        self.assertIsNone(match_cases(before, [case('a', 'happy'), case('a', 'happy')]))

    def test_pairs_skip_cases_where_either_run_is_none(self):
        pairs = match_cases([case('a', 'happy', mood_fit=None), case('a', 'sad', mood_fit=0.2)],
                            [case('a', 'happy', mood_fit=0.9), case('a', 'sad', mood_fit=0.4)])
        self.assertEqual([round(d, 6) for d in paired_diffs(pairs, 'mood_fit')], [0.2])

    def test_compare_runs_falls_back_to_unpaired(self):
        before = [case('a', 'happy', mood_fit=0.5), case('a', 'sad', mood_fit=0.5)]
        after = [case('a', 'happy', mood_fit=0.7), case('b', 'sad', mood_fit=0.7)]
        rows, paired = compare_runs(before, after)
        self.assertFalse(paired)
        self.assertAlmostEqual(rows['mood_fit']['change'], 0.2)

    def test_consistent_paired_improvement_is_better(self):
        before = [case('a', m, mood_fit=0.5 + i / 100) for i, m in enumerate('abcdefghij')]
        after = [case('a', m, mood_fit=0.6 + i / 100) for i, m in enumerate('abcdefghij')]
        rows, paired = compare_runs(before, after)
        self.assertTrue(paired)
        self.assertEqual(rows['mood_fit']['verdict'], 'better')


class VerdictTest(unittest.TestCase):
    def test_ci_spanning_zero_is_no_clear_change(self):
        self.assertEqual(verdict((-0.02, 0.03), 'higher'), 'no clear change')
        self.assertEqual(verdict((-0.02, 0.03), None), 'no clear change')
        self.assertEqual(verdict((0.0, 0.0), 'lower'), 'no clear change')

    def test_ci_excluding_zero_follows_better_direction(self):
        self.assertEqual(verdict((0.01, 0.03), 'higher'), 'better')
        self.assertEqual(verdict((0.01, 0.03), 'lower'), 'WORSE')
        self.assertEqual(verdict((-0.03, -0.01), 'lower'), 'better')
        self.assertEqual(verdict((0.01, 0.03), None), 'changed')

    def test_noisy_paired_change_is_no_clear_change(self):
        moods = 'abcdefghij'
        before = [case('a', m, mood_fit=0.5) for m in moods]
        after = [case('a', m, mood_fit=0.5 + d) for m, d in zip(moods, [0.1, -0.1] * 5)]
        rows, _ = compare_runs(before, after)
        self.assertEqual(rows['mood_fit']['verdict'], 'no clear change')


if __name__ == '__main__':
    unittest.main()
