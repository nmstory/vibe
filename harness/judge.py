"""LLM judge: rate the human rating sheet's rows with Claude, then measure how
far the judge can be trusted against the human ratings.

Usage, from the project root (needs ANTHROPIC_API_KEY in .env or the environment):
    python -m harness.judge run [--model claude-haiku-5-5] [--effort medium] [--attempts 1] [--limit N]
    python -m harness.judge run --dry-run      # print the prompt for one row; no API call
    python -m harness.judge report             # agreement with human ratings and other checks

The judge sees exactly what the human rater sees (mood, seed tracks, track and
artist; no audio features or automated scores) and is given the same rubric.
Results are saved per configuration in harness/labels/judge/, one call per
row and attempt; re-running only calls the API for rows not yet judged.

Agreement is reported separately on a tuning half and a test half of the
cases. Tune the judge prompt against the tuning half only; the test half is
the honest number.
"""
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json
import os

from dotenv import load_dotenv

from harness.ratings import (RATINGS_DIR, SAMPLE_PATH, DIMENSIONS, read_ratings,
                             spearman, mean, fmt)

JUDGE_DIR = RATINGS_DIR / "judge"
RUBRIC_PATH = RATINGS_DIR / "RUBRIC.md"

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_EFFORT = "medium"
PROMPT_VERSION = 1  # bump whenever the prompt below changes, so results stay comparable

# Per 1M tokens (input, output); for cost estimates only
PRICES = {
    'claude-opus-5-5': (4.00, 20.00),
    'claude-sonnet-5-5': (2.00, 10.00),
    'claude-haiku-5-5': (0.10, 0.50),
}

# Server-side refusal fallback is supported on these; Haiku 5.5 rejects it
FALLBACK_MODELS = {'claude-opus-5-5', 'claude-sonnet-5-5', 'claude-fable-5-1'}

SCORE = {"anyOf": [{"type": "integer", "enum": [1, 2, 3, 4, 5]}, {"type": "null"}]}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "known_track": {"type": "boolean"},
        "mood_fit": SCORE,
        "seed_fit": SCORE,
        "rationale": {"type": "string"},
    },
    "required": ["known_track", "mood_fit", "seed_fit", "rationale"],
    "additionalProperties": False,
}

JUDGE_INSTRUCTIONS = """You are rating tracks for a playlist evaluation, using the same rubric as the human raters.

Each request gives a requested mood, the listener's seed tracks (their taste), and one track to rate. Rate the track on its own, on both dimensions below, from 1 to 5.

{rubric}

Rules:
- Set known_track to true only if you know this specific recording well enough to judge how it sounds.
- If you don't know the track, don't guess from its title: set mood_fit to null. You may still rate seed_fit if you know the artist well enough to judge the fit with the seeds; otherwise set it to null too.
- rationale: one short sentence saying what the scores rest on."""


def rubric_dimensions():
    # The two dimension sections of the human rubric, without the human-only notes
    text = RUBRIC_PATH.read_text(encoding='utf-8')
    start = text.index("## mood_fit")
    end = text.index("## Notes")
    return text[start:end].strip()


def system_prompt():
    return JUDGE_INSTRUCTIONS.format(rubric=rubric_dimensions())


def user_prompt(item):
    seeds = "\n".join(f"- {s['name']} - {s['artist']}" for s in item['seeds'])
    return (f"Mood: {item['mood']}\n\n"
            f"Seed tracks (the listener's taste):\n{seeds}\n\n"
            f"Track to rate: {item['track']['name']} - {item['track']['artist']}")


def config_name(model, effort):
    return f"{model}_{effort}_v{PROMPT_VERSION}"


def results_path(model, effort):
    return JUDGE_DIR / f"{config_name(model, effort)}.json"


def load_results(path):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return None


def case_splits(items):
    # Split by case, not row, so near-identical rows (same mood and seeds) never
    # land on both sides. Cases are ordered by a hash, so the split is fixed but
    # unrelated to mood or seed set, and halved exactly
    cases = sorted({(item['mood'], item['seed_set']) for item in items},
                   key=lambda case: hashlib.sha256('|'.join(case).encode('utf-8')).hexdigest())
    half = len(cases) // 2
    return {case: 'tune' if index < half else 'test' for index, case in enumerate(cases)}


def split_of(item, splits):
    return splits[(item['mood'], item['seed_set'])]


def judge_row(client, model, effort, item):
    request = {
        'model': model,
        'max_tokens': 16000,
        'system': system_prompt(),
        'messages': [{'role': 'user', 'content': user_prompt(item)}],
        'output_config': {
            'effort': effort,
            'format': {'type': 'json_schema', 'schema': OUTPUT_SCHEMA},
        },
    }
    if model in FALLBACK_MODELS:
        request['betas'] = ['server-side-fallback-2026-07-01']
        request['fallbacks'] = 'default'

    response = client.beta.messages.create(**request)

    result = {
        'stop_reason': response.stop_reason,
        'served_by': response.model,
        'input_tokens': response.usage.input_tokens,
        'output_tokens': response.usage.output_tokens,
    }

    # A refusal (after any fallback) has no usable output; record it as unscored
    if response.stop_reason == 'refusal':
        return {**result, 'known_track': None, 'mood_fit': None, 'seed_fit': None, 'rationale': None}

    text = next(block.text for block in response.content if block.type == 'text')
    return {**result, **json.loads(text)}


