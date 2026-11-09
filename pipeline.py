"""Playlist generation pipeline, independent of Flask.

Uses the ReccoBeats API (no key needed), which works in Spotify track IDs, so
it can be called directly (e.g. by an evaluation harness) without a user session.

A track is a dict: {'uri': str, 'name': str, 'artist': str, 'duration_ms': int}
(duration_ms may be missing on seeds from elsewhere; DEFAULT_TRACK_MS stands in)
"""
import math
import requests

RECCOBEATS_URL = "https://api.reccobeats.com/v1"

# ReccoBeats limits
MAX_SEEDS = 5
MAX_RECOMMENDATIONS = 100
MAX_AUDIO_FEATURE_IDS = 40

# Playlist shape
SIMILAR_PER_SEED = 5
MOOD_TRACKS = 10

# Fitting a playlist to a journey: the mood tracks get this share of the
# journey, the seed blocks the rest, and more mood tracks top it up if the
# seeds run out
MOOD_SHARE = 0.25
DEFAULT_TRACK_MS = 210_000  # 3.5 minutes, for a track with no known length

# Target audio features per mood, on Spotify's 0-1 scales.
# valence: how positive a track sounds, energy: how intense it feels
MOOD_TARGETS = {
    'happy':     {'valence': 0.85, 'energy': 0.75},
    'excited':   {'valence': 0.80, 'energy': 0.90},
    'energetic': {'valence': 0.65, 'energy': 0.90},
    'angry':     {'valence': 0.25, 'energy': 0.90},
    'romantic':  {'valence': 0.65, 'energy': 0.40},
    'nostalgic': {'valence': 0.50, 'energy': 0.45},
    'focused':   {'valence': 0.45, 'energy': 0.40},
    'calm':      {'valence': 0.55, 'energy': 0.25},
    'tired':     {'valence': 0.40, 'energy': 0.20},
    'sad':       {'valence': 0.20, 'energy': 0.30},
}


def generate_playlist_tracks(mood, seed_tracks, journey_minutes=None):
    """Build the track list for a playlist.

    mood: mood string, e.g. "happy" (see MOOD_TARGETS)
    seed_tracks: list of track dicts (normally the user's top tracks, best first)
    journey_minutes: length of the journey, or None for the full playlist

    Returns a list of track dicts: each seed followed by its similar tracks,
    then the mood recommendations. With journey_minutes, the playlist is cut
    to the journey: it stops at the first track that takes it past the
    journey's length, so the music doesn't run out before arrival.
    """
    if journey_minutes is None:
        track_list = []
        for track in seed_tracks:
            track_list.append(track)
            track_list.extend(get_similar_tracks(track))
        return track_list + recommendations_from_mood(mood, seed_tracks)

    target_ms = journey_minutes * 60_000

    # The whole ranked pool comes from one API call either way, so take all of
    # it and use as many as the journey needs
    mood_pool = recommendations_from_mood(mood, seed_tracks, limit=MAX_RECOMMENDATIONS)
    mood_tracks = take_until(mood_pool, target_ms * MOOD_SHARE)

    # Seed blocks in rank order, so only the seeds the journey needs cost a call
    seed_part = []
    for track in seed_tracks:
        if playlist_ms(seed_part) + playlist_ms(mood_tracks) >= target_ms:
            break
        seed_part.extend([track] + get_similar_tracks(track))
    seed_part = take_until(seed_part, target_ms - playlist_ms(mood_tracks))

    # Seeds ran out: top up with the next-best mood tracks
    mood_tracks = take_until(mood_pool, target_ms - playlist_ms(seed_part))

    return seed_part + mood_tracks


def track_ms(track):
    return track.get('duration_ms') or DEFAULT_TRACK_MS


def playlist_ms(tracks):
    return sum(track_ms(track) for track in tracks)


def take_until(tracks, budget_ms):
    # The shortest prefix of tracks whose length reaches budget_ms (or all of them)
    taken, total = [], 0
    for track in tracks:
        if total >= budget_ms:
            break
        taken.append(track)
        total += track_ms(track)
    return taken


def spotify_id(uri):
    # "spotify:track:<id>" -> "<id>"
    return uri.rsplit(':', 1)[-1]


def to_track(reccobeats_track):
    return {
        'uri': f"spotify:track:{reccobeats_track['href'].rsplit('/', 1)[-1]}",
        'name': reccobeats_track['trackTitle'],
        'artist': reccobeats_track['artists'][0]['name'],
        'duration_ms': reccobeats_track.get('durationMs')
    }


def get_recommendations(seed_tracks, size, **feature_params):
    params = {
        'seeds': [spotify_id(track['uri']) for track in seed_tracks[:MAX_SEEDS]],
        'size': min(size, MAX_RECOMMENDATIONS),
        **feature_params
    }

    response = requests.get(f"{RECCOBEATS_URL}/track/recommendation", params=params)

    # ReccoBeats returns 400 when none of the seeds are in its catalogue
    if response.status_code == 200:
        return [to_track(track) for track in response.json().get('content', [])]
    else:
        print(f"Error {response.status_code}: {response.text}")
        return []


def get_audio_features(tracks):
    # Returns {spotify uri: audio features}; tracks ReccoBeats doesn't know are left out
    features = {}

    for i in range(0, len(tracks), MAX_AUDIO_FEATURE_IDS):
        batch = tracks[i:i + MAX_AUDIO_FEATURE_IDS]
        params = {'ids': [spotify_id(track['uri']) for track in batch]}

        response = requests.get(f"{RECCOBEATS_URL}/audio-features", params=params)

        if response.status_code == 200:
            for item in response.json().get('content', []):
                features[f"spotify:track:{item['href'].rsplit('/', 1)[-1]}"] = item
        else:
            print(f"Error {response.status_code}: {response.text}")

    return features


def get_similar_tracks(track, limit=SIMILAR_PER_SEED):
    return get_recommendations([track], limit)


def recommendations_from_mood(mood, seed_tracks, limit=MOOD_TRACKS):
    if not seed_tracks:
        print("No seed tracks to base mood recommendations on.")
        return []

    target = MOOD_TARGETS.get(mood.strip().lower())

    if not target:
        print(f"Unknown mood: {mood}, returning unranked recommendations")
        return get_recommendations(seed_tracks, limit)

    # ReccoBeats' own feature params barely steer results, so fetch a wide pool
    # of candidates and rank them against the mood target ourselves
    candidates = get_recommendations(seed_tracks, MAX_RECOMMENDATIONS, **target)
    features = get_audio_features(candidates)

    def distance(track):
        track_features = features[track['uri']]
        return math.dist(
            [track_features[key] for key in target],
            [target[key] for key in target]
        )

    ranked = sorted((track for track in candidates if track['uri'] in features), key=distance)

    return ranked[:limit]
