import contextlib
import io
import unittest
from unittest import mock

import pipeline


def response(status, data=None, text=""):
    r = mock.Mock(status_code=status, text=text)
    r.json.return_value = data
    return r


def reccobeats_track(spotify_id, title, artist):
    return {'id': f"uuid-{spotify_id}", 'trackTitle': title, 'artists': [{'name': artist}],
            'href': f"https://open.spotify.com/track/{spotify_id}"}


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
    def generate(self, mood, seeds):
        # The pipeline prints API problems; keep test output clean
        with mock.patch.object(pipeline.requests, 'get', side_effect=fake_get), \
                contextlib.redirect_stdout(io.StringIO()):
            return pipeline.generate_playlist_tracks(mood, seeds)

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

    def test_tracks_have_uri_name_and_artist(self):
        for t in self.generate('happy', SEEDS):
            self.assertEqual(set(t), {'uri', 'name', 'artist'})

    def test_no_seeds_gives_no_tracks(self):
        self.assertEqual(self.generate('happy', []), [])

    def test_unknown_mood_falls_back_to_unranked(self):
        with mock.patch.object(pipeline.requests, 'get', side_effect=fake_get), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(len(pipeline.recommendations_from_mood('jubilant', SEEDS)), pipeline.MOOD_TRACKS)


if __name__ == '__main__':
    unittest.main()
