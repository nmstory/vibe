"""Run the fixed test set through the pipeline, score it, and save the run.

Usage, from the project root:
    python -m harness.run                      # fetch on cache miss
    python -m harness.run --offline            # cached responses only; fail on a miss
    python -m harness.run --cases              # also print the per-case table
    python -m harness.run --baseline <run.json> # compare against a specific run
    python -m harness.run --baselines          # also score random and popular baselines
    python -m harness.run --cache-dir <dir>    # use another cache, e.g. empty for a fresh sample

Each run is compared against the previous saved run that used the same cache
(or --baseline). Cases are paired by (seed set, mood) and the change in each
metric gets a bootstrap 95% CI; a metric is only marked better or worse when
that CI excludes 0.
"""
from datetime import datetime
from pathlib import Path
import argparse
import json
import time

import pipeline
from harness.baselines import build_baselines
from harness.cache import cached_pipeline, DEFAULT_CACHE_DIR
from harness.metrics import METRICS, generated_tracks, score_case, mean_scores
from harness.stats import bootstrap_ci, compare_runs, overall_cis

HARNESS_DIR = Path(__file__).parent
PROJECT_DIR = HARNESS_DIR.parent
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
    'duration_fit': 'dur_fit',
}

# Metrics left out of the baseline table: equal to the pipeline's by
# construction (generated, fill), or undefined because baselines make no calls (err)
BASELINE_SKIP = {'generated', 'fill_rate', 'error_rate'}


def load_testset(path=TESTSET_PATH):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def run_testset(testset, http, generate=pipeline.generate_playlist_tracks):
    # generate(mood, seed_tracks) -> tracks: the pipeline, or a baseline
    cases = []

    for seed_set in testset['seed_sets']:
        for mood in testset['moods']:
            first_call = len(http.calls)
            start = time.perf_counter()

            tracks = generate(mood['mood'], seed_set['tracks'])

            cases.append({
                'seed_set': seed_set['name'],
                'mood': mood['mood'],
                'seeds': seed_set['tracks'],
                'tracks': tracks,
                'calls': http.calls[first_call:],
                'seconds': round(time.perf_counter() - start, 3)
            })

    return cases


def fetch_features(tracks):
    # Sorted so the batches, and so the cache keys, are stable between runs
    uris = sorted({t['uri'] for t in tracks})
    return pipeline.get_audio_features([{'uri': uri} for uri in uris])


def score_cases(testset, cases, features=None):
    targets = {mood['mood']: mood['target'] for mood in testset['moods']}

    # Fetch audio features once for every generated track, unless given
    if features is None:
        features = fetch_features([t for case in cases for t in generated_tracks(case)])

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
        'overall_ci': overall_cis(cases),
        'by_mood': group('mood'),
        'by_seed_set': group('seed_set'),
    }


def fmt(name, value):
    if value is None:
        return '-'
    return f"{value:.1f}" if name == 'generated' else f"{value:.2f}"


def fmt_ci(name, value, ci, sign=''):
    # e.g. "0.77 [0.75,0.79]", or with sign='+' "+0.17 [+0.15,+0.19]"
    if value is None:
        return '-'
    digits = 1 if name == 'generated' else 2
    text = f"{value:{sign}.{digits}f}"
    if ci:
        text += f" [{ci[0]:{sign}.{digits}f},{ci[1]:{sign}.{digits}f}]"
    return text


def print_table(title, rows, label_width=18):
    header = f"{title:<{label_width}}" + ''.join(f"{COLUMNS[name]:>9}" for name in METRICS)
    print(header)
    print('-' * len(header))
    for label, scores in rows.items():
        print(f"{label:<{label_width}}" + ''.join(f"{fmt(name, scores[name]):>9}" for name in METRICS))
    print()