def run_command(args):
    sample = json.loads(SAMPLE_PATH.read_text(encoding='utf-8'))
    items = sample['items'][:args.limit] if args.limit else sample['items']

    if args.dry_run:
        print("=== system ===\n" + system_prompt())
        print("\n=== user (first row) ===\n" + user_prompt(items[0]))
        print(f"\n{len(items)} rows x {args.attempts} attempts would be judged by {args.model} at effort {args.effort}.")
        return

    load_dotenv()
    if not (os.getenv('ANTHROPIC_API_KEY') or os.getenv('ANTHROPIC_AUTH_TOKEN')):
        raise SystemExit("No Anthropic credentials: set ANTHROPIC_API_KEY in .env (see README).")

    import anthropic  # imported here so --dry-run and report work without the SDK configured
    client = anthropic.Anthropic()

    path = results_path(args.model, args.effort)
    results = load_results(path) or {
        'model': args.model, 'effort': args.effort, 'prompt_version': PROMPT_VERSION,
        'sample_run': sample['run'], 'system_prompt': system_prompt(), 'rows': {}
    }
    if results['system_prompt'] != system_prompt():
        raise SystemExit(f"The prompt has changed since {path.name} was made. Bump PROMPT_VERSION.")

    JUDGE_DIR.mkdir(exist_ok=True)
    new_calls = 0
    for item in items:
        attempts = results['rows'].setdefault(item['id'], [])
        while len(attempts) < args.attempts:
            try:
                attempts.append(judge_row(client, args.model, args.effort, item))
            except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as e:
                # The SDK has already retried these; save progress and stop
                path.write_text(json.dumps(results, indent=2), encoding='utf-8')
                raise SystemExit(f"Stopped at {item['id']}: {e}. Progress saved; run again to continue.")
            new_calls += 1
            # Save after every call so an interrupted run loses nothing
            path.write_text(json.dumps(results, indent=2), encoding='utf-8')
            print(f"{item['id']} attempt {len(attempts)}: mood_fit={attempts[-1]['mood_fit']} "
                  f"seed_fit={attempts[-1]['seed_fit']} known={attempts[-1]['known_track']}")

    all_attempts = [a for rows in results['rows'].values() for a in rows]
    input_tokens = sum(a['input_tokens'] for a in all_attempts)
    output_tokens = sum(a['output_tokens'] for a in all_attempts)
    cost = None
    if args.model in PRICES:
        price_in, price_out = PRICES[args.model]
        cost = input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out
    print(f"\n{new_calls} new calls. {len(all_attempts)} judged in total: "
          f"{input_tokens} input / {output_tokens} output tokens"
          + (f", about ${cost:.2f} at list prices" if cost is not None and cost >= 0.01
             else f", about ${cost:.4f} at list prices" if cost is not None else "")
          + f". Saved {path}")


def weighted_kappa(xs, ys, categories=(1, 2, 3, 4, 5)):
    # Quadratic-weighted Cohen's kappa: agreement on an ordinal scale, corrected for
    # chance; near misses count as partial agreement
    if len(xs) < 2:
        return None
    k = len(categories)
    index = {c: i for i, c in enumerate(categories)}
    observed = [[0] * k for _ in range(k)]
    for x, y in zip(xs, ys):
        observed[index[x]][index[y]] += 1
    n = len(xs)
    row_totals = [sum(row) for row in observed]
    col_totals = [sum(observed[i][j] for i in range(k)) for j in range(k)]

    weight = lambda i, j: (i - j) ** 2 / (k - 1) ** 2
    disagreement = sum(weight(i, j) * observed[i][j] for i in range(k) for j in range(k))
    expected = sum(weight(i, j) * row_totals[i] * col_totals[j] / n for i in range(k) for j in range(k))
    return 1 - disagreement / expected if expected else None


def agreement(pairs):
    # pairs: (judge, human) scores on the same rows
    judge, human = [p[0] for p in pairs], [p[1] for p in pairs]
    return {
        'n': len(pairs),
        'exact': mean([a == b for a, b in pairs]),
        'within_1': mean([abs(a - b) <= 1 for a, b in pairs]),
        'spearman': spearman(judge, human),
        'kappa': weighted_kappa(judge, human),
        'bias': mean([a - b for a, b in pairs]),  # > 0: judge is more lenient
    }


def print_agreement(label, stats):
    print(f"  {label:<20} n={stats['n']:<4} exact={fmt(stats['exact'])} within1={fmt(stats['within_1'])} "
          f"rho={fmt(stats['spearman'])} kappa={fmt(stats['kappa'])} bias={fmt(stats['bias'])}")


