# Legacy -> V2.1 deterministic gate matrix

- controls: **12** real August renders, narration byte-for-byte as committed
- reach today's quality scorer: **12/12**
- short-mode bounds: {'word_hard': [68, 108], 'word_target': [78, 98], 'scenes': [5, 8], 'scene_word_cap': 25, 'hook_words': [4, 16]}
- long-mode bounds: {'word_hard': [85, 115], 'word_target': [95, 110], 'scenes': [7, 10], 'scene_word_cap': 25, 'hook_words': [4, 16]}

| video | stored score | words | scenes | passes under | reaches scorer | blocking gate (short / long) |
|---|---|---|---|---|---|---|
| 2026-08-03_the-metal-that-remembers-its-shape | 8.29 | 94 | 7 | short, long | YES | PASS / PASS |
| 2026-08-13_your-fingerprints-aren-t-in-your-ge | 8.14 | 102 | 8 | short, long | YES | PASS / PASS |
| 2026-08-14_spiders-out-eat-all-of-us | 8.14 | 104 | 7 | short, long | YES | PASS / PASS |
| 2026-08-07_part-1-the-solid-that-is-secretly-a | 8.0 | 91 | 7 | short, long | YES | PASS / PASS |
| 2026-08-07_how-machines-learn-your-brain-code | 8.0 | 94 | 7 | short, long | YES | PASS / PASS |
| 2026-08-08_the-flammable-ocean-floor | 8.0 | 93 | 8 | short, long | YES | PASS / PASS |
| 2026-08-16_light-that-doesn-t-move | 7.86 | 103 | 7 | short, long | YES | PASS / PASS |
| 2026-08-05_why-water-breaks-the-rules-of-physi | 7.71 | 85 | 7 | short, long | YES | PASS / PASS |
| 2026-08-09_venus-where-a-day-outlasts-a-year | 7.71 | 80 | 6 | short | YES | PASS / length:scene_count |
| 2026-08-05_what-actually-happens-to-a-body-in- | 7.14 | 92 | 8 | short, long | YES | PASS / PASS |
| 2026-08-10_the-animal-that-poops-in-cubes | 7.14 | 100 | 8 | short, long | YES | PASS / PASS |
| 2026-08-12_your-head-ages-faster-than-your-fee | 7.0 | 99 | 8 | short, long | YES | PASS / PASS |

## Blocking gate families (scripts blocked in BOTH modes)

None -- every legacy control reaches the scorer under at least one length mode.

## Gates recorded NOT TESTABLE (never counted as failures)

- `traceability_hard` — legacy manifests carry no source_claim_ids or claim inventory
- `semantic_support` — requires the LLM critic and a claim inventory; neither exists here
- `information_gain` — LLM call; excluded by the zero-provider constraint
- `score_script` — LLM rubric call; excluded by the zero-provider constraint

## Head-to-head: known-good legacy vs Writer V2.1 certification

_word-count method cross-checked against validate()'s own arithmetic: 13 agree / 0 disagree._

| | legacy controls | V2.1 rounds |
|---|---|---|
| n | 12 | 54 |
| words median | 94.0 | 109.5 |
| words range | 80-104 | 84-156 |
| over the 115 hard ceiling | 0 | 18 |
| clears deterministic gates | 12/12 | 5/54 |
| score when it DOES reach the scorer | 7.0-8.29 | 4.0-5.57 |

### What blocks V2.1 rounds that are ALREADY a legal length

If length were the binding constraint, these would pass.

Of 36 rounds inside a legal word window:

- 5 — PASS
- 4 — craft:repetition
- 4 — length:total_words
- 4 — craft:restated_fact
- 4 — content:key_terms
- 3 — hook:question
- 3 — craft:formal_connector
- 3 — length:hook_words
- 2 — length:per_scene_cap
- 2 — content:whatif_gap
- 1 — meta:hook_headline
- 1 — other:scene 2 voiceover compares to a specific named landmark/obje
