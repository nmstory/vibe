"""Disk cache for the pipeline's HTTP calls.

Swaps pipeline.requests for a shim whose get() serves responses from disk,
fetching and saving them on a miss. Failed responses are cached too, so a run
replays exactly, and every call is logged so the harness can count errors.

Delete the cache folder to take a fresh sample from the APIs.
"""
from contextlib import contextmanager
from pathlib import Path
from unittest import mock
import hashlib
import json

import requests

import pipeline

DEFAULT_CACHE_DIR = Path(__file__).parent / "cache"


class CachedResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


class CachedRequests:
    def __init__(self, cache_dir, offline=False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.calls = []  # one record per get(): url, params, status_code, cached

    @staticmethod
    def key(url, params):
        # Param order doesn't matter, but order within a list (e.g. seeds) does
        normalised = json.dumps([url, sorted((params or {}).items())], sort_keys=True)
        return hashlib.sha256(normalised.encode('utf-8')).hexdigest()

    def get(self, url, params=None, **kwargs):
        path = self.cache_dir / f"{self.key(url, params)}.json"
        cached = path.exists()

        if cached:
            entry = json.loads(path.read_text(encoding='utf-8'))
        elif self.offline:
            raise RuntimeError(f"Cache miss in offline mode: {url} {params}")
        else:
            response = requests.get(url, params=params, **kwargs)
            entry = {
                'url': url,
                'params': params,
                'status_code': response.status_code,
                'text': response.text
            }
            path.write_text(json.dumps(entry, indent=2), encoding='utf-8')

        self.calls.append({
            'url': url,
            'params': params,
            'status_code': entry['status_code'],
            'cached': cached
        })
        return CachedResponse(entry['status_code'], entry['text'])


@contextmanager
def cached_pipeline(cache_dir=DEFAULT_CACHE_DIR, offline=False):
    """Within this block, pipeline's HTTP calls go through the disk cache.

    Yields the CachedRequests instance; read .calls for the call log.
    offline=True raises on a cache miss instead of hitting the network.
    """
    shim = CachedRequests(cache_dir, offline=offline)
    with mock.patch.object(pipeline, 'requests', shim):
        yield shim
