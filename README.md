# vibe

Welcome to Project Vibe: your go-to Spotify playlist generator before heading out on a drive!

**Vibe will only ask you to input:**

1. Your starting location
2. Your desired destination
3. Your current mood

**And from this, will curate a unique playlist for your journey based on factors such as:**

* The length of your journey, and how that matches to the way you feel (_daunted at a long drive?_).
* The weather in both your departure and arrival destinations (_arriving to a destination with better or worse weather?_).
* The time of day (_is the sun about to set as you drive?_).
* Music that's popular in the local area of your destination, that also matches your taste.
* Your current heavy rotation of music.

## Inspiration for the Name

Whilst the aim of this project is to accurately curate a Spotify playlist to set the perfect _vibe_ for your ride, I'm also currently learning Portuguese, and this is also an acronym for the slightly more Brazilian phrase **_v_**_amos_ **_i_**_ntensificar o_ **_b_**_om_ **_e_**_squema_, which roughly translate as slang to English as _let's get this vibe right_.

# Prerequisites

## Frameworks:
- Python (version: 3.13.2)
- Flask (version: 3.1.0)
- python-dotenv (version: 1.0.1)
- requests (version: 2.32.3)
- googlemaps (version: 4.10.0)
- anthropic (version: 2.4.0), used only by the evaluation harness's LLM judge

_Installable from the project root with:_
```
pip install -r requirements.txt
```

If pip reports an `externally-managed-environment` error (common on Debian/Ubuntu), create and activate a virtual environment first:
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## API Keys and .env
The implementation of vibe makes use of three API's: [Spotify](https://developer.spotify.com/), [Google Cloud](https://cloud.google.com/apis) and [ReccoBeats](https://reccobeats.com/docs/documentation/introduction) (track recommendations and audio features, no key needed).

For you to get vibe working locally, you'll need to personally generate your own API keys, then place them into a .env at the root of the project:
_/.env_
```
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
GOOGLE_MAPS_API_KEY=
FLASK_SECRET_KEY=
ANTHROPIC_API_KEY=
```

`ANTHROPIC_API_KEY` is only needed to run the evaluation harness's LLM judge ([Claude API](https://platform.claude.com/)); the app itself doesn't use it.

## Spotify Authentication Flow

To increase security within the desired environment (eventually potentially a web app), the [Spotify authentication flow](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow) uses an authorisation code with PKCE - in the event that the runtime environment may provide an opportunity for the authorisation code to be intercepted.

Follows this flow:

1. Code Challenge generation from a Code Verifier
2. Request authorisation from the user and retrieve the authorisation code
3. Request an access token from the authorisation code
4. Use the access token to make API calls

# Evaluation harness

A playlist isn't right or wrong; it's better or worse, along several dimensions at once. The harness in `harness/` treats vibe's recommendations as a system to evaluate: a fixed test set, repeatable runs, graded automated metrics, blind human ratings, and an LLM judge, with each automated scorer trusted only as far as it agrees with the human ratings.

## How it works

```
harness/testset.json ──► pipeline.generate_playlist_tracks(mood, seeds)   (pipeline.py, no Flask)
                                  │  HTTP calls replayed by harness/cache.py
                                  ▼
                         harness/run.py ──► metrics per case ──► score tables + diff vs previous run
                                  │                                   saved to harness/runs/
                                  ▼
                         harness/ratings.py sample ──► harness/labels/sheet.csv (blind, rated by a person)
                                                       harness/ratings.py summary ──► rater consistency,
                                                                                      human vs metric agreement
                                                       harness/judge.py run ──► same rows rated by Claude
                                                       harness/judge.py report ──► judge vs human agreement
```

