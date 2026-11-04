import argparse
import contextlib
import io
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import anthropic

from harness import judge
from harness.tests.test_ratings import write_sheet

ITEMS = json.loads(judge.SAMPLE_PATH.read_text(encoding='utf-8'))['items']


class FakeClient:
    """Stands in for anthropic.Anthropic: records requests, returns canned judgements."""
    def __init__(self, refuse=False):
        self.requests = []
        self.refuse = refuse
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        usage = types.SimpleNamespace(input_tokens=1000, output_tokens=200)
        if self.refuse:
            return types.SimpleNamespace(stop_reason='refusal', model=request['model'], content=[], usage=usage)
        body = {'known_track': True, 'mood_fit': 3, 'seed_fit': 2, 'rationale': 'test'}
        return types.SimpleNamespace(stop_reason='end_turn', model=request['model'], usage=usage,
                                     content=[types.SimpleNamespace(type='thinking', thinking=''),
                                              types.SimpleNamespace(type='text', text=json.dumps(body))])


class JudgeRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Results go to a temporary folder; no real credentials or API calls
        for patch in (mock.patch.object(judge, 'JUDGE_DIR', Path(self.tmp.name)),
                      mock.patch.object(judge, 'load_dotenv', lambda: None),
                      mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test'})):
            patch.start()
            self.addCleanup(patch.stop)

    def run_judge(self, client, **options):
        args = argparse.Namespace(**{'model': judge.DEFAULT_MODEL, 'effort': judge.DEFAULT_EFFORT,
                                     'attempts': 1, 'limit': 3, 'dry_run': False, **options})
        with mock.patch.object(anthropic, 'Anthropic', return_value=client), \
                contextlib.redirect_stdout(io.StringIO()):
            judge.run_command(args)
        return json.loads(judge.results_path(args.model, args.effort).read_text(encoding='utf-8'))

    def test_request_shape(self):
        client = FakeClient()
        self.run_judge(client, model='claude-opus-5-5')
        request = client.requests[0]
        self.assertEqual(request['output_config']['format']['type'], 'json_schema')
        self.assertEqual(request['output_config']['effort'], judge.DEFAULT_EFFORT)
        self.assertEqual(request['fallbacks'], 'default')
        self.assertEqual(request['betas'], ['server-side-fallback-2026-07-01'])

    def test_judge_sees_only_what_the_rater_sees(self):
        client = FakeClient()
        self.run_judge(client)
        prompt = client.requests[0]['messages'][0]['content']
        self.assertIn(ITEMS[0]['track']['name'], prompt)
        for hidden in ('valence', 'energy', 'auto_mood_fit', ITEMS[0]['kind']):
            self.assertNotIn(hidden, prompt)

    def test_no_fallbacks_for_haiku(self):
        client = FakeClient()
        self.run_judge(client, model='claude-haiku-5-5')
        self.assertNotIn('fallbacks', client.requests[0])
        self.assertNotIn('betas', client.requests[0])

    def test_rerun_resumes_and_attempts_add_calls(self):
        client = FakeClient()
        results = self.run_judge(client)
        self.assertEqual(len(results['rows']), 3)
        self.run_judge(client)
        self.assertEqual(len(client.requests), 3)  # nothing new to judge
        self.run_judge(client, attempts=2)
        self.assertEqual(len(client.requests), 6)

    def test_refusal_recorded_as_unscored(self):
        results = self.run_judge(FakeClient(refuse=True), limit=1)
        row = results['rows'][ITEMS[0]['id']][0]
        self.assertEqual(row['stop_reason'], 'refusal')
        self.assertIsNone(row['mood_fit'])

    def test_changed_prompt_without_version_bump_is_refused(self):
        self.run_judge(FakeClient(), limit=1)
        with mock.patch.object(judge, 'JUDGE_INSTRUCTIONS', judge.JUDGE_INSTRUCTIONS + " Changed."):
            with self.assertRaises(SystemExit) as raised:
                self.run_judge(FakeClient(), limit=1)
        self.assertIn('Bump PROMPT_VERSION', str(raised.exception))

    def test_report_runs_against_a_sheet(self):
        self.run_judge(FakeClient(), limit=None)
        sheet = Path(self.tmp.name) / 'sheet.csv'
        write_sheet(sheet, {item['id']: ('3', '2') for item in ITEMS})  # agrees with the fake judge
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            judge.report_command(argparse.Namespace(sheet=sheet))
        self.assertIn('105 rows judged', out.getvalue())
        self.assertIn('exact=1.00', out.getvalue())


class SplitTest(unittest.TestCase):
    def test_balanced_stable_split_by_case(self):
        splits = judge.case_splits(ITEMS)
        self.assertEqual(len(splits), len({(i['mood'], i['seed_set']) for i in ITEMS}))
        self.assertEqual(judge.case_splits(list(reversed(ITEMS))), splits)
        self.assertEqual(sorted(splits.values()).count('tune'), len(splits) // 2)


class WeightedKappaTest(unittest.TestCase):
    def test_perfect_and_opposite(self):
        self.assertAlmostEqual(judge.weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]), 1)
        self.assertAlmostEqual(judge.weighted_kappa([1, 1, 5, 5], [5, 5, 1, 1]), -1)

    def test_near_misses_beat_far_misses(self):
        near = judge.weighted_kappa([1, 2, 3, 4, 5], [2, 3, 4, 5, 4])
        far = judge.weighted_kappa([1, 2, 3, 4, 5], [5, 1, 5, 1, 1])
        self.assertGreater(near, far)


if __name__ == '__main__':
    unittest.main()
