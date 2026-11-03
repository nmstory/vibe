# Rating rubric

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

## seed_fit: would someone who likes the seed tracks enjoy this track?

| Score | Meaning |
|---|---|
| 5 | Same scene or sound as the seeds. An obvious recommendation |
| 4 | Adjacent genre or era. A plausible recommendation |
| 3 | Some connection, but a stretch |
| 2 | Weak connection |
| 1 | No connection, e.g. a children's song for hip-hop seeds |

## Notes

- Leave a cell blank if you really can't judge it, for example if the track is unavailable. Blanks aren't counted.
- Use `notes` for anything odd: wrong version, a duplicate, a live recording, a non-music track.
- Some rows are repeats or deliberate checks. Rate them like any other row.
- Save as **CSV UTF-8** if you edit in Excel.
