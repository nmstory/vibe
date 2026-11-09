import contextlib
import io
import unittest
from unittest import mock

import pipeline


def response(status, data=None, text=""):
    r = mock.Mock(status_code=status, text=text)
    r.json.return_value = data
    return r


TRACK_MS = 200_000  # every fake ReccoBeats track lasts 3m20s


def reccobeats_track(spotify_id, title, artist):
    return {'id': f"uuid-{spotify_id}", 'trackTitle': title, 'artists': [{'name': artist}],
            'durationMs': TRACK_MS, 'href': f"https://open.spotify.com/track/{spotify_id}"}


# A fake catalogue: C0 = (0, 0) ... C20 = (1, 1) in valence/energy; C17 has no audio features
POOL = {f"C{i}": (i / 20, i / 20) for i in range(21)}


def fake_get(url, params=None, **kwargs):
    """Stands in for ReccoBeats, enforcing its limits."""
    if url.endswith('/track/recommendation'):
        seeds = params['seeds']
        assert 1 <= len(seeds) <= pipeline.MAX_SEEDS, seeds
        assert params['size'] <= pipeline.MAX_RECOMMENDATIONS
        if seeds == ['Missing']:
            return response(400, text='{"error":"Cannot find any track for given seed ids"}')
        if params['size'] == pipeline.MAX_RECOMMENDATIONS:  # the mood candidate pool
            return response(200, {'content': [reccobeats_track(s, s, f"Art{s}") for s in POOL]})
        return response(200, {'content': [reccobeats_track(f"{seeds[0]}-sim{i}", f"{seeds[0]} sim {i}", 'SimArtist')
                                          for i in range(params['size'])]})
    if url.endswith('/audio-features'):
        assert len(params['ids']) <= pipeline.MAX_AUDIO_FEATURE_IDS
        return response(200, {'content': [
            {'href': f"https://open.spotify.com/track/{s}", 'valence': POOL[s][0], 'energy': POOL[s][1]}
            for s in params['ids'] if s in POOL and s != 'C17']})
    raise AssertionError(f"unexpected GET {url}")


SEEDS = [{'uri': 'spotify:track:SeedA', 'name': 'SeedA', 'artist': 'ArtistA'},
         {'uri': 'spotify:track:Missing', 'name': 'Missing', 'artist': 'ArtistB'}]


class GeneratePlaylistTracksTest(unittest.TestCase):
    def generate(self, mood, seeds, journey_minutes=None):
        # The pipeline prints API problems; keep test output clean
        with mock.patch.object(pipeline.requests, 'get', side_effect=fake_get) as get, \
                contextlib.redirect_stdout(io.StringIO()):
            tracks = pipeline.generate_playlist_tracks(mood, seeds, journey_minutes)
        self.calls = [call.kwargs['params'] for call in get.call_args_list]
        return tracks

    def test_each_seed_is_followed_by_its_similar_tracks(self):
        tracks = self.generate('happy', SEEDS)
        self.assertEqual(tracks[0], SEEDS[0])
        self.assertEqual([t['uri'] for t in tracks[1:6]], [f"spotify:track:SeedA-sim{i}" for i in range(5)])

    def test_seed_missing_from_catalogue_gets_no_similar_tracks(self):
        tracks = self.generate('happy', SEEDS)
        self.assertEqual(tracks[6], SEEDS[1])
        self.assertEqual(len(tracks), 7 + pipeline.MOOD_TRACKS)

    def test_mood_tracks_ranked_nearest_first(self):
        mood_tracks = self.generate(' Happy ', SEEDS)[7:]  # mood is trimmed and case-insensitive
        names = [t['name'] for t in mood_tracks]
        # happy target (0.85, 0.75): C16 then C15, then C14 and C18, which are equidistant
        self.assertEqual(names[:2], ['C16', 'C15'])
        self.assertEqual(set(names[2:4]), {'C14', 'C18'})
        self.assertNotIn('C17', names)  # no audio features, so can't be ranked

    def test_tracks_have_uri_name_artist_and_length(self):
        for t in self.generate('happy', SEEDS)[7:]:  # past the seed blocks: ReccoBeats tracks
            self.assertEqual(set(t), {'uri', 'name', 'artist', 'duration_ms'})
            self.assertEqual(t['duration_ms'], TRACK_MS)

    def test_no_seeds_gives_no_tracks(self):
        self.assertEqual(self.generate('happy', []), [])

    def test_unknown_mood_falls_back_to_unranked(self):
        with mock.patch.object(pipeline.requests, 'get', side_effect=fake_get), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(len(pipeline.recommendations_from_mood('jubilant', SEEDS)), pipeline.MOOD_TRACKS)



class JourneyLengthTest(unittest.TestCase):
    generate = GeneratePlaylistTracksTest.generate

    def assert_covers_journey(self, tracks, journey_minutes):
        # Long enough for the journey, and the last track is the one that gets it there
        journey_ms = journey_minutes * 60_000
        self.assertGreaterEqual(pipeline.playlist_ms(tracks), journey_ms)
        self.assertLess(pipeline.playlist_ms(tracks[:-1]), journey_ms)

    def test_short_journey_is_cut_to_length(self):
        tracks = self.generate('happy', SEEDS, journey_minutes=20)
        self.assert_covers_journey(tracks, 20)
        # SeedA (no length, so the 3.5-minute default) with 3 of its similar
        # tracks, then the 2 best mood tracks for a quarter of the journey
        self.assertEqual([t['name'] for t in tracks],
                         ['SeedA', 'SeedA sim 0', 'SeedA sim 1', 'SeedA sim 2', 'C16', 'C15'])

    def test_only_seeds_the_journey_needs_are_looked_up(self):
        self.generate('happy', SEEDS, journey_minutes=20)
        similar_calls = [c for c in self.calls if 'seeds' in c and c['size'] == pipeline.SIMILAR_PER_SEED]
        self.assertEqual([c['seeds'] for c in similar_calls], [['SeedA']])

    def test_mood_tracks_top_up_when_seeds_run_out(self):
        tracks = self.generate('happy', SEEDS, journey_minutes=60)
        self.assert_covers_journey(tracks, 60)
        self.assertEqual(tracks[:7], self.generate('happy', SEEDS)[:7])  # both seed blocks in full
        mood_names = [t['name'] for t in tracks[7:]]
        self.assertGreater(len(mood_names), pipeline.MOOD_TRACKS)
        self.assertEqual(mood_names[:2], ['C16', 'C15'])  # still nearest first

    def test_journey_longer_than_everything_available_uses_it_all(self):
        tracks = self.generate('happy', SEEDS, journey_minutes=600)
        # 7 seed-block tracks plus the 20 mood candidates with audio features
        self.assertEqual(len(tracks), 7 + 20)

    def test_no_seeds_gives_no_tracks(self):
        self.assertEqual(self.generate('happy', [], journey_minutes=20), [])


if __name__ == '__main__':
    unittest.main()