- **Pipeline:** `pipeline.py` holds playlist generation with no session or request dependency, so the harness calls it directly. It uses [ReccoBeats](https://reccobeats.com/docs/documentation/introduction) for similar tracks and audio features, and ranks mood recommendations by distance to a valence/energy target.
- **Test set:** `harness/testset.json` has 11 moods × 3 seed sets (upbeat pop/rock, mellow acoustic, hip-hop) = 33 cases. One mood, "jubilant", is deliberately unknown to the pipeline, to exercise its fallback. Mood targets here are the scoring yardstick and are kept separate from the pipeline's own, so tuning the pipeline can't move the goalposts.
- **Cache:** ReccoBeats returns different results on every call. `harness/cache.py` stores every response, including failures, in `harness/cache/`, so the first run fixes the sample and later runs replay it exactly. To draw a fresh sample, point `--cache-dir` at an empty folder, or delete the default one.
- **Regression runs:** every run is saved and compared with the previous run on the same cache, i.e. the same API sample, so a difference comes from the code, not the sampling. Cases are paired by (seed set, mood), and the mean per-case change gets a bootstrap 95% CI. A metric is marked better, WORSE, or changed (for metrics with no better direction) only when that CI excludes 0; otherwise it's "no clear change". If the two runs' test set versions or cases differ, the comparison warns and falls back to an unpaired bootstrap.
- **Uncertainty:** each overall mean is shown with a bootstrap 95% CI (2,000 resamples of the cases, fixed seed, so output is reproducible; `harness/stats.py`, standard library only). The CIs are also saved in the run's `summary.overall_ci`.
- **Baselines:** `harness/baselines.py` holds two reference systems with the pipeline's own interface, `generate(mood, seed_tracks)`, so they're scored by exactly the same metrics. Both draw from a **candidate pool**: every track in the run's recommendation responses (the similar tracks plus the full 100-candidate mood pools), recovered from the cache.
  - **random:** for each case, as many tracks as the pipeline generated, sampled uniformly from the pool without replacement (fixed seed).
  - **popular:** the pool's most popular tracks by ReccoBeats `popularity` (0–100), ignoring mood and seeds: "just play the hits". The pipeline drops this field; the baseline reads it from the cached responses, where every one of the 2,724 items carries it as an integer, with no track ever given two different values.

  Baseline results are saved under the run's `baselines` key, separate from `summary` and `cases`, so a baseline is never taken as the previous run.

## Metrics

All scores are 0–1 and are computed over **generated tracks only**; the seed tracks the pipeline copies into the playlist are excluded.

| Metric | Measures | Better |
|---|---|---|
| `fill` | tracks returned ÷ tracks requested (silent loss from the API) | higher |
| `feat` | generated tracks with audio features, i.e. scorable for mood | higher |
| `err` | failed API calls ÷ API calls | lower |
| `dup` | 1 − unique tracks ÷ generated | lower |
| `artists` | unique primary artists ÷ generated | higher |
| `seed` | generated tracks that are a seed track | lower |
| `seed_art` | generated tracks by a seed artist | (a product choice) |
| `mood_fit` | 1 − mean valence/energy distance to the mood target ÷ √2 | higher |

## Human ratings

`mood_fit` is a proxy: it only sees two audio features, and it can't tell whether a track suits the listener's taste. So a person rates a fixed sample against [`harness/labels/RUBRIC.md`](harness/labels/RUBRIC.md), on two 1–5 dimensions:

- **`mood_fit`:** does the track suit the mood?
- **`seed_fit`:** would someone who likes the seed tracks enjoy it?

The sheet is built to make the ratings themselves checkable:

- **Blind:** rows are shuffled, and nothing on the sheet shows automated scores or which rows are special. That's kept in `harness/labels/sample.json`.
- **Controls (~10%):** tracks picked to clash with the case's mood. If they aren't rated low, the rater or the scale has a problem.
- **Repeats (~6%):** earlier rows shown again later in the sheet, to measure the rater's own consistency.

The summary then reports Spearman rank correlation between the automated `mood_fit` and the human ratings.

## LLM judge

Human ratings are the most trustworthy scorer, but they don't scale: when the pipeline changes, its new tracks have no ratings. `harness/judge.py` has Claude rate the same rows, so that if it agrees with people well enough, it can score runs nobody has rated.

- **Same instrument as the human:** the judge gets the rubric's two dimensions and sees only what the rater sees (mood, seed tracks, track and artist), with no audio features or automated scores, so it can't simply echo the metric.
- **Fixed output:** structured outputs constrain each reply to `{known_track, mood_fit, seed_fit, rationale}`, where scores are 1–5 or null.
- **Abstains instead of guessing:** for a track it doesn't know, it leaves `mood_fit` empty rather than guessing from the title. How often it abstains is reported, because a judge that only scores well-known tracks has a blind spot.
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) at effort `medium` by default, with the API's server-side refusal fallback enabled. `--model` and `--effort` select others (e.g. `claude-haiku-5-5`, `claude-sonnet-5-5`, effort `low`); Haiku doesn't support the fallback, so it's left off there. Each configuration's results are kept separately, so judges can be compared on agreement, coverage and cost.
- **Versioned and cached:** results are saved in `harness/labels/judge/<model>_<effort>_v<prompt version>.json` after every call. Re-running only judges rows that aren't done yet, and changing the prompt without bumping `PROMPT_VERSION` is refused, so old and new results are never mixed.

