"""Human rating sheet: build it from a run, then summarise the filled-in ratings.

Usage, from the project root:
    python -m harness.ratings sample [--run <run.json>] [--per-case 3] [--force]
    python -m harness.ratings summary

sample  writes harness/labels/sheet.csv (blank, for rating against RUBRIC.md)
        and harness/labels/sample.json (what each row is; kept out of the sheet
        so rating stays blind). Rows are shuffled, and the sheet includes:
          - control rows: a track deliberately far from the case's mood target,
            which should be rated low; checks the rater and the scale
          - repeat rows: copies of earlier rows, to measure rater consistency
summary checks the filled sheet, then reports rater consistency, whether the
        controls were rated low, and how well the automated mood_fit metric
        agrees with the human mood_fit ratings (Spearman rank correlation).
"""
from pathlib import Path
import argparse
import csv
import json
import math
import random

import pipeline
from harness.cache import cached_pipeline, DEFAULT_CACHE_DIR
from harness.metrics import generated_tracks
from harness.run import RUNS_DIR, load_testset

RATINGS_DIR = Path(__file__).parent / "labels"
SHEET_PATH = RATINGS_DIR / "sheet.csv"
SAMPLE_PATH = RATINGS_DIR / "sample.json"

SHEET_COLUMNS = ['id', 'mood', 'seeds', 'track', 'artist', 'listen', 'mood_fit', 'seed_fit', 'notes']
DIMENSIONS = ['mood_fit', 'seed_fit']
RANDOM_SEED = 2026  # fixed, so the same run always gives the same sheet


def latest_scored_run():
    for path in sorted(RUNS_DIR.glob("*.json"), reverse=True):
        if 'summary' in json.loads(path.read_text(encoding='utf-8')):
            return path
    raise SystemExit("No scored run found; run `python -m harness.run` first.")


def track_mood_fit(features, target):
    # Same formula as harness.metrics.mood_fit, for a single track
    distance = math.dist([features[key] for key in target], [target[key] for key in target])
    return 1 - distance / math.sqrt(len(target))