def print_overall(summary, n_cases):
    # One row per metric: the mean with its bootstrap 95% CI
    print(f"OVERALL ({n_cases} cases)")
    header = f"{'metric':<20}{'mean [95% CI]':>22}"
    print(header)
    print('-' * len(header))
    for name in METRICS:
        ci = summary['overall_ci'][name]
        print(f"{name:<20}{fmt_ci(name, summary['overall'][name], ci):>22}")
    print()


def print_comparison(current_cases, baseline_run, baseline_name, testset_version):
    paired = baseline_run.get('testset_version') == testset_version
    if not paired:
        print(f"WARNING: test set version differs ({baseline_run.get('testset_version')} vs "
              f"{testset_version}); comparing unpaired.")
    rows, paired = compare_runs(baseline_run['cases'], current_cases, paired=paired)
    if not paired and baseline_run.get('testset_version') == testset_version:
        print("WARNING: the two runs' cases don't match by (seed set, mood); comparing unpaired.")

    how = "paired by case" if paired else "unpaired"
    print(f"Compared with {baseline_name} ({how}, bootstrap 95% CI of the change):")
    header = f"{'metric':<20}{'before':>9}{'after':>9}{'change [95% CI]':>24}"
    print(header)
    print('-' * len(header))
    for name, row in rows.items():
        change = fmt_ci(name, row['change'], row['ci'], sign='+')
        print(f"{name:<20}{fmt(name, row['before']):>9}{fmt(name, row['after']):>9}{change:>24}  {row['verdict']}")
    print()


def score_baselines(testset, cases, http):
    """Run and score each baseline over the same test set.

    Returns {name: {'summary': ..., 'cases': ...}}, plus the pool size.
    """
    pool, baselines = build_baselines(cases, http)
    # Features for the whole pool, in one stable set of batches, so every
    # baseline is covered and later runs replay from the cache
    features = fetch_features(pool)

    results = {}
    for name, generate in baselines.items():
        baseline_cases = run_testset(testset, http, generate)
        score_cases(testset, baseline_cases, features)
        results[name] = {'summary': summarise(baseline_cases), 'cases': baseline_cases}
    return results, len(pool)


def print_baselines(systems):
    """systems: {name: cases}, pipeline first. One row per system, each metric
    with its CI, then each system's paired lift over random."""
    names = [n for n in METRICS if n not in BASELINE_SKIP]
    width = 21

    def table(title, cells):
        header = f"{title:<10}" + ''.join(f"{COLUMNS[n]:>{width}}" for n in names)
        print(header)
        print('-' * len(header))
        for system, row in cells.items():
            print(f"{system:<10}" + ''.join(f"{row[n]:>{width}}" for n in names))
        print()

    scores = {}
    for system, cases in systems.items():
        values = {n: [c['scores'][n] for c in cases if c['scores'][n] is not None] for n in names}
        scores[system] = {
            n: fmt_ci(n, sum(v) / len(v) if v else None, bootstrap_ci(v)) for n, v in values.items()
        }
    table('system', scores)

    lifts = {}
    for system, cases in systems.items():
        if system == 'random':
            continue
        rows, _ = compare_runs(systems['random'], cases)
        lifts[system] = {n: fmt_ci(n, rows[n]['change'], rows[n]['ci'], sign='+') if n in rows else '-'
                         for n in names}
    table('vs random', lifts)

    # Mood fit by mood: does the system respond to mood at all?
    moods = list(dict.fromkeys(c['mood'] for c in next(iter(systems.values()))))
    header = f"{'mood_fit':<12}" + ''.join(f"{s:>10}" for s in systems)
    print(header)
    print('-' * len(header))
    for mood in moods:
        cells = []
        for cases in systems.values():
            values = [c['scores']['mood_fit'] for c in cases if c['mood'] == mood and c['scores']['mood_fit'] is not None]
            cells.append(f"{sum(values) / len(values):.2f}" if values else '-')
        print(f"{mood:<12}" + ''.join(f"{cell:>10}" for cell in cells))
    print()