`python -m harness.judge report` measures whether the judge can be trusted:

- **Agreement with the human,** per dimension: exact and within-1-point agreement, Spearman ρ, quadratic-weighted Cohen's κ, and bias (mean judge − human; positive means more lenient).
- **Tune/test split:** cases are split 15/15 by a fixed hash, by case rather than row, so near-identical rows never fall on both sides. Change the judge prompt only while looking at the tune split; the test split is the honest number.
- **The ceiling:** the human's agreement with themself on repeat rows, shown alongside. A judge can't be expected to agree with someone better than they agree with themself.
- **Checks that need no human ratings:** whether controls get lower scores than sampled rows, how the judge's `mood_fit` correlates with the automated metric, and self-consistency on repeat rows (and across `--attempts N` runs, since these models no longer take a temperature setting).

## Running it

From the project root, with the virtual environment set up (on Windows, use `.venv\Scripts\python` in place of `python`):

1. **Run and score the test set:** the first run calls the API (about a minute); later runs replay from the cache.
   ```
   python -m harness.run
   ```
   Options:
   - `--cases` prints the per-case table.
   - `--offline` fails on a cache miss rather than calling the API.
   - `--baseline harness/runs/<file>.json` compares with a specific run.
   - `--baselines` also scores the random and popular baselines. It prints one row per system with each metric's CI, each system's paired lift over random, and `mood_fit` by mood. The first time, it fetches audio features for the candidate pool (about 30 calls); after that it works with `--offline`.
   - `--cache-dir <dir>` uses another response cache (default `harness/cache/`).
   **To check the noise floor (A/A test)** after changing how the harness samples or scores, draw a fresh API sample with the same code, and compare it with an existing run. Any metric marked as changed here is flagging sampling noise, not a code change.
   ```
   python -m harness.run --cache-dir harness/cache_aa --baseline harness/runs/<run on harness/cache>.json
   ```
2. **Build a rating sheet** from the latest run. It won't overwrite a sheet that may already hold ratings without `--force`.
   ```
   python -m harness.ratings sample
   ```
3. **Rate** `harness/labels/sheet.csv` against the rubric. If you use Excel, save as *CSV UTF-8*.
4. **Summarise the ratings:**
   ```
   python -m harness.ratings summary
   ```
5. **Run the LLM judge** on the same sheet (needs `ANTHROPIC_API_KEY`). `--dry-run` prints the exact prompt without calling the API, and `--limit 5` tries a few rows first. Measured on 5 rows, a full 105-row pass costs about $0.03 on Haiku 5.5, $0.33 on Sonnet 5.5 and $1.10 on Opus 5.5 at list prices; each run prints its actual token usage.
   ```
   python -m harness.judge run --dry-run
   python -m harness.judge run --limit 5
   python -m harness.judge run
   ```
6. **Check the judge against the human ratings:**
   ```
   python -m harness.judge report
   ```
   Both `report` and `python -m harness.ratings summary` take `--sheet` to read another sheet with the same rows. For example, to reproduce the pilot figures below from the archived rubric-v1 ratings:
   ```
   python -m harness.judge report --sheet harness/labels/sheet_v1.csv
   ```
   The report covers every judge results file, and each file's name records its rubric version (`_v1`, `_v2`). Compare each sheet only with the judge files of the same rubric version.