def report_command(args):
    items, human, problems = read_ratings()
    for problem in problems:
        print(f"Problem in sheet.csv: {problem}")

    paths = sorted(JUDGE_DIR.glob("*.json")) if JUDGE_DIR.exists() else []
    if not paths:
        raise SystemExit("No judge results yet; run `python -m harness.judge run` first.")

    rated = {i: r for i, r in human.items() if r}
    splits = case_splits(items.values())
    print(f"Human ratings: {len(rated)} of {len(items)} rows rated. "
          f"Cases split {sum(s == 'tune' for s in splits.values())} tune / "
          f"{sum(s == 'test' for s in splits.values())} test.\n")

    for path in paths:
        results = json.loads(path.read_text(encoding='utf-8'))
        rows = results['rows']
        first = {i: attempts[0] for i, attempts in rows.items() if attempts and i in items}
        print(f"=== {path.stem}  ({len(first)} rows judged) ===")

        # Coverage: how often the judge abstains or refuses
        stops = Counter(a['stop_reason'] for a in first.values())
        unknown = sum(a['known_track'] is False for a in first.values())
        print(f"  unknown tracks={unknown}/{len(first)}  refusals={stops.get('refusal', 0)}  "
              f"fell back={sum(a['served_by'] != results['model'] for a in first.values())}")
        for dim in DIMENSIONS:
            scored = sum(a[dim] is not None for a in first.values())
            print(f"  {dim:<9} scored on {scored}/{len(first)} rows")
        print()

        # Agreement with the human ratings, by split; the test split is the headline
        for dim in DIMENSIONS:
            print(f"  Agreement with human {dim} (originals and controls; repeats excluded)")
            for split in ('test', 'tune'):
                pairs = [(a[dim], rated[i][dim]) for i, a in first.items()
                         if items[i]['kind'] != 'repeat' and split_of(items[i], splits) == split
                         and a[dim] is not None and dim in rated.get(i, {})]
                if pairs:
                    print_agreement(f"{split} split", agreement(pairs))
                else:
                    print(f"  {split + ' split':<20} no rows with both a judge and a human score")

            # The ceiling: how well the human agrees with themself on repeat rows
            human_pairs = [(rated[i][dim], rated[items[i]['repeat_of']][dim]) for i in rated
                           if items[i]['kind'] == 'repeat' and dim in rated[i]
                           and dim in rated.get(items[i]['repeat_of'], {})]
            if human_pairs:
                print_agreement("human vs self", agreement(human_pairs))
            print()

        # Checks that need no human ratings
        print("  Checks without human ratings")
        for dim in DIMENSIONS:
            control = [a[dim] for i, a in first.items() if items[i]['kind'] == 'control' and a[dim] is not None]
            sample = [a[dim] for i, a in first.items() if items[i]['kind'] == 'sample' and a[dim] is not None]
            print(f"  {dim:<9} control mean={fmt(mean(control))} (n={len(control)})  "
                  f"sampled mean={fmt(mean(sample))} (n={len(sample)})")

        auto = [(items[i]['auto_mood_fit'], a['mood_fit']) for i, a in first.items()
                if items[i]['kind'] != 'repeat' and a['mood_fit'] is not None
                and items[i]['auto_mood_fit'] is not None]
        if len(auto) >= 3:
            print(f"  judge mood_fit vs automated mood_fit: rho={fmt(spearman(*zip(*auto)))} (n={len(auto)})")

        # Self-consistency: repeat rows vs their originals, and extra attempts
        for dim in DIMENSIONS:
            pairs = [(first[i][dim], first[items[i]['repeat_of']][dim]) for i in first
                     if items[i]['kind'] == 'repeat' and items[i]['repeat_of'] in first
                     and first[i][dim] is not None and first[items[i]['repeat_of']][dim] is not None]
            multi = [(attempts[0][dim], attempts[k][dim]) for attempts in rows.values()
                     for k in range(1, len(attempts))
                     if attempts[0][dim] is not None and attempts[k][dim] is not None]
            pairs += multi
            if pairs:
                print(f"  {dim:<9} self-consistency: exact={fmt(mean([a == b for a, b in pairs]))} "
                      f"within1={fmt(mean([abs(a - b) <= 1 for a, b in pairs]))} (pairs={len(pairs)})")
        print()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)

    run = commands.add_parser('run', help="judge the rating sheet's rows")
    run.add_argument('--model', default=DEFAULT_MODEL)
    run.add_argument('--effort', default=DEFAULT_EFFORT, choices=['low', 'medium', 'high', 'xhigh', 'max'])
    run.add_argument('--attempts', type=int, default=1, help="judgements per row, to measure consistency")
    run.add_argument('--limit', type=int, help="only the first N rows of the sheet")
    run.add_argument('--dry-run', action='store_true', help="print the prompt; make no API calls")
    run.set_defaults(func=run_command)

    report = commands.add_parser('report', help="agreement with human ratings and other checks")
    report.set_defaults(func=report_command)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
