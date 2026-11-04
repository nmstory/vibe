"""Bootstrap confidence intervals for run scores and run comparisons.

The test set is small (33 cases) and ReccoBeats samples randomly, so a mean
moves a little between runs even when the code doesn't change. Each mean gets
a 95% interval from resampling the cases, and a comparison only calls a
metric better or worse when the interval for the change excludes 0.

Standard library only; the RNG seed is fixed so the output is reproducible.
"""
import random

from harness.metrics import METRICS

RESAMPLES = 2000
LEVEL = 0.95
RNG_SEED = 0


def mean(values):
    return sum(values) / len(values)


def percentile_interval(means, level=LEVEL):
    means = sorted(means)
    tail = (1 - level) / 2
    return means[int(tail * len(means))], means[int((1 - tail) * len(means)) - 1]


def bootstrap_ci(values, resamples=RESAMPLES, seed=RNG_SEED, level=LEVEL):
    """95% CI of the mean of values, resampling with replacement.

    None values are skipped, as mean_scores does. Returns (low, high), or None
    if there are no values.
    """
    values = [v for v in values if v is not None]
    if not values:
        return None

    rng = random.Random(seed)  # fresh per call, so each CI is reproducible on its own
    n = len(values)
    means = [mean(rng.choices(values, k=n)) for _ in range(resamples)]
    return percentile_interval(means, level)


def unpaired_diff_ci(before, after, resamples=RESAMPLES, seed=RNG_SEED, level=LEVEL):
    # CI of mean(after) - mean(before), resampling each run on its own
    before = [v for v in before if v is not None]
    after = [v for v in after if v is not None]
    if not before or not after:
        return None

    rng = random.Random(seed)
    diffs = [
        mean(rng.choices(after, k=len(after))) - mean(rng.choices(before, k=len(before)))
        for _ in range(resamples)
    ]
    return percentile_interval(diffs, level)


def case_key(case):
    return case['seed_set'], case['mood']


def match_cases(before_cases, after_cases):
    """Pair up cases by (seed_set, mood): [(before, after), ...], or None if
    the two runs don't hold exactly the same cases."""
    before = {case_key(c): c for c in before_cases}
    after = {case_key(c): c for c in after_cases}

    duplicated = len(before) != len(before_cases) or len(after) != len(after_cases)
    if duplicated or before.keys() != after.keys():
        return None
    return [(before[key], after[key]) for key in sorted(before)]


def paired_diffs(pairs, name):
    # Per-case after - before, over the cases where both runs define the metric
    return [
        a['scores'][name] - b['scores'][name]
        for b, a in pairs
        if a['scores'][name] is not None and b['scores'][name] is not None
    ]


def verdict(ci, better):
    """'better' / 'WORSE' / 'changed' only when the CI of the change excludes 0."""
    if ci is None:
        return ''
    low, high = ci
    if low <= 0 <= high:
        return 'no clear change'
    if better is None:
        return 'changed'
    improved = low > 0 if better == 'higher' else high < 0
    return 'better' if improved else 'WORSE'


def compare_runs(before_cases, after_cases, paired=True):
    """Change in each metric's mean from before to after, with its CI.

    paired=True matches cases by (seed_set, mood) and bootstraps the mean of
    the per-case differences; it falls back to unpaired if the cases don't
    match. Returns (rows, paired_used) where rows is
    {metric: {before, after, change, ci, verdict}}.
    """
    pairs = match_cases(before_cases, after_cases) if paired else None
    rows = {}

    for name, (_, better) in METRICS.items():
        before = [c['scores'][name] for c in before_cases if c['scores'][name] is not None]
        after = [c['scores'][name] for c in after_cases if c['scores'][name] is not None]
        if not before or not after:
            continue

        if pairs is not None:
            diffs = paired_diffs(pairs, name)
            if not diffs:
                continue
            change, ci = mean(diffs), bootstrap_ci(diffs)
        else:
            change, ci = mean(after) - mean(before), unpaired_diff_ci(before, after)

        rows[name] = {
            'before': mean(before),
            'after': mean(after),
            'change': change,
            'ci': ci,
            'verdict': verdict(ci, better),
        }

    return rows, pairs is not None


def overall_cis(cases):
    # {metric: [low, high] or None}, for the run JSON summary
    cis = {}
    for name in METRICS:
        ci = bootstrap_ci([c['scores'][name] for c in cases])
        cis[name] = list(ci) if ci else None
    return cis