def build_sample(run, testset, features, per_case, control_share=0.1, repeat_share=0.06):
    rng = random.Random(RANDOM_SEED)
    targets = {mood['mood']: mood['target'] for mood in testset['moods']}
    all_tracks = {t['uri']: t for case in run['cases'] for t in generated_tracks(case)}

    items = []
    # Only moods with a target, and only full-length cases: journey cases are cut
    # from the same responses, so including them would weight each case 4 times
    cases = [case for case in run['cases']
             if targets[case['mood']] and case.get('journey_minutes') is None]

    for case in cases:
        unique = list({t['uri']: t for t in generated_tracks(case)}.values())
        for track in rng.sample(unique, min(per_case, len(unique))):
            items.append({'kind': 'sample', 'mood': case['mood'], 'seed_set': case['seed_set'],
                          'seeds': case['seeds'], 'track': track})

    # Controls: for a random subset of cases, the track from anywhere in the run
    # that is furthest from that case's mood target
    for case in rng.sample(cases, max(1, round(len(items) * control_share))):
        target = targets[case['mood']]
        in_case = {t['uri'] for t in generated_tracks(case)}
        candidates = [t for uri, t in all_tracks.items() if uri in features and uri not in in_case]
        worst = min(candidates, key=lambda t: track_mood_fit(features[t['uri']], target))
        items.append({'kind': 'control', 'mood': case['mood'], 'seed_set': case['seed_set'],
                      'seeds': case['seeds'], 'track': worst})

    # Repeats: copies of sampled rows, rated again later in the shuffled sheet
    originals = [item for item in items if item['kind'] == 'sample']
    repeats = [dict(item, kind='repeat') for item in rng.sample(originals, max(1, round(len(items) * repeat_share)))]

    rng.shuffle(items)
    # Put each repeat at least a third of the sheet after its original
    for repeat in repeats:
        original_index = next(i for i, item in enumerate(items)
                              if item['kind'] == 'sample' and item['track']['uri'] == repeat['track']['uri']
                              and item['mood'] == repeat['mood'] and item['seed_set'] == repeat['seed_set'])
        earliest = min(len(items), original_index + len(items) // 3)
        items.insert(rng.randint(earliest, len(items)), repeat)

    for number, item in enumerate(items, start=1):
        item['id'] = f"R{number:03d}"
    for repeat in repeats:
        repeat['repeat_of'] = next(item['id'] for item in items if item['kind'] == 'sample'
                                   and item['track']['uri'] == repeat['track']['uri']
                                   and item['mood'] == repeat['mood'] and item['seed_set'] == repeat['seed_set'])

    for item in items:
        uri = item['track']['uri']
        target = targets[item['mood']]
        item['auto_mood_fit'] = track_mood_fit(features[uri], target) if uri in features else None

    return items


def write_sheet(items):
    with SHEET_PATH.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for item in items:
            writer.writerow({
                'id': item['id'],
                'mood': item['mood'],
                'seeds': '; '.join(f"{s['name']} - {s['artist']}" for s in item['seeds']),
                'track': item['track']['name'],
                'artist': item['track']['artist'],
                'listen': f"https://open.spotify.com/track/{pipeline.spotify_id(item['track']['uri'])}",
                'mood_fit': '', 'seed_fit': '', 'notes': ''
            })


def sample_command(args):
    if SHEET_PATH.exists() and not args.force:
        raise SystemExit(f"{SHEET_PATH} already exists and may hold ratings. Use --force to overwrite it.")

    run_path = args.run or latest_scored_run()
    run = json.loads(Path(run_path).read_text(encoding='utf-8'))
    testset = load_testset()

    uris = sorted({t['uri'] for case in run['cases'] for t in generated_tracks(case)})
    with cached_pipeline(DEFAULT_CACHE_DIR):
        features = pipeline.get_audio_features([{'uri': uri} for uri in uris])

    items = build_sample(run, testset, features, args.per_case)

    RATINGS_DIR.mkdir(exist_ok=True)
    SAMPLE_PATH.write_text(json.dumps({'run': Path(run_path).name, 'random_seed': RANDOM_SEED,
                                       'per_case': args.per_case, 'items': items}, indent=2), encoding='utf-8')
    write_sheet(items)

    counts = {kind: sum(item['kind'] == kind for item in items) for kind in ('sample', 'control', 'repeat')}
    print(f"Wrote {SHEET_PATH.relative_to(RATINGS_DIR.parent.parent)}: {len(items)} rows "
          f"({counts['sample']} sampled, {counts['control']} controls, {counts['repeat']} repeats) "
          f"from {Path(run_path).name}")
    print(f"Rate them against {(RATINGS_DIR / 'RUBRIC.md').relative_to(RATINGS_DIR.parent.parent)}, "
          f"then run `python -m harness.ratings summary`.")


def ranks(values):
    # Average ranks, so tied ratings share a rank
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            result[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return result


def spearman(xs, ys):
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    var = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return cov / var if var else None


def read_ratings(sheet_path=None):
    # sheet_path: a different filled-in sheet with the same rows, e.g. an archived rubric version
    sheet_path = Path(sheet_path) if sheet_path else SHEET_PATH
    if not sheet_path.exists() or not SAMPLE_PATH.exists():
        raise SystemExit(f"No rating sheet at {sheet_path}; run `python -m harness.ratings sample` first.")

    items = {item['id']: item for item in json.loads(SAMPLE_PATH.read_text(encoding='utf-8'))['items']}
    problems = []
    ratings = {}

    with sheet_path.open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if row['id'] not in items:
                problems.append(f"{row['id']}: not in sample.json")
                continue
            ratings[row['id']] = {}
            for dim in DIMENSIONS:
                value = (row.get(dim) or '').strip()
                if not value:
                    continue
                if value not in {'1', '2', '3', '4', '5'}:
                    problems.append(f"{row['id']} {dim}: '{value}' is not 1-5")
                    continue
                ratings[row['id']][dim] = int(value)

    return items, ratings, problems


def mean(values):
    return sum(values) / len(values) if values else None


def fmt(value, digits=2):
    return '-' if value is None else f"{value:.{digits}f}"


def summary_command(args):
    items, ratings, problems = read_ratings(args.sheet)

    for problem in problems:
        print(f"Problem: {problem}")

    rated = {i: r for i, r in ratings.items() if r}
    print(f"Rated {len(rated)} of {len(items)} rows.\n")
    if not rated:
        return

    def scores(kind, dim):
        return [r[dim] for i, r in rated.items() if items[i]['kind'] == kind and dim in r]

    # 1. Rater consistency on repeated rows
    print("Rater consistency (repeat rows vs their originals)")
    for dim in DIMENSIONS:
        pairs = [(rated[i][dim], rated[items[i]['repeat_of']][dim]) for i in rated
                 if items[i]['kind'] == 'repeat' and dim in rated[i]
                 and dim in rated.get(items[i]['repeat_of'], {})]
        exact = mean([a == b for a, b in pairs])
        within_one = mean([abs(a - b) <= 1 for a, b in pairs])
        print(f"  {dim:<9} pairs={len(pairs):<3} exact={fmt(exact)} within 1 point={fmt(within_one)}")
    print()

    # 2. Controls should be rated lower than sampled rows
    print("Controls (tracks chosen to clash with the mood) vs sampled rows")
    for dim in DIMENSIONS:
        control, sample = scores('control', dim), scores('sample', dim)
        print(f"  {dim:<9} control mean={fmt(mean(control))} (n={len(control)})  "
              f"sampled mean={fmt(mean(sample))} (n={len(sample)})")
    print()

    # 3. Human ratings by mood and seed set (sampled rows only)
    for key in ('mood', 'seed_set'):
        print(f"Mean human rating by {key} (sampled rows)")
        groups = {}
        for i, r in rated.items():
            if items[i]['kind'] == 'sample':
                groups.setdefault(items[i][key], []).append(r)
        for name, rs in groups.items():
            print(f"  {name:<18}" + ''.join(f"{dim}={fmt(mean([r[dim] for r in rs if dim in r])):<6}" for dim in DIMENSIONS)
                  + f"n={len(rs)}")
        print()

    # 4. Does the automated metric agree with people?
    pairs = [(items[i]['auto_mood_fit'], r['mood_fit']) for i, r in rated.items()
             if items[i]['kind'] != 'repeat' and 'mood_fit' in r and items[i]['auto_mood_fit'] is not None]
    rho = spearman([a for a, _ in pairs], [h for _, h in pairs])
    print("Automated mood_fit vs human mood_fit")
    print(f"  Spearman rho={fmt(rho)} over n={len(pairs)} rows "
          f"(1 = same ordering, 0 = unrelated, below 0 = opposite)")

    seed_pairs = [(r['mood_fit'], r['seed_fit']) for i, r in rated.items()
                  if items[i]['kind'] != 'repeat' and 'mood_fit' in r and 'seed_fit' in r]
    print(f"  human mood_fit vs human seed_fit: rho={fmt(spearman(*zip(*seed_pairs)) if len(seed_pairs) >= 3 else None)} "
          f"(low means they measure different things)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)

    sample = commands.add_parser('sample', help="build a blank rating sheet from a run")
    sample.add_argument('--run', type=Path, help="run file to sample from (default: latest scored run)")
    sample.add_argument('--per-case', type=int, default=3, help="tracks sampled per case (default 3)")
    sample.add_argument('--force', action='store_true', help="overwrite an existing sheet")
    sample.set_defaults(func=sample_command)

    summary = commands.add_parser('summary', help="summarise the filled-in ratings")
    summary.add_argument('--sheet', type=Path, help="sheet to read (default: harness/labels/sheet.csv)")
    summary.set_defaults(func=summary_command)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
