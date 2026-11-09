import math
import unittest

from harness.metrics import duration_fit, generated_tracks, mean_scores, score_case


def track(uri, artist):
    return {'uri': uri, 'name': uri, 'artist': artist}


SEEDS = [track('S1', 'SeedArtist'), track('S2', 'Other')]
# S1, its similar tracks (a duplicate and a re-recommended seed S2), S2, then a mood track
CASE = {
    'seeds': SEEDS,
    'tracks': [track('S1', 'SeedArtist'), track('A', 'X'), track('A', 'X'), track('S2', 'Other'),
               track('S2', 'Other'), track('B', 'SeedArtist'), track('C', 'Y')],
    'calls': [{'status_code': 200}, {'status_code': 400}, {'status_code': 200}, {'status_code': 200}],
}
FEATURES = {'A': {'valence': 1.0, 'energy': 1.0}, 'B': {'valence': 0.5, 'energy': 0.5},
            'S2': {'valence': 0.5, 'energy': 0.5}}  # C has no features
TARGET = {'valence': 0.5, 'energy': 0.5}


class GeneratedTracksTest(unittest.TestCase):
    def test_each_seed_removed_once_and_re_recommendations_kept(self):
        self.assertEqual([t['uri'] for t in generated_tracks(CASE)], ['A', 'A', 'S2', 'B', 'C'])


class ScoreCaseTest(unittest.TestCase):
    def setUp(self):
        self.scores = score_case(CASE, FEATURES, TARGET, requested=20)

    def test_counting_metrics(self):
        self.assertEqual(self.scores['generated'], 5)
        self.assertAlmostEqual(self.scores['fill_rate'], 5 / 20)
        self.assertAlmostEqual(self.scores['feature_coverage'], 4 / 5)
        self.assertAlmostEqual(self.scores['error_rate'], 1 / 4)
        self.assertAlmostEqual(self.scores['duplicate_rate'], 1 - 4 / 5)

    def test_diversity_and_seed_metrics(self):
        self.assertAlmostEqual(self.scores['artist_diversity'], 4 / 5)  # X, Other, SeedArtist, Y
        self.assertAlmostEqual(self.scores['seed_overlap'], 1 / 5)  # S2 re-recommended
        self.assertAlmostEqual(self.scores['seed_artist_share'], 2 / 5)  # S2 by Other, B by SeedArtist

    def test_mood_fit(self):
        # A, A are sqrt(0.5) from the target; S2 and B are on it; C has no features
        expected = 1 - (2 * math.sqrt(0.5) / 4) / math.sqrt(2)
        self.assertAlmostEqual(self.scores['mood_fit'], expected)
        self.assertIsNone(score_case(CASE, FEATURES, None, 20)['mood_fit'])

    def test_playlist_of_only_seeds(self):
        empty = score_case({'seeds': SEEDS, 'tracks': SEEDS, 'calls': []}, {}, TARGET, 20)
        self.assertEqual(empty['fill_rate'], 0.0)
        self.assertIsNone(empty['duplicate_rate'])
        self.assertIsNone(empty['error_rate'])


class DurationFitTest(unittest.TestCase):
    def tracks(self, *minutes):
        return [{'uri': str(i), 'duration_ms': m * 60_000} for i, m in enumerate(minutes)]

    def test_exact_fit_is_one(self):
        self.assertAlmostEqual(duration_fit(self.tracks(10, 10), 20), 1.0)

    def test_half_and_double_score_the_same(self):
        self.assertAlmostEqual(duration_fit(self.tracks(10), 20), 0.5)
        self.assertAlmostEqual(duration_fit(self.tracks(20, 20), 20), 0.5)

    def test_undefined_without_a_journey_or_a_length(self):
        self.assertIsNone(duration_fit(self.tracks(10), None))
        self.assertIsNone(duration_fit([], 20))
        self.assertIsNone(duration_fit(self.tracks(10) + [{'uri': 'x'}], 20))

    def test_score_case_measures_whole_playlist_and_skips_fill_rate(self):
        case = {'seeds': [{'uri': 'S', 'artist': 'a', 'duration_ms': 600_000}],
                'tracks': [{'uri': 'S', 'artist': 'a', 'duration_ms': 600_000},
                           {'uri': 'T', 'artist': 'b', 'duration_ms': 600_000}],
                'calls': [], 'journey_minutes': 20}
        scores = score_case(case, {}, None, requested=None)
        self.assertAlmostEqual(scores['duration_fit'], 1.0)  # the seed's 10 minutes count
        self.assertIsNone(scores['fill_rate'])

    def test_full_length_case_has_no_duration_fit(self):
        self.assertIsNone(score_case(CASE, FEATURES, TARGET, requested=20)['duration_fit'])


class MeanScoresTest(unittest.TestCase):
    def test_means_skip_undefined_values(self):
        full = score_case(CASE, FEATURES, TARGET, 20)
        empty = score_case({'seeds': SEEDS, 'tracks': SEEDS, 'calls': []}, {}, TARGET, 20)
        means = mean_scores([full, empty])
        self.assertAlmostEqual(means['duplicate_rate'], full['duplicate_rate'])
        self.assertAlmostEqual(means['fill_rate'], (0.25 + 0) / 2)


if __name__ == '__main__':
    unittest.main()
