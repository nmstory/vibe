import unittest

from harness.baselines import popular_baseline, random_baseline
from harness.metrics import generated_tracks

SEEDS = [{'uri': f"spotify:track:seed{i}", 'name': f"Seed {i}", 'artist': f"Seed artist {i}"} for i in range(3)]
POOL = [{'uri': f"spotify:track:t{i:03d}", 'name': f"Track {i}", 'artist': f"Artist {i % 40}",
         'popularity': i % 50} for i in range(200)]
SEED_URIS = tuple(s['uri'] for s in SEEDS)
COUNTS = {('happy', SEED_URIS): 23, ('sad', SEED_URIS): 7}


def as_case(seeds, tracks):
    return {'seeds': seeds, 'tracks': tracks}


class RandomBaselineTest(unittest.TestCase):
    def test_deterministic_with_fixed_seed(self):
        first = random_baseline(POOL, COUNTS, seed=1)('happy', SEEDS)
        again = random_baseline(POOL, COUNTS, seed=1)('happy', SEEDS)
        other = random_baseline(POOL, COUNTS, seed=2)('happy', SEEDS)
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)

    def test_track_count_matches_pipeline_and_has_no_duplicates(self):
        generate = random_baseline(POOL, COUNTS)
        for mood, n in [('happy', 23), ('sad', 7)]:
            generated = generated_tracks(as_case(SEEDS, generate(mood, SEEDS)))
            self.assertEqual(len(generated), n)
            self.assertEqual(len({t['uri'] for t in generated}), n)

    def test_seeds_kept_in_place(self):
        tracks = random_baseline(POOL, COUNTS)('happy', SEEDS)
        # Each seed is followed by its share of tracks, as in the pipeline
        self.assertEqual([tracks[0], tracks[6], tracks[12]], SEEDS)
        self.assertNotIn('popularity', tracks[1])


class PopularBaselineTest(unittest.TestCase):
    def test_picks_most_popular_regardless_of_mood(self):
        generate = popular_baseline(POOL, COUNTS)
        happy = generated_tracks(as_case(SEEDS, generate('happy', SEEDS)))
        sad = generated_tracks(as_case(SEEDS, generate('sad', SEEDS)))
        self.assertEqual(len(happy), 23)
        self.assertEqual(sad, happy[:7])  # same ranking, fewer tracks
        popularity = {t['uri']: t['popularity'] for t in POOL}
        self.assertTrue(all(popularity[t['uri']] == 49 for t in happy[:4]))

    def test_deterministic_and_seeds_in_place(self):
        tracks = popular_baseline(POOL, COUNTS)('happy', SEEDS)
        self.assertEqual(tracks, popular_baseline(POOL, COUNTS)('happy', SEEDS))
        self.assertEqual([tracks[0], tracks[6], tracks[12]], SEEDS)


if __name__ == '__main__':
    unittest.main()
