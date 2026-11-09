"""Automated metrics for one test case.

Every metric is a graded score, not pass/fail. Seed tracks are excluded:
metrics are computed over the generated tracks only, i.e. the playlist minus
the user's own top tracks. duration_fit is the exception: it measures the
whole playlist, seeds included, since every track plays on the journey.

Each metric records which direction is better, so runs can be compared.
"""
import math

# name: (description, better) where better is 'higher', 'lower' or None (no preferred direction)
METRICS = {
    'generated':        ("tracks generated (seeds excluded)",                 None),
    'fill_rate':        ("generated / tracks requested (full-length cases only)", 'higher'),
    'feature_coverage': ("generated tracks with audio features (scorable)",   'higher'),
    'error_rate':       ("failed API calls / API calls",                      'lower'),
    'duplicate_rate':   ("1 - unique tracks / generated",                     'lower'),
    'artist_diversity': ("unique primary artists / generated",                'higher'),
    'seed_overlap':     ("generated tracks that are a seed track",            'lower'),
    'seed_artist_share':("generated tracks by a seed artist",                 None),
    'mood_fit':         ("1 - mean valence/energy distance to target / sqrt(2)", 'higher'),
    'duration_fit':     ("shorter / longer of playlist and journey length",   'higher'),
}


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def generated_tracks(case):
    # The pipeline puts each seed in the playlist; drop those exact positions,
    # but keep any later re-recommendation of a seed so seed_overlap can see it
    remaining_seeds = [seed['uri'] for seed in case['seeds']]
    generated = []

    for track in case['tracks']:
        if track['uri'] in remaining_seeds:
            remaining_seeds.remove(track['uri'])
        else:
            generated.append(track)

    return generated


def mood_fit(tracks, features, target):
    if not target:
        return None

    distances = [
        math.dist([features[t['uri']][key] for key in target], [target[key] for key in target])
        for t in tracks if t['uri'] in features
    ]
    if not distances:
        return None

    max_distance = math.sqrt(len(target))  # features are on 0-1 scales
    return 1 - (sum(distances) / len(distances)) / max_distance


def duration_fit(tracks, journey_minutes):
    # 1 when the playlist lasts exactly the journey; 0.5 when it's half or double
    if journey_minutes is None or not tracks:
        return None
    if any(t.get('duration_ms') is None for t in tracks):
        return None  # can't measure the playlist's length

    playlist_ms = sum(t['duration_ms'] for t in tracks)
    journey_ms = journey_minutes * 60_000
    return min(playlist_ms, journey_ms) / max(playlist_ms, journey_ms)


def score_case(case, features, target, requested):
    """case: a run case (seeds, tracks, calls, journey_minutes); features: {uri:
    audio features}; target: the test set's mood target or None; requested:
    tracks asked for, or None when the playlist is cut to a journey."""
    tracks = generated_tracks(case)
    seed_uris = {seed['uri'] for seed in case['seeds']}
    seed_artists = {seed['artist'] for seed in case['seeds']}
    calls = case['calls']

    return {
        'generated': len(tracks),
        'fill_rate': ratio(len(tracks), requested),
        'feature_coverage': ratio(sum(t['uri'] in features for t in tracks), len(tracks)),
        'error_rate': ratio(sum(call['status_code'] != 200 for call in calls), len(calls)),
        'duplicate_rate': 1 - ratio(len({t['uri'] for t in tracks}), len(tracks)) if tracks else None,
        'artist_diversity': ratio(len({t['artist'] for t in tracks}), len(tracks)),
        'seed_overlap': ratio(sum(t['uri'] in seed_uris for t in tracks), len(tracks)),
        'seed_artist_share': ratio(sum(t['artist'] in seed_artists for t in tracks), len(tracks)),
        'mood_fit': mood_fit(tracks, features, target),
        'duration_fit': duration_fit(case['tracks'], case.get('journey_minutes')),
    }


def mean_scores(scores):
    # Average each metric over the cases where it is defined
    means = {}
    for name in METRICS:
        values = [s[name] for s in scores if s[name] is not None]
        means[name] = sum(values) / len(values) if values else None
    return means