7. **Change the recommendation logic** in `pipeline.py`, then run step 1 again. The comparison table shows which metrics moved, in which direction, and whether the change is clear of the noise.
8. **Run the unit tests.** They need no API keys, make no network or API calls, and leave the real sheet, labels and judge results untouched:
   ```
   python -m unittest discover -s harness/tests -t .
   ```
   They cover:
   - **metrics:** seed exclusion, every metric's arithmetic, and undefined values in means;
   - **pipeline:** track order, catalogue misses, mood ranking and its fallbacks, against a fake ReccoBeats;
   - **stats:** bootstrap CIs, paired comparison and the "no clear change" verdict;
   - **baselines:** determinism, track counts and seed placement;
   - **ratings:** sheet validation, Spearman, and refusing to overwrite a sheet;
   - **judge:** request shape, blindness, resuming, refusals, the prompt-version guard, the tune/test split, weighted κ, and the report, against a fake Anthropic client.

## Findings so far

Baseline (33 cases): `mood_fit` 0.77 [0.74, 0.80], `fill` 0.93 [0.90, 0.95], `artists` 0.99 [0.99, 1.00], no duplicates, no errors.

- **Mood barely changes the playlist.** `mood_fit` only ranges 0.71–0.82 across moods. About 60% of each playlist is similar-to-seed tracks, which ignore mood and are the same for every mood. Dropping them raised `mood_fit` from 0.77 to 0.87.
- **The `mood_fit` scale is compressed.** An unrelated track still scores around 0.6, and a random track from the candidate pool scores 0.69 (see below). So 0.77 is a lift of only about 0.08 over chance.
- **The API under-delivers silently.** Asking for 5 similar tracks returns 3–4, and some tracks aren't in the catalogue at all. `fill` makes this visible.
- **Some failures don't affect any metric yet.** Off-genre picks, such as reggaeton for The Killers seeds, aren't caught by any automated score. That's what `seed_fit` and the LLM judge are for.

### Baselines: pipeline vs random vs popular

Same 33 cases, same metrics, 1,151-track candidate pool. Lift is the paired mean difference from random, with its 95% CI:

| | `mood_fit` | lift over random | `artists` | lift over random | `seed_art` |
|---|---|---|---|---|---|
| pipeline | 0.77 [0.74, 0.80] | **+0.08 [+0.05, +0.10]** | 0.99 [0.99, 1.00] | +0.00 [−0.01, +0.01] | 0.02 |
| random | 0.69 [0.68, 0.71] | – | 0.99 [0.98, 0.99] | – | 0.00 |
| popular | 0.71 [0.69, 0.73] | +0.02 [−0.00, +0.03] | 0.96 [0.96, 0.96] | **−0.03 [−0.04, −0.02]** | 0.05 |

- **The pipeline clearly beats random on mood**, but by only 0.08, because ~60% of each playlist ignores mood. The mood-ranked tracks carry the whole lift.
- **Random scores 0.69, not ~0.6.** The pool isn't random music: it comes from the seeds' neighbourhood plus mood-steered requests, so it already sits near the middle of the valence/energy space. 0.69 is the honest floor for this metric.
- **"Just play the hits" does no better than random on mood** (its CI touches 0) and has the lowest artist diversity, since the top of the pool repeats some artists (Playboi Carti twice in the top 21). Its `mood_fit` still varies by mood (0.64–0.80) even though its tracks never change. That variation is the target moving, not the playlist.
- **`mood_fit` favours mid-range targets.** Popular nearly matches the pipeline on nostalgic (0.79 vs 0.82) and focused (0.78 vs 0.80), whose targets sit near the centre, and loses clearly on happy and excited (0.66 vs 0.78; 0.64 vs 0.76). The pipeline's real advantage is on the extreme moods.
- **Seed duplicates under another URI slip through `seed`.** Popular includes a different release of "Mr. Brightside", which is a seed, and so does one pipeline case. `seed_overlap` matches URIs, so it scores 0 for both.

### A/A check: the noise floor

A fresh API sample (an empty `--cache-dir`, same code), compared with the baseline run, paired by case:

| Metric | Change [95% CI] | Verdict |
|---|---|---|
| `generated` | +0.3 [−0.5, +1.2] | no clear change |
| `fill` | +0.01 [−0.02, +0.05] | no clear change |
| `artists` | +0.00 [−0.00, +0.01] | no clear change |
| `mood_fit` | −0.00 [−0.01, +0.00] | no clear change |
| `seed_art` | −0.02 [−0.02, −0.01] | **changed** (a false alarm) |
| `feat`, `err`, `dup`, `seed` | 0 in both samples | no clear change |

