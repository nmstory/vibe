"""Run the fixed test set through the pipeline, score it, and save the run.

Usage, from the project root:
    python -m harness.run                      # fetch on cache miss
    python -m harness.run --offline            # cached responses only; fail on a miss
    python -m harness.run --cases              # also print the per-case table
    python -m harness.run --baseline <run.json> # compare against a specific run

Each run is compared against the previous saved run (or --baseline), so a
change to the recommendation logic shows up as better or worse per metric.
"""
from datetime import datetime
from pathlib import Path
import argparse
import json
import time

import pipeline
from harness.cache import cached_pipeline, DEFAULT_CACHE_DIR
from harness.metrics import METRICS, generated_tracks, score_case, mean_scores

HARNESS_DIR = Path(__file__).parent
TESTSET_PATH = HARNESS_DIR / "testset.json"
RUNS_DIR = HARNESS_DIR / "runs"

# Short column headings for the score tables
COLUMNS = {
    'generated': 'gen',
    'fill_rate': 'fill',
    'feature_coverage': 'feat',
    'error_rate': 'err',
    'duplicate_rate': 'dup',
    'artist_diversity': 'artists',
    'seed_overlap': 'seed',
    'seed_artist_share': 'seed_art',
    'mood_fit': 'mood_fit',
}


def load_testset(path=TESTSET_PATH):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def run_testset(testset, http):
    cases = []

    for seed_set in testset['seed_sets']:
        for mood in testset['moods']:
            first_call = len(http.calls)
            start = time.perf_counter()

            tracks = pipeline.generate_playlist_tracks(mood['mood'], seed_set['tracks'])

            cases.append({
                'seed_set': seed_set['name'],
                'mood': mood['mood'],
                'seeds': seed_set['tracks'],
                'tracks': tracks,
                'calls': http.calls[first_call:],
                'seconds': round(time.perf_counter() - start, 3)
            })

    return cases


def score_cases(testset, cases):
    targets = {mood['mood']: mood['target'] for mood in testset['moods']}

    # Fetch audio features once for every generated track; sorted so the
    # batches, and so the cache keys, are stable between runs
    uris = sorted({t['uri'] for case in cases for t in generated_tracks(case)})
    features = pipeline.get_audio_features([{'uri': uri} for uri in uris])

    for case in cases:
        requested = len(case['seeds']) * pipeline.SIMILAR_PER_SEED + pipeline.MOOD_TRACKS
        case['scores'] = score_case(case, features, targets[case['mood']], requested)


def summarise(cases):
    def group(key):
        groups = {}
        for case in cases:
            groups.setdefault(case[key], []).append(case['scores'])
        return {name: mean_scores(scores) for name, scores in groups.items()}

    return {
        'overall': mean_scores([case['scores'] for case in cases]),
        'by_mood': group('mood'),
        'by_seed_set': group('seed_set'),
    }


def fmt(name, value):
    if value is None:
        return '-'
    return f"{value:.1f}" if name == 'generated' else f"{value:.2f}"


def print_table(title, rows, label_width=18):
    header = f"{title:<{label_width}}" + ''.join(f"{COLUMNS[name]:>9}" for name in METRICS)
    print(header)
    print('-' * len(header))
    for label, scores in rows.items():
        print(f"{label:<{label_width}}" + ''.join(f"{fmt(name, scores[name]):>9}" for name in METRICS))
    print()


def print_comparison(current, baseline, baseline_name):
    print(f"Compared with {baseline_name}:")
    header = f"{'metric':<20}{'before':>9}{'after':>9}{'change':>9}"
    print(header)
    print('-' * len(header))

    for name, (_, better) in METRICS.items():
        before, after = baseline.get(name), current[name]
        if before is None or after is None:
            continue
        change = after - before
        if abs(change) < 0.005:
            verdict = ''
        elif better is None:
            verdict = 'changed'
        else:
            improved = change > 0 if better == 'higher' else change < 0
            verdict = 'better' if improved else 'WORSE'
        print(f"{name:<20}{fmt(name, before):>9}{fmt(name, after):>9}{change:>+9.2f}  {verdict}")
    print()


def previous_run(exclude):
    runs = sorted(p for p in RUNS_DIR.glob("*.json") if p != exclude)
    for path in reversed(runs):
        run = json.loads(path.read_text(encoding='utf-8'))
        if 'summary' in run:  # skip runs saved before scoring existed
            return path, run
    return None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--offline', action='store_true', help="use cached responses only")
    parser.add_argument('--cases', action='store_true', help="print the per-case score table")
    parser.add_argument('--baseline', type=Path, help="run file to compare against (default: previous run)")
    args = parser.parse_args()

    testset = load_testset()
    with cached_pipeline(DEFAULT_CACHE_DIR, offline=args.offline) as http:
        cases = run_testset(testset, http)
        score_cases(testset, cases)
    summary = summarise(cases)

    RUNS_DIR.mkdir(exist_ok=True)
    run_path = RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    run_path.write_text(json.dumps({
        'testset_version': testset['version'],
        'created': datetime.now().isoformat(timespec='seconds'),
        'pipeline': {'similar_per_seed': pipeline.SIMILAR_PER_SEED, 'mood_tracks': pipeline.MOOD_TRACKS},
        'summary': summary,
        'cases': cases
    }, indent=2), encoding='utf-8')

    if args.cases:
        print_table('case', {f"{c['seed_set'][:10]}/{c['mood']}": c['scores'] for c in cases}, label_width=22)
    print_table('mood', summary['by_mood'])
    print_table('seed set', summary['by_seed_set'])
    print_table('OVERALL', {'all cases': summary['overall']})

    if args.baseline:
        baseline_path, baseline = args.baseline, json.loads(args.baseline.read_text(encoding='utf-8'))
    else:
        baseline_path, baseline = previous_run(exclude=run_path)
    if baseline:
        print_comparison(summary['overall'], baseline['summary']['overall'], baseline_path.name)

    all_calls = [call for case in cases for call in case['calls']]
    print(f"{len(cases)} cases, {len(all_calls)} pipeline calls, "
          f"{sum(c['cached'] for c in all_calls)} from cache. Saved {run_path.relative_to(HARNESS_DIR.parent)}")
    print("Columns: " + "; ".join(f"{COLUMNS[n]} = {desc}" for n, (desc, _) in METRICS.items()))


if __name__ == '__main__':
    main()
