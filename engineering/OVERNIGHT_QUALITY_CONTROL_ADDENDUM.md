# Overnight Quality Control Addendum — 2026-09-04 00:42 CT

This addendum extends `engineering/OVERNIGHT_QUALITY_CONTROL.md` and is part of the canonical hourly handoff until folded back into the primary checkpoint.

## Live state verified this run
- origin/main: `6a045e50a33408ecafdfa21c9ff951d731347bd9` — unchanged.
- Claude Writer V2.1 base: `claude/writer-v2-traceability-repair-01` @ `2256f229be0c5b245cb5c1a2ec7cd4b0d8b3c2e6`.
- SuperChad takeover branch advanced to `648c13d5b4a58aa0c93a668e5c5d496949b8c37b`.
- PR #56 remains draft, base = Claude Writer V2.1 branch, not main.
- Latest Actions run for takeover head: `33837755848`, pending at checkpoint write.
- No merge, deploy, render, publish, cron/live-delivery change, or paid provider call.

## Added overnight priorities now encoded in the hourly automation
The stateful `Content Render Overnight Control` automation now explicitly carries:
1. blind pairwise editorial judging;
2. repair-regression protection;
3. permanent known-bad torture corpus;
4. narrative-shape diversity diagnostics;
5. first-8-second audit;
6. spoken hook / on-screen hook / first-frame visual / cover-headline separation;
7. payoff proof;
8. pre-render visual feasibility pressure test;
9. structured failure-learning records;
10. promotion evidence packet.

The automation must read the primary checkpoint AND this addendum before acting.

## New implementation — repair craft regression
`writer_v21_repair_regression.py`

Purpose: preserve evidence that a factual repair can make a script less watchable before any selection rule is changed.

Current telemetry includes:
- exact before/after lines;
- declared target beats vs changed beats;
- hook/payoff word inflation;
- newly introduced generic AI moralizing;
- information-gain/repetition warning changes;
- critic craft-average decline;
- legacy-score decline;
- scorer-vs-critic disagreement worsening;
- untargeted text changes.

All output remains `gating=False`.

## New implementation — blind pairwise editorial judge
`writer_v21_pairwise.py`

Purpose: absolute score swings are noisy. Pairwise comparison asks the easier question: between two candidates that ALREADY passed factual, validation, and semantic gates, which is the stronger human-facing short-form story?

Safety/rigor:
- candidate ids, round numbers, treatment names, original/repair/newer metadata, previous scores, and repair history never enter the judge prompt;
- deterministic but blind A/B order;
- only factually clean + validate-clean + semantic-verified candidates are eligible;
- criteria: opening pull, spoken naturalness, information gain, escalation, payoff, low AI smell, visual tellability;
- explicit TIE option to prevent forced fake differences;
- structured verdict validation;
- alias maps back to candidate identity only AFTER verdict;
- cannot accept/reject a script; `gating=False`.

Zero-network tests added in `tests/test_writer_v21_pairwise.py` and wired into CI.

## New implementation — permanent known-bad torture corpus
`writer_v21_torture_corpus.py`

Canonical real failure classes:
- `mantis_shrimp_blender` — unsupported comparison + generic moralizing payoff;
- `neutron_star_invented_mechanism` — no-number/no-proper-noun hallucinated mechanism/application;
- `mauna_kea_invented_framing` — invented authority/record framing;
- `lightning_duration_inflation` — one-day -> three-month quantitative inflation;
- `chess_magnitude_only` — technically impressive magnitude with weak idea/payoff + AI grandeur;
- `stomach_clinical_repair` — provenance repair makes sharper prose long/clinical/flat.

The corpus records the expected guard (`hard_traceability`, `semantic_support`, `editorial_quality`, or `repair_regression_pairwise`) instead of pretending every failure is string-matchable.

Zero-network tests added in `tests/test_writer_v21_torture_corpus.py` and wired into CI.

## Latest branch writes this run
- `39759dfb4bd654bf1bb3f5f988d45e585029ed35` — add blind pairwise editorial judging contract.
- `0167eafb1ed580246edbf468e79951751bbaa977` — pairwise zero-network tests.
- `1b479b5f0169de5068a3b8e96c45e6e66d57b24a` — permanent known-bad torture corpus.
- `abb923e284e523eefdf4b2eb1702441bded0cbbd` — torture corpus tests.
- `648c13d5b4a58aa0c93a668e5c5d496949b8c37b` — run pairwise + torture corpus in CI.

## NEXT EXACT ACTION
1. Read Actions run `33837755848`.
2. If RED: diagnose exact failing new test/contract and fix without weakening a guard.
3. If GREEN: build deterministic NARRATIVE-SHAPE DIVERSITY + FIRST-8-SECOND diagnostics next, still non-gating.
4. Then integrate those diagnostics into `wr21_takeover_bakeoff.py` reporting.
5. If secret-backed Groq quota is available after those zero-quota gates are green, run the corrected five-topic panel once through `wr21_run.py`; do not run repeatedly under quota contention.
6. Every live script must be read as a human. Pairwise judge is evidence, not a substitute for human editorial judgment.

## Promotion remains HOLD
No genuinely postable, quality-floor-clearing Writer V2.1 script has yet been demonstrated under the final combined semantic-failclosed + spoken-hook/payoff stack.
Full video certification is still NOT EARNED.