- **8 of 9 metrics pass.** The noise floor on `mood_fit` is about ±0.005 between samples, so a pipeline change worth 0.01 is detectable. `fill` needs a change of about 0.035, and `generated` about 1 track.
- **The `seed_art` false alarm comes from cases that aren't independent.** The pipeline asks for each seed's similar tracks once, and all 11 moods of that seed set share the response, through the cache and in a live run alike. In the old sample, one Drake track in a hip-hop similar-tracks response appeared in all 11 hip-hop cases, and the bootstrap counted it as 11 independent observations. The effective sample size for anything driven by similar tracks is closer to 9 seeds than 33 cases, so **CIs on `seed_art`, `artists` and `fill` are too narrow.** `mood_fit` is less affected, because the mood pool is fetched per case. With 3 seed sets, clustering the bootstrap by seed set isn't usable; the fix is more seed sets.

### Judge pilot (44 human-rated rows, one rater, quick ratings)

| | Haiku 5.5 | Opus 5.5 |
|---|---|---|
| Cost, 105 rows | $0.03 | $1.03 |
| Tracks not known | 58 / 105 | 49 / 105 |
| Controls vs sampled, judge `mood_fit` | 1.80 vs 3.02 | 1.50 vs 3.02 |
| `mood_fit` vs human: ρ / κ / bias | 0.17 / 0.04 / −1.82 | 0.30 / 0.07 / −1.81 |
| `seed_fit` vs human: ρ / κ / bias | 0.14 / 0.03 / −1.91 | 0.18 / 0.06 / −1.74 |

- **Neither judge can stand in for the human ratings yet:** agreement is close to chance for both.
- **A stronger model helped only a little.** Opus knew more tracks and separated the controls better, but kept the same ~1.8-point gap. So the problem is the scale, not the model.
- **The human ratings have problems too.** 65% of `mood_fit` scores were 5, and the 2 controls averaged 4.0, so quick ratings barely used the bottom of the scale. The judges put most `seed_fit` scores at 2.

### Rubric v2: anchored scale

The rubric now gives example tracks for 1, 3 and 5 on each dimension, and guidance on using the whole scale. None of the anchor tracks or artists appear on the sheet, and the seed-fit anchors use a made-up rock seed set, so the examples don't leak answers. The v1 ratings are archived in `harness/labels/sheet_v1.csv`, and judge results are versioned (`_v1` / `_v2`), so the two rubric versions are never mixed.

Opus 5.5 on rubric v2 ($1.25 for 105 rows):

| | Rubric v1 | Rubric v2 |
|---|---|---|
| Tracks not known | 49 | 46 |
| Controls vs sampled, `mood_fit` | 1.50 vs 3.02 | 1.33 vs 2.96 |
| `seed_fit` scored 2 | 55 of 101 | 58 of 101 |
| ρ with the v1 human ratings (`mood_fit` / `seed_fit`)* | 0.30 / 0.18 | 0.41 / 0.31 |

\* Comparing the v2 judge with ratings made against v1 mixes rubric versions, so these figures are only indicative.

- **The anchors barely moved the judge.** It ranks tracks slightly more like the human and separates the controls a little better, but its score levels hardly changed. Its harsh `seed_fit` may be correct: many picks are further from the seeds than the "3" anchor (Billie Jean for rock seeds).
- **The anchors are mainly a fix for the human ratings,** which were the lenient side. The real test is re-rating the same 44 rows against rubric v2, then comparing the two. **Not done yet:** `sheet.csv` is blank, waiting for v2 ratings.
- **If agreement is still low after that,** switch to pairwise comparisons, which don't depend on how each rater uses the scale.

## Next

- Re-rate the 44 pilot rows against rubric v2, then compare the human v1 vs v2 ratings and judge–human agreement on the test split. If agreement is still low, switch to pairwise comparisons.
- A second rater, so agreement between people can be measured, not just one rater's consistency with themself.
- Compare judges (Opus 5.5 vs Sonnet 5.5 vs Haiku 5.5, and effort levels) on agreement per dollar.
- More seed sets, so the bootstrap can be clustered by seed set and the similar-track metrics get honest CIs.
- A per-case random baseline (only the pipeline's own candidates for that case, unranked), to isolate what the mood ranking adds.
- Reusing human ratings across runs, keyed by mood, seed set and track, so regression runs report a human score with its coverage.
