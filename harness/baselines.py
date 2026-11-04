"""Reference systems scored by the same metrics as the pipeline.

A score like mood_fit 0.77 means little on its own: an unrelated track still
scores around 0.6. These baselines give it context. Each is built as a
generate(mood, seed_tracks) function, the same interface as
pipeline.generate_playlist_tracks, so run.py runs and scores them unchanged.

- random:  the same number of generated tracks as the pipeline produced for
           the case, drawn uniformly from the candidate pool
- popular: the most popular tracks in the pool, ignoring mood and seeds
           ("just play the hits")

The candidate pool is every track in the pipeline's recommendation responses
during the run: the similar tracks plus the full 100-candidate mood pools.
It's recovered from the cached responses, so it costs no extra API calls.
"""
import random

import pipeline
from harness.metrics import generated_tracks

RECOMMENDATION_URL = f"{pipeline.RECCOBEATS_URL}/track/recommendation"
RNG_SEED = 0


def candidate_pool(cases, http):
    """Every track in the run's successful recommendation responses, with its
    ReccoBeats popularity (0-100). Sorted by uri, so the pool is stable.

    http: the harness's CachedRequests, which serves the responses from disk.
    """
    pool = {}
    seen_calls = set()

    for case in cases:
        for call in case['calls']:
            if call['url'] != RECOMMENDATION_URL or call['status_code'] != 200:
                continue
            key = http.key(call['url'], call['params'])
            if key in seen_calls:
                continue
            seen_calls.add(key)

            response = http.get(call['url'], params=call['params'])
            for item in response.json().get('content', []):
                track = pipeline.to_track(item)
                # pipeline.to_track drops popularity; keep it for the popular baseline
                track['popularity'] = item['popularity']
                pool[track['uri']] = track

    return [pool[uri] for uri in sorted(pool)]


def track_counts(cases):
    """{(mood, seed uris): number of generated tracks} for the pipeline's run,
    so each baseline case gets as many tracks as the pipeline produced."""
    return {
        (case['mood'], tuple(seed['uri'] for seed in case['seeds'])): len(generated_tracks(case))
        for case in cases
    }


def with_seeds(seed_tracks, generated):
    # Lay the playlist out as the pipeline does: each seed followed by its
    # share of tracks, then the rest, so generated_tracks() works unchanged
    track_list = []
    rest = list(generated)

    for seed in seed_tracks:
        track_list.append(seed)
        track_list.extend(rest[:pipeline.SIMILAR_PER_SEED])
        rest = rest[pipeline.SIMILAR_PER_SEED:]

    return track_list + rest


def plain(track):
    return {'uri': track['uri'], 'name': track['name'], 'artist': track['artist']}


def random_baseline(pool, counts, seed=RNG_SEED):
    """generate(mood, seed_tracks): a uniform sample from the pool, without
    replacement, of the size the pipeline produced for that case."""
    def generate(mood, seed_tracks):
        seed_uris = tuple(t['uri'] for t in seed_tracks)
        n = counts[(mood, seed_uris)]
        # Seeded per case, so a case's draw doesn't depend on the order cases run in
        rng = random.Random(f"{seed}|{mood}|{'|'.join(seed_uris)}")
        return with_seeds(seed_tracks, [plain(t) for t in rng.sample(pool, n)])

    return generate


def popular_baseline(pool, counts):
    """generate(mood, seed_tracks): the n most popular tracks in the pool,
    ties broken by uri. Mood and seeds don't change the picks."""
    by_popularity = sorted(pool, key=lambda t: (-t['popularity'], t['uri']))

    def generate(mood, seed_tracks):
        n = counts[(mood, tuple(t['uri'] for t in seed_tracks))]
        return with_seeds(seed_tracks, [plain(t) for t in by_popularity[:n]])

    return generate


def build_baselines(cases, http):
    """{name: generate} for the baselines, built from a pipeline run's cases."""
    pool = candidate_pool(cases, http)
    counts = track_counts(cases)
    return pool, {
        'random': random_baseline(pool, counts),
        'popular': popular_baseline(pool, counts),
    }
