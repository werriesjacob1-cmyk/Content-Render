# Writer corpus fixtures

Real, historical **rejected** Writer V2.1 outputs, preserved verbatim from the
`quality-certification` GitHub Actions artifacts of the five flagship
certification runs. Every one of those runs failed at the Writer stage, so no
video was ever produced — these files are the only surviving record of what the
Writer actually emitted and why each round was rejected.

Purpose: evaluate Writer/prompt/gate changes **offline at $0**, instead of
spending a paid Gemini certification run each time.

## Provenance

| file | run id | flagship | head sha | topic |
|---|---|---|---|---|
| `flagship_02_2dbad04.json` | 34257803289 | #2 | `2dbad043…` | greenland_shark |
| `flagship_03_4b7584c.json` | 34263047438 | #3 | `4b7584c0…` | venus_day |
| `flagship_04_39275e3.json` | 34264652218 | #4 | `39275e38…` | venus_day |
| `flagship_05_240bdc1.json` | 34284331800 | #5 | `240bdc13…` | greenland_shark |

Flagship #1 (run 34256572142, sha `fa3bfc8e…`) produced **no** `writer_attempts.json`
— its artifact contains only a QA report saying the manifest was never written —
so there is no fixture for it.

`INDEX.json` summarizes each fixture (attempt and round counts).

## Rules

These are historical records, not test inputs to be tuned. **Do not edit, clean,
reformat, or trim a fixture to make a test pass.** If a test disagrees with a
fixture, the test or the pipeline is what changes. New fixtures may be added
from future runs; existing ones are append-only.
