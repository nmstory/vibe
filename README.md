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
- **Cache:** ReccoBeats returns different results on every call. `harness/cache.py` stores every response, including failures, in `harness/cache/`, so the first run fixes the sample and later runs replay it exactly. Delete the folder to draw a fresh sample.
- **Regression runs:** every run is saved and compared with the previous one, with each metric marked better, worse or changed.

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
- **Model:** Claude Haiku 5.5 (`claude-haiku-5-5`) at effort `medium` by default. On the first 5 rows it gave seed-fit scores close to Opus 5.5 and Sonnet 5.5 at about 1/40th of Opus's cost, but it recognised fewer tracks (it abstained on 3 of 5, against 2 for Opus). `--model` and `--effort` select others (e.g. `claude-opus-5-5`, `claude-sonnet-5-5`, effort `low`); for Opus and Sonnet the API's server-side refusal fallback is enabled, which Haiku doesn't support. Each configuration's results are kept separately, so judges can be compared on agreement, coverage and cost once human ratings exist.
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
   Add `--cases` for the per-case table, `--offline` to fail rather than call the API on a cache miss, or `--baseline harness/runs/<file>.json` to compare with a specific run.
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
7. **Change the recommendation logic** in `pipeline.py`, then run step 1 again. The comparison table shows which metrics moved and in which direction.

## Findings so far

Baseline (33 cases): `mood_fit` 0.77, `fill` 0.93, `artists` 0.99, no duplicates, no errors.

- **Mood barely changes the playlist.** `mood_fit` only ranges 0.71–0.82 across moods. About 60% of each playlist is similar-to-seed tracks, which ignore mood and are the same for every mood. Dropping them raised `mood_fit` from 0.77 to 0.87.
- **The `mood_fit` scale is compressed.** An unrelated track still scores around 0.6, so the score needs a random-track baseline before 0.77 means much.
- **The API under-delivers silently.** Asking for 5 similar tracks returns 3–4, and some tracks aren't in the catalogue at all. `fill` makes this visible.
- **Some failures don't affect any metric yet.** Off-genre picks, such as reggaeton for The Killers seeds, aren't caught by any automated score. That's what `seed_fit` and the LLM judge are for.

## Next

- Human ratings and a first judge pass, then report judge–human agreement on the test split.
- Compare judges (Opus 5.5 vs Sonnet 5.5 vs Haiku 5.5, and effort levels) on agreement per dollar.
- Bootstrap confidence intervals on run comparisons, and random/popular baselines to give `mood_fit` context.
- Reusing human ratings across runs, keyed by mood, seed set and track, so regression runs report a human score with its coverage.