def same_cache(run, cache_dir):
    # Runs saved before cache_dir was recorded used the default cache
    return run.get('cache_dir', DEFAULT_CACHE_DIR.relative_to(PROJECT_DIR).as_posix()) == cache_dir


def previous_run(exclude, cache_dir):
    # The latest earlier run on the same cache, i.e. the same API sample, so
    # differences come from the code rather than from sampling
    runs = sorted(p for p in RUNS_DIR.glob("*.json") if p != exclude)
    for path in reversed(runs):
        run = json.loads(path.read_text(encoding='utf-8'))
        if 'summary' in run and same_cache(run, cache_dir):  # skip runs saved before scoring existed
            return path, run
    return None, None


def display_path(path):
    path = Path(path).resolve()
    try:
        return path.relative_to(PROJECT_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--offline', action='store_true', help="use cached responses only")
    parser.add_argument('--cases', action='store_true', help="print the per-case score table")
    parser.add_argument('--baseline', type=Path, help="run file to compare against (default: previous run)")
    parser.add_argument('--baselines', action='store_true', help="also score the random and popular baselines")
    parser.add_argument('--cache-dir', type=Path, default=DEFAULT_CACHE_DIR,
                        help="response cache folder (default: harness/cache); an empty one draws a fresh sample")
    args = parser.parse_args()
    cache_dir = display_path(args.cache_dir)

    testset = load_testset()
    with cached_pipeline(args.cache_dir, offline=args.offline) as http:
        cases = run_testset(testset, http)
        score_cases(testset, cases)
        first_baseline_call = len(http.calls)
        baselines, pool_size = score_baselines(testset, cases, http) if args.baselines else (None, 0)
        baseline_calls = http.calls[first_baseline_call:]
    summary = summarise(cases)

    run = {
        'testset_version': testset['version'],
        'created': datetime.now().isoformat(timespec='seconds'),
        'pipeline': {'similar_per_seed': pipeline.SIMILAR_PER_SEED, 'mood_tracks': pipeline.MOOD_TRACKS},
        'cache_dir': cache_dir,
        'summary': summary,
        'cases': cases
    }
    if baselines:
        # Kept apart from 'summary' and 'cases', so a baseline is never
        # mistaken for the pipeline's previous run
        run['baselines'] = baselines

    RUNS_DIR.mkdir(exist_ok=True)
    run_path = RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    run_path.write_text(json.dumps(run, indent=2), encoding='utf-8')

    if args.cases:
        print_table('case', {f"{c['seed_set'][:10]}/{c['mood']}": c['scores'] for c in cases}, label_width=22)
    print_table('mood', summary['by_mood'])
    print_table('seed set', summary['by_seed_set'])
    print_overall(summary, len(cases))

    if args.baseline:
        baseline_path, baseline = args.baseline, json.loads(args.baseline.read_text(encoding='utf-8'))
    else:
        baseline_path, baseline = previous_run(exclude=run_path, cache_dir=cache_dir)
    if baseline:
        print_comparison(cases, baseline, baseline_path.name, testset['version'])

    if baselines:
        print(f"Baselines ({pool_size}-track candidate pool from this run's responses):")
        print_baselines({'pipeline': cases, **{name: b['cases'] for name, b in baselines.items()}})

    all_calls = [call for case in cases for call in case['calls']]
    print(f"{len(cases)} cases, {len(all_calls)} pipeline calls, "
          f"{sum(c['cached'] for c in all_calls)} from cache. Saved {run_path.relative_to(PROJECT_DIR)}")
    if baselines:
        print(f"Baselines: {len(baseline_calls)} calls (pool responses and audio features), "
              f"{sum(c['cached'] for c in baseline_calls)} from cache.")
    print("Columns: " + "; ".join(f"{COLUMNS[n]} = {desc}" for n, (desc, _) in METRICS.items()))


if __name__ == '__main__':
    main()
