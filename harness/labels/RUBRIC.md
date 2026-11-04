# Rating rubric

Version 2: adds example tracks (anchors) for 1, 3 and 5, and guidance on using the whole scale. Ratings made against version 1 are archived in `sheet_v1.csv`.

Rate each row of `sheet.csv` on two dimensions, 1–5. Listen with the link if you don't know the track; 20–30 seconds is enough.
Rate the **track on its own**: don't compare it to the other rows, and don't guess which part of the pipeline produced it.

## mood_fit: does this track suit the requested mood?

| Score | Meaning |
|---|---|
| 5 | Clearly this mood. You'd pick it for a playlist with that name |
| 4 | Fits well, with small reservations |
| 3 | Neutral or ambiguous. Neither fits nor clashes |
| 2 | Mostly doesn't fit |
| 1 | Clashes with the mood, e.g. an aggressive track for "calm" |

Anchors:

| Mood | 5 | 3 | 1 |
|---|---|---|---|
| calm | Banana Pancakes - Jack Johnson | Yellow - Coldplay (gentle, but builds to a big chorus) | Killing in the Name - Rage Against the Machine |
| happy | Happy - Pharrell Williams | Wonderwall - Oasis (upbeat, but wistful) | Hurt - Johnny Cash |

## seed_fit: would someone who likes the seed tracks enjoy this track?

| Score | Meaning |
|---|---|
| 5 | Same scene or sound as the seeds. An obvious recommendation |
| 4 | Adjacent genre or era. A plausible recommendation |
| 3 | Some connection, but a stretch |
| 2 | Weak connection |
| 1 | No connection, e.g. a children's song for hip-hop seeds |

Anchors, for the seeds *Back in Black - AC/DC* and *Smells Like Teen Spirit - Nirvana*:

| Score | Track |
|---|---|
| 5 | Enter Sandman - Metallica (same hard-rock scene and era) |
| 4 | Seven Nation Army - The White Stripes (riff-driven rock, a later era) |
| 3 | Billie Jean - Michael Jackson (a classic, but pop, not rock) |
| 1 | Baby Shark - Pinkfong |

## Using the scale

- Match each score to the anchors: a 5 should be as clear-cut as the 5 examples, and a 1 as clear a mismatch as the 1s.
- Use the whole scale. A typical, reasonable recommendation is a 3 or a 4; save 5 for standout picks, and use 1 and 2 when a track doesn't fit.
- Judge each dimension separately. A track can suit the mood perfectly and still be a poor fit for the seeds, or the other way round.

## Notes

- Rate only tracks you know or have listened to. If you can't judge a track's mood, leave `mood_fit` blank; rate `seed_fit` only if you know the artist well enough. Blanks aren't counted.
- Use `notes` for anything odd: wrong version, a duplicate, a live recording, a non-music track.
- Some rows are repeats or deliberate checks. Rate them like any other row.
- Save as **CSV UTF-8** if you edit in Excel.
