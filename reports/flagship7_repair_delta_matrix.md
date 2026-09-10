# Repair Delta Matrix — Writer corpus (flagship_02..07)

Source: `tests/fixtures/writer_corpus/flagship_02_2dbad04.json` .. `flagship_07_greenland_shark_age.json`, real historical rejected Writer V2.1 output (see that directory's own README: never edited to make a test pass). This document is a read-only data extraction; nothing in `/home/user/content-render` was modified to produce it.

## 0. Schema actually found (inspected before extracting anything)

Top-level fixture object: `{accepted, attempt_count, attempts, evidence_seed_enabled, ...}`, `attempts: [{accepted, attempt, calls, error, repair_rounds, rounds, semantic_retries_used, total_calls, treatment, validate_err, ...}]`.

**Schema differences found, exactly as they appear on disk:**

- **Top-level keys differ by vintage.** `flagship_02` .. `flagship_05` carry `source_run_id, source_head_sha, flagship_attempt, topic_hint` (provenance back to a specific CI run/commit). `flagship_06` and `flagship_07` do **not** carry any of those four keys — instead they carry `requested_topic, topic_id, max_provider_attempts`, which `02`-`05` lack. `INDEX.json` (committed alongside the fixtures) only documents `02`-`06`; **`flagship_07_greenland_shark_age.json` is not indexed there at all** (it is newer than `INDEX.json`'s own last edit).
- **`candidate_kind` / `deterministic_evidence_seed`** appear on every attempt in `04`-`07` but are absent from every attempt in `02`-`03`.
- **`mechanical_trim_applied`** appears on every round in `05`-`07` but is absent from every round in `02`-`04`.
- Round-level fields are otherwise stable across all 6 fixtures: `beats, critic_avg, critic_error, critic_verdict, hook, mechanical_hard_count, mechanical_violation_count, payoff, repair_plan, round, score, score_clears_floor, semantic_coverage_errors, semantic_covered_indices, semantic_critic_attempts, semantic_verified, semantic_violation_count, stalled_going_in, validate_err, violations`.
- **`score` is a dict when present, `null` otherwise** — and it is `null` on **49 of 54 rounds (91%)** in this corpus. Empirically, `score` is populated **iff `validate_err` is `null`** for that round: the scorer only ever runs on a structurally-valid script. This is the single fact that shapes everything below — most parent→child transitions cannot support a craft-score comparison at all.
- `hook` and `payoff` are literal copies of `beats[0]` and `beats[-1]` respectively in every round checked; they are not independent fields.
- `repair_plan.diagnosis` uses a `"beat N: <violation> '<quoted text>'"` format **only for `repair_type: PROVENANCE`** rounds. `HOOK` and `STRUCTURAL` repair types write a whole-script sentence with no `beat N:` markers at all (4 of 36 parent rounds in this corpus: 1 `STRUCTURAL`-word-count, 1 `STRUCTURAL`-restated-fact, 1 `STRUCTURAL`-hook-phrasing, 1 `HOOK`-length). `repair_plan.target_beats` is a separate, always-present structured integer list that still exists on those 4 rounds even when `diagnosis` has no parseable beat markers, and it agrees with the diagnosis-derived indices on every round where both are parseable — used here only as a cross-check, per the task's instruction to parse `diagnosis`.

## 1. Full pair table (36 parent→child rounds, all 6 fixtures, all attempts)

Legend: **P/C** = parent/child. **Ov** = `score.overall` (— = unscored, round had a `validate_err`). **ΔOv** = C−P overall, only computable when both scored. **MH** = `mechanical_hard_count`. **SV** = `semantic_violation_count`. **SVf** = `semantic_verified`. **Δwc** = word count of (hook+beats+payoff), C−P. **#Δbeat** = count of beat indices whose text differs P→C. **TgtMatch** = do the repair_plan's diagnosis-targeted beat indices equal the beats that actually changed? (n/a = diagnosis had no `beat N:` markers, whole-script repair type). **Extra** = a beat changed that was **not** in the targeted set. **VE(P)→VE(C)** = validate_err text, truncated 70 chars, `—`=none.

| Fixture | Att | Rnd P→C | Ov P | Ov C | ΔOv | MH P→C | SV P→C | SVf P→C | Δwc | #Δbeat | beat idxs | TgtMatch | Extra | Bucket | VE(P)→VE(C) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fs02 | 0 | 0→1 | 5.57 | — | — | 2→2 | 5→5 | Y→Y | +25 | 6 | 0,1,2,3,4,5 | Y | — | E | `—` → `script word count 128 out of range (target 78-98, hard 68-108, mode sh` |
| fs02 | 0 | 1→2 | — | — | — | 2→0 | 5→3 | Y→Y | -2 | 6 | 0,1,3,4,5,6 | N | 6 | B | `script word count 128 out of range (target 78-98, hard 68-108, mode sh` → `hook length 18 words out of range` |
| fs02 | 1 | 0→1 | — | — | — | 0→1 | 0→4 | N→Y | +2 | 1 | 0 | n/a | — | E | `hook 'What if the creature you see now has outlived the nation you wer` → `script word count 126 out of range (target 78-98, hard 68-108, mode sh` |
| fs02 | 1 | 1→2 | — | — | — | 1→1 | 4→2 | Y→Y | -19 | 4 | 1,2,4,5 | N | — | B | `script word count 126 out of range (target 78-98, hard 68-108, mode sh` → `scenes 4 and 5 too similar (repetition)` |
| fs03 | 0 | 0→1 | — | — | — | 7→3 | 2→2 | Y→Y | -1 | 6 | 1,2,3,4,5,6 | Y | — | B | `script word count 109 out of range (target 78-98, hard 68-108, mode sh` → `scenes 7 and 8 too similar (repetition)` |
| fs03 | 0 | 1→2 | — | — | — | 3→3 | 2→3 | Y→Y | +9 | 5 | 0,1,3,4,5 | Y | — | F | `scenes 7 and 8 too similar (repetition)` → `script word count 116 out of range (target 78-98, hard 68-108, mode sh` |
| fs03 | 1 | 0→1 | — | — | — | 6→1 | 4→2 | Y→Y | +25 | 4 | 1,2,3,4 | Y | — | B | `hook 'What happens when a day outlasts a year?' is phrased as a QUESTI` → `hook 'What happens when a day outlasts a year?' is phrased as a QUESTI` |
| fs03 | 1 | 1→2 | — | — | — | 1→1 | 2→0 | Y→Y | -24 | 3 | 4,6,7 | Y | — | B | `hook 'What happens when a day outlasts a year?' is phrased as a QUESTI` → `hook 'What happens when a day outlasts a year?' is phrased as a QUESTI` |
| fs03 | 2 | 0→1 | — | — | — | 9→3 | 2→4 | Y→Y | +2 | 4 | 0,1,2,5 | Y | — | B | `scene 4 voiceover uses the formal connector 'Thus' — nobody talks like` → `scene 3 voiceover 'A day on Venus lasts about 243 Earth days, while it` |
| fs03 | 2 | 1→2 | — | — | — | 3→3 | 4→1 | Y→Y | -3 | 6 | 0,1,3,5,6,7 | Y | — | B | `scene 3 voiceover 'A day on Venus lasts about 243 Earth days, while it` → `scene 3 voiceover 'A day on Venus lasts about 243 Earth days, while it` |
| fs04 | 0 | 0→1 | — | — | — | 0→0 | 3→0 | Y→Y | -3 | 2 | 1,7 | N | — | B | `the verified fact is restated in 2 scenes [3, 4] instead of being reve` → `the verified fact is restated in 2 scenes [3, 4] instead of being reve` |
| fs04 | 0 | 1→2 | — | — | — | 0→0 | 0→3 | Y→Y | +0 | 0 | none | n/a | — | F | `the verified fact is restated in 2 scenes [3, 4] instead of being reve` → `the verified fact is restated in 2 scenes [3, 4] instead of being reve` |
| fs04 | 1 | 0→1 | — | — | — | 6→2 | 4→1 | Y→Y | -20 | 6 | 0,1,2,4,5,7 | Y | — | B | `scene 5 voiceover uses the formal connector 'Thus' — nobody talks like` → `hook_headline 'VENUS YEAR ENDS BEFORE' is nearly identical to the spok` |
| fs04 | 1 | 1→2 | — | — | — | 2→1 | 1→3 | Y→Y | -1 | 3 | 0,4,6 | Y | — | B | `hook_headline 'VENUS YEAR ENDS BEFORE' is nearly identical to the spok` → `scenes 1 and 3 too similar (repetition)` |
| fs04 | 2 | 0→1 | — | — | — | 5→3 | 3→1 | Y→Y | -1 | 5 | 0,1,2,4,6 | Y | — | B | `script word count 118 out of range (target 78-98, hard 68-108, mode sh` → `script word count 112 out of range (target 78-98, hard 68-108, mode sh` |
| fs04 | 2 | 1→2 | — | — | — | 3→2 | 1→3 | Y→Y | -1 | 2 | 0,4 | Y | — | B | `script word count 112 out of range (target 78-98, hard 68-108, mode sh` → `script word count 112 out of range (target 78-98, hard 68-108, mode sh` |
| fs04 | 3 | 0→1 | — | — | — | 3→0 | 2→4 | Y→Y | +0 | 4 | 0,1,2,4 | Y | — | B | `script word count 110 out of range (target 78-98, hard 68-108, mode sh` → `scene 5 voiceover too long (28 words, cap is 25)` |
| fs04 | 3 | 1→2 | — | — | — | 0→1 | 4→2 | Y→Y | -6 | 4 | 0,2,3,7 | Y | — | E | `scene 5 voiceover too long (28 words, cap is 25)` → `scene 5 voiceover too long (28 words, cap is 25)` |
| fs05 | 0 | 0→1 | — | — | — | 1→0 | 0→0 | Y→Y | +1 | 1 | 4 | Y | — | B | `script word count 140 out of range (target 78-98, hard 68-108, mode sh` → `script word count 141 out of range (target 78-98, hard 68-108, mode sh` |
| fs05 | 0 | 1→2 | — | — | — | 0→0 | 0→1 | Y→Y | -35 | 2 | 4,6 | n/a | — | F | `script word count 141 out of range (target 78-98, hard 68-108, mode sh` → `only 0/3 mandatory key terms named (none) — the script must explicitly` |
| fs05 | 1 | 0→1 | — | — | — | 1→0 | 1→4 | Y→Y | +18 | 2 | 1,4 | Y | — | B | `script word count 126 out of range (target 78-98, hard 68-108, mode sh` → `scene 5 voiceover too long (30 words, cap is 25)` |
| fs05 | 1 | 1→2 | — | — | — | 0→1 | 4→3 | Y→Y | +15 | 4 | 1,2,6,7 | Y | — | E | `scene 5 voiceover too long (30 words, cap is 25)` → `scene 5 voiceover too long (30 words, cap is 25)` |
| fs05 | 2 | 0→1 | — | — | — | 1→1 | 3→4 | Y→Y | +17 | 2 | 5,6 | N | — | F | `scenes 7 and 8 too similar (repetition)` → `scene 6 voiceover too long (31 words, cap is 25)` |
| fs05 | 2 | 1→2 | — | — | — | 1→1 | 4→4 | Y→Y | +3 | 5 | 0,2,5,6,7 | Y | — | F | `scene 6 voiceover too long (31 words, cap is 25)` → `script word count 118 out of range (target 78-98, hard 68-108, mode sh` |
| fs06 | 0 | 0→1 | — | — | — | 2→0 | 3→2 | Y→Y | -2 | 5 | 0,1,2,4,6 | Y | — | B | `only 1/3 mandatory key terms named (['Greenland shark']) — the script ` → `only 1/3 mandatory key terms named (['Greenland shark']) — the script ` |
| fs06 | 0 | 1→2 | — | — | — | 0→0 | 2→4 | Y→Y | +0 | 1 | 0 | N | — | F | `only 1/3 mandatory key terms named (['Greenland shark']) — the script ` → `only 1/3 mandatory key terms named (['Greenland shark']) — the script ` |
| fs06 | 1 | 0→1 | — | — | — | 0→0 | 2→1 | Y→Y | +5 | 2 | 0,1 | Y | — | B | `scene 2 voiceover compares to a specific named landmark/object ('Unite` → `hook length 17 words out of range` |
| fs06 | 1 | 1→2 | — | — | — | 0→0 | 1→2 | Y→Y | +1 | 1 | 4 | Y | — | F | `hook length 17 words out of range` → `hook length 17 words out of range` |
| fs06 | 2 | 0→1 | — | — | — | 0→0 | 3→0 | Y→Y | +5 | 3 | 0,2,5 | Y | — | B | `scene 7 voiceover uses the formal connector 'Thus' — nobody talks like` → `hook length 18 words out of range` |
| fs06 | 2 | 1→2 | — | — | — | 0→1 | 0→5 | Y→Y | -10 | 1 | 0 | n/a | — | E | `hook length 18 words out of range` → `scene 7 voiceover uses the formal connector 'Thus' — nobody talks like` |
| fs07 | 0 | 0→1 | — | — | — | 2→1 | 5→4 | Y→Y | -4 | 5 | 0,2,4,6,7 | Y | — | B | `whatif curiosity gap never opened — the hook or one of the first few s` → `hook 'Could a Greenland shark you see today have lived before America?` |
| fs07 | 0 | 1→2 | — | — | — | 1→0 | 4→2 | Y→Y | +14 | 4 | 0,1,5,7 | Y | — | B | `hook 'Could a Greenland shark you see today have lived before America?` → `whatif curiosity gap never opened — the hook or one of the first few s` |
| fs07 | 1 | 0→1 | 5.57 | 4.14 | -1.43 | 0→1 | 3→4 | Y→Y | +8 | 3 | 1,3,4 | Y | — | E | `—` → `—` |
| fs07 | 1 | 1→2 | 4.14 | — | — | 1→1 | 4→7 | Y→Y | -4 | 2 | 1,4 | N | — | E | `—` → `the verified fact is restated in 2 scenes [1, 2] instead of being reve` |
| fs07 | 2 | 0→1 | 5.14 | — | — | 2→2 | 2→0 | Y→Y | +39 | 3 | 3,4,7 | Y | — | E | `—` → `script word count 122 out of range (target 78-98, hard 68-108, mode sh` |
| fs07 | 2 | 1→2 | — | 4.00 | — | 2→0 | 0→0 | Y→Y | -25 | 2 | 3,4 | Y | — | B | `script word count 122 out of range (target 78-98, hard 68-108, mode sh` → `—` |

## 2. Bucket counts

**Definitions used** (as specified in the task, applied with one explicit tie-break noted below): *factual/mechanical improvement* = `mechanical_hard_count` decreased, OR `semantic_violation_count` decreased, OR parent had a `validate_err` and child does not. Classification priority: **E is checked first** — any pair that introduced a brand-new hard violation (`mechanical_hard_count` increased) or a brand-new `validate_err` (parent had none, child has one) is bucketed E even if it also happens to satisfy A/B/C/D's criteria, because a fresh regression is the more informative label. This matters for exactly one pair (§4/§5, fs07 attempt 1, round 0→1): it is simultaneously the corpus's only measurable D-candidate (no mechanical improvement + craft down) **and** its clearest E-instance (new hard violation). It is reported as E, and flagged again below so this is not read as cherry-picking.

A 6th bucket, **F**, was added because the specified taxonomy (A-E) does not partition the state space found in the data: a pair with **no** mechanical improvement, **no** new violation, and craft neutral/unscored/improved does not satisfy any of A-E as literally defined. 7 of 36 pairs (19%) land here. This is reported rather than force-fit, per the task's instruction not to invent structure the data doesn't support.

| Bucket | Meaning | Count (of 36) |
|---|---|---|
| A | mechanical improvement AND craft up | **0** |
| B | mechanical improvement, craft neutral/unscored | **21** |
| C | mechanical improvement AND craft down | **0** |
| D | no mechanical improvement AND craft down | **0** |
| E | regression (new hard violation or new validate_err) | **8** |
| F *(added — see above)* | no mechanical improvement, no regression, craft neutral/unscored/up | **7** |

**Zero pairs landed in A, C, or D.** A and C are structurally near-impossible in this corpus for a reason documented in §3: mechanical improvement and "both sides scored" **never co-occur** (0 of 36 pairs). D would need only "both scored" + craft down (no mechanical-improvement requirement) and has exactly one candidate — the same pair claimed by E under the tie-break above.

### Per fixture

| Fixture | A | B | C | D | E | F | total pairs |
|---|---|---|---|---|---|---|---|
| fs02 | 0 | 2 | 0 | 0 | 2 | 0 | 4 |
| fs03 | 0 | 5 | 0 | 0 | 0 | 1 | 6 |
| fs04 | 0 | 6 | 0 | 0 | 1 | 1 | 8 |
| fs05 | 0 | 2 | 0 | 0 | 1 | 3 | 6 |
| fs06 | 0 | 3 | 0 | 0 | 1 | 2 | 6 |
| fs07 | 0 | 3 | 0 | 0 | 3 | 0 | 6 |

## 3. How many pairs actually support a craft-delta measurement

- **Both parent and child scored: N = 1 of 36** (2.8%). This is the *only* row in the entire corpus where an `overall` score delta can be computed at all: fs07, attempt 1, round 0→1 (5.57 → 4.14, Δ = -1.43).
- **Exactly one side scored (parent scored / child fell to unscorable, or vice versa): N = 4 of 36.**
- **Neither side scored: N = 31 of 36 (86%).**
- **Unscored on at least one side (cannot support ANY craft-score comparison): N = 35 of 36 (97%).**

Put plainly: **35 of 36 parent→child transitions in this corpus cannot support a craft-score claim in either direction**, because one or both rounds never reached the scorer (a `validate_err` blocked it). Any statement about repair's effect on craft can only be evidenced by that single N=1 pair, plus the qualitative/text evidence in §4 for the 4 one-side-scored pairs where a previously-scored, structurally-valid draft was repaired into something the validator rejected outright.

## 4. The 5 pairs with the largest craft drop

Ranking method, stated explicitly since only one pair has a real numeric `overall` delta: **#1 is the corpus's only measured drop.** #2-#5 are the next-most-severe transitions by a documented proxy — a previously **scored** (structurally valid) round whose repair produced a **new** `validate_err`/hard violation and fell out of scoring range entirely, ranked by severity of the mechanical/semantic regression. These are not scored drops; they are labeled as the proxy they are.

### #1 — MEASURED (only both-scored pair in the corpus)
`flagship_07_greenland_shark_age.json`, attempt 1, round 0 → 1

- overall: `5.57` → `4.14` (Δ -1.43)
- mechanical_hard_count: `0` → `1`  **← NEW hard violation**
- semantic_violation_count: `3` → `4`
- validate_err: `—` → `—`
- word count (hook+beats+payoff): 113 → 121 (+8)
- repair_plan.repair_type = `PROVENANCE`, tier 1
- repair targeted beats (parsed from diagnosis) = `[1, 3, 4]`; beats that actually changed = `[1, 3, 4]`; match = `Y`

**Changed beats, verbatim:**

- beat [1]
  - PARENT: "The journey belongs to a single protein locked inside its eye."
  - CHILD:  "This eye‑lens protein, formed once in the embryo, makes the Greenland shark the longest-lived vertebrate."
- beat [3]
  - PARENT: "How did this core molecule survive as centuries of new tissue buried it?"
  - CHILD:  "How could such a protein stay unchanged for centuries as the shark’s body grew?"
- beat [4]
  - PARENT: "Freezing water and a heart beating once every twelve seconds prevented decay."
  - CHILD:  "Living in near‑freezing Arctic water and a heart that beats every twelve seconds slows decay."

### #2 — proxy: scored → unscorable, same attempt's next round (continues #1's collapse)
`flagship_07_greenland_shark_age.json`, attempt 1, round 1 → 2

- overall: `4.14` → `—`
- mechanical_hard_count: `1` → `1`
- semantic_violation_count: `4` → `7`
- validate_err: `—` → `the verified fact is restated in 2 scenes [1, 2] instead of being revealed once and escalated from`  **← NEW**
- word count (hook+beats+payoff): 121 → 117 (-4)
- repair_plan.repair_type = `PROVENANCE`, tier 1
- repair targeted beats (parsed from diagnosis) = `[1, 2, 4, 7]`; beats that actually changed = `[1, 4]`; match = `N`

**Changed beats, verbatim:**

- beat [1]
  - PARENT: "This eye‑lens protein, formed once in the embryo, makes the Greenland shark the longest-lived vertebrate."
  - CHILD:  "This protein lets the Greenland shark live around 400 years, the longest‑lived vertebrate."
- beat [4]
  - PARENT: "Living in near‑freezing Arctic water and a heart that beats every twelve seconds slows decay."
  - CHILD:  "In near‑freezing Arctic water, a heart that beats every twelve seconds slows decay."

### #3 — proxy: scored → unscorable, +25 words pushed it over the hard cap
`flagship_02_2dbad04.json`, attempt 0, round 0 → 1

- overall: `5.57` → `—`
- mechanical_hard_count: `2` → `2`
- semantic_violation_count: `5` → `5`
- validate_err: `—` → `script word count 128 out of range (target 78-98, hard 68-108, mode short)`  **← NEW**
- word count (hook+beats+payoff): 131 → 156 (+25)
- repair_plan.repair_type = `PROVENANCE`, tier 1
- repair targeted beats (parsed from diagnosis) = `[0, 1, 2, 3, 4, 5]`; beats that actually changed = `[0, 1, 2, 3, 4, 5]`; match = `Y`

**Changed beats, verbatim:**

- beat [0]
  - PARENT: "Your dinner could share a timeline with a nation"
  - CHILD:  "A Greenland shark alive today may have been born before the United States existed."
- beat [1]
  - PARENT: "You think the ocean is just a cold, empty expanse?"
  - CHILD:  "The Arctic ocean houses Greenland sharks that may have been born before the United States existed."
- beat [2]
  - PARENT: "But beneath that silence lies a Greenland shark moving slower than centuries."
  - CHILD:  "These sharks grow only about a centimeter a year and do not reach adulthood until around 150 years old."
- beat [3]
  - PARENT: "The Greenland shark grows roughly a centimeter each year, taking about 150 years to become an adult."
  - CHILD:  "The Greenland shark grows roughly a centimeter each year and takes about 150 years to become an adult."
- beat [4]
  - PARENT: "Its metabolism lets it survive for around 400 years, making it the longest-lived vertebrate on Earth."
  - CHILD:  "Its metabolism lets it survive for around 400 years, making it the longest-lived vertebrate with a backbone."
- beat [5]
  - PARENT: "Because it reproduces so slowly, any drop in its numbers takes centuries to recover."
  - CHILD:  "Its slow growth and late maturity mean population changes can take a long time."

### #4 — proxy: scored → unscorable, +39 words (largest word-count blowout of any scored→unscorable pair)
`flagship_07_greenland_shark_age.json`, attempt 2, round 0 → 1

- overall: `5.14` → `—`
- mechanical_hard_count: `2` → `2`
- semantic_violation_count: `2` → `0`
- validate_err: `—` → `script word count 122 out of range (target 78-98, hard 68-108, mode short)`  **← NEW**
- word count (hook+beats+payoff): 114 → 153 (+39)
- repair_plan.repair_type = `PROVENANCE`, tier 1
- repair targeted beats (parsed from diagnosis) = `[3, 4, 7]`; beats that actually changed = `[3, 4, 7]`; match = `Y`

**Changed beats, verbatim:**

- beat [3]
  - PARENT: "As she grew barely a centimeter yearly, new lens layers sealed it away."
  - CHILD:  "The Greenland shark grows only about 0.5 to 1 cm a year, taking a human lifetime to reach the length of an office desk."
- beat [4]
  - PARENT: "It weathered sub-zero Arctic water without breaking down, shielded by stabilizing chemicals."
  - CHILD:  "Its eye proteins are stabilized by high concentrations of trimethylamine N‑oxide and urea, protecting them from denaturation in cold water."
- beat [7]
  - PARENT: "This creature was already a century old before modern science even began."
  - CHILD:  "The oldest dated shark, born between 1504 and 1744, lived during the Ming Dynasty, making it the longest‑lived vertebrate of its time."

### #5 — proxy: unscored both sides, but the single largest semantic-violation jump (0→5) and a new hard violation, from a one-beat hook trim
`flagship_06_fed4b0f.json`, attempt 2, round 1 → 2

- overall: `—` → `—`
- mechanical_hard_count: `0` → `1`  **← NEW hard violation**
- semantic_violation_count: `0` → `5`
- validate_err: `hook length 18 words out of range` → `scene 7 voiceover uses the formal connector 'Thus' — nobody talks like this out loud; rewrite in plain conversational language`
- word count (hook+beats+payoff): 143 → 133 (-10)
- repair_plan.repair_type = `HOOK`, tier 2
- repair targeted beats (parsed from diagnosis) = `none parseable`; beats that actually changed = `[0]`; match = `n/a`

**Changed beats, verbatim:**

- beat [0]
  - PARENT: "A Greenland shark swimming in the Arctic right now may have been born before the United States existed."
  - CHILD:  "A Greenland shark in the Arctic may have been born before the U.S."

## 5. Bucket A pairs (mechanical improvement AND craft improvement) — the existence-proof check

**There are 0 pairs in bucket A.**

Bucket A is **empty**. There is no row in this 36-pair corpus where the same parent→child transition both (a) reduced `mechanical_hard_count` or `semantic_violation_count` or cleared a `validate_err`, **and** (b) raised the `overall` score by more than 0.15. This is not a near-miss: as shown in §3, "mechanical improvement" and "both sides scored" never co-occur even once in the corpus (`mech_improved AND both_scored` = 0 of 36), so bucket A's precondition cannot be satisfied by any row currently on file, favorable or not. The corpus's one truly-measured craft delta (§4 #1) went the opposite direction: overall −1.43, plus a brand-new hard violation.

**Conclusion the data actually supports:** this corpus does not show that repair systematically *improves* craft, and it does not show that repair systematically *degrades* craft either — because 97% of transitions (35/36) are unscored on at least one side and cannot speak to craft at all. What the corpus **does** show, with real numbers: mechanical repair reliably shrinks the flagged-violation counts it targets in the round it targets them (mech_improved = True in 24 of 36 pairs), it sometimes trades one violation for a new one (E, 8 of 36 = 22%, including the corpus's only measured-craft pair, which got worse on both axes at once), and its aim is otherwise imprecise but not wild: of the 32 pairs where the repair plan's targeted beats could be parsed from `diagnosis`, 26 (81%) changed exactly the targeted beats and no others, 5 changed a strict subset of the targeted beats (under-application), and exactly 1 changed a beat outside the targeted set.

## 6. Pairs unscored on either side (cannot support a craft claim)

**35 of 36 pairs (97.2%)** have `score.overall = null` on the parent, the child, or both. Broken down: 31 pairs unscored on **both** sides, 4 pairs unscored on **exactly one** side, 1 pair scored on **both** sides. Only that last one pair can support any craft-direction claim with an actual number attached.

## 7. Other findings surfaced during extraction (not asked for, but real and relevant)

- **Judge/critic non-determinism on byte-identical text.** `flagship_04`, attempt 0, round 1→2: `hook`, all 8 `beats`, and `payoff` are **literally identical strings** parent→child (the repair changed nothing — same `validate_err` persists verbatim: "the verified fact is restated in 2 scenes [3, 4]..."), yet `semantic_violation_count` moved 0→3 and `critic_avg` moved 7.11→6.56 on the exact same input. This is scorer/critic variance, not a repair effect, and it lands in bucket F here — flagged separately because it means even a same-text "pair" is not a clean zero-effect control.
- **A hook-length fix (mechanical) spiked semantic violations 0→5 by itself** (§4 #5): trimming "the United States" to "the U.S." to satisfy an 18-word hook cap changed nothing else in the script, yet `semantic_violation_count` went from 0 to 5 and a new hard violation appeared — consistent with the semantic/citation checker matching against the literal string in the evidence ("United States") and failing to recognize the abbreviation as the same entity.
- **`targets_match_changed` mismatches are almost all under-application, not scope creep.** Of the 6 mismatches (of 32 determinable pairs), 5 changed a strict subset of the beats the diagnosis named and 0 beats outside it; only 1 pair (fs02, attempt 0, round 1→2) changed a beat (index 6) that the diagnosis never targeted (indices 0,1,3,4,5), and even there every targeted beat was also changed — it is additive, not a substitution.

