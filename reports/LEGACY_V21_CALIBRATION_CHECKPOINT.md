# Legacy → V2.1 calibration — did we break a working Writer?

- **branch**: `claude/legacy-v21-calibration-20260910` (fresh from main `024b0b8`)
- **cost**: $0. Zero provider calls, zero network for the experiment itself, zero LLM.
- **production changes**: none. This branch adds a diagnostic script, fixtures and reports only.

## PRIMARY DIAGNOSIS: **WRITER / PROMPT / MODEL DEFICIT**

The hypothesis that the V2.1 gate stack drifted and now rejects scripts we already
know make good videos is **NOT SUPPORTED**.

**12 of 12** real August videos — narration byte-for-byte as committed, scores
7.0–8.29 — pass today's deterministic gate stack and would reach the quality
scorer. Not one is blocked by a gate.

Meanwhile, across **54** preserved Writer V2.1 certification rounds, **5** clear
the same gates. And on the **same scorer, same rubric, same function**, the five
that get there score **4.0–5.57** against legacy's **7.0–8.29**.

| | legacy controls | V2.1 rounds |
|---|---|---|
| n | 12 | 54 |
| words median | 94.0 | 109.5 |
| words range | 80–104 | 84–156 |
| over the 115-word hard ceiling | 0 | 18 |
| clears deterministic gates | **12/12** | **5/54** |
| score when it DOES reach the scorer | **7.0–8.29** | **4.0–5.57** |

That last row is the finding. It is not a gate result at all — it is the same
LLM rubric, reached by both, disagreeing about the writing by three full points.

## Why this is not tautological (the objection I had to answer)

A committed August manifest is by construction one that passed August's
`validate()`. If the gates were unchanged, "legacy passes validate" proves
nothing. So the claim rests only on the parts that genuinely changed:

`validate()` moved in exactly four ways since 2026-08-07 (diff below is the whole
code delta; comment-only changes excluded):

1. `4 <= hook <= 16` → `HOOK_WORD_LO/HI` — **constant extraction, identical
   behaviour**. This was NOT a new gate; I initially mis-read it as one.
2. **NEW** `FALSE_PRESENT_STAKES_RE` on the hook.
3. **NEW** `GENERIC_REFRAME_CLICHE_RE` on the final line.
4. Two **relaxations**: `REFERENCE_WORTHY_RE` now skipped for bank facts, and the
   restated-fact check gained a numeric-key-term exemption.

So the non-tautological question is: do the two genuinely new gates reject
known-good scripts? **0 of 12 trip either one.** Word windows (`78-98/68-108`
short, `95-110/85-115` long), `SCENE_WORD_CAP = 25` and the hook range are
numerically **identical** to August, verified against `generate.py` at
`64e1f3a` (2026-08-07).

## Scorer comparability: **IDENTICAL for 9/12, MATERIALLY COMPARABLE for 3/12**

Both paths call the *same function*. `writer_v21_orchestrator.py:161`:

```python
score = None if validate_err else G.score_script(manifest, fact=fact, cta_style=cta_style)
```

`score_script`'s rubric text, criteria list, coercion and aggregation
(`overall` = unweighted mean of 7 criteria, computed by us, not by the model) are
unchanged since 2026-08-03 — before every control. The only post-August change
was `e3ed744` (2026-09-03), which altered **fail-open → fail-closed policy and
docstrings only**, not a single scoring semantic.

One real, bounded difference: `CTA_RUBRIC_HINTS["COMMENT"]` was reworded stricter
on 2026-09-03. It feeds **one of seven criteria** (`rewatch`) and only for
COMMENT-style endings. **9 of 12 controls** (SAVE_WORTHY/LOOP — including spiders
8.14 and shape-memory 8.29) used hint text that is byte-identical today. The 3
COMMENT controls scored 7.14, 7.14, 8.14.

The 7.0–8.29 vs 4.0–5.57 gap therefore is **not** an artifact of a changed scorer.

## The control set (evidence-bound, tiered honestly)

All 12 recovered from `git show <sha>:manifest.json`, saved verbatim to
`tests/fixtures/legacy_controls/`. Scores are from `memory_science.json`, not
memory. The user's remembered figures checked out: fingerprints 8.14, spiders
8.14, flammable ocean floor 8.0.

**TIER A — rendered AND released (9).** A GitHub Release exists carrying 6
platform-cut MP4s, 4.0–11.3 MB each. This is post-ready output, not just a script.

**TIER B — scored manifest, NO release (3).** `the-metal-that-remembers-its-shape`
(8.29), `what-actually-happens-to-a-body-in-space` (7.14),
`part-1-the-solid-that-is-secretly-a-liqu` (8.0). These reached a committed,
scored manifest but produced no Release — most likely aborted at final-QA. **The
single highest-scoring control is Tier B**, so "8.29" is a script score, not a
proven video. The diagnosis does not depend on them: Tier A alone is 9/9 passing
with scores 7.0–8.14.

## Provenance: **NOT TESTABLE for 12/12 — and that is not a failure**

Legacy manifests contain no `source_claim_ids`, no claim inventory, no evidence
packet — and no `fact_id` either (the fact link lives only in
`memory_science.json`). Traceability and semantic-support gates are therefore
recorded **NOT TESTABLE**, never FAIL. Absent metadata is not evidence that a
sentence was unsupported, and nothing was researched today and back-dated to
manufacture an evidence packet.

Consequence, stated plainly: this experiment **cannot** rule out that V2.1's
traceability/semantic layer is miscalibrated. It rules out the *deterministic
editorial* gates as the cause. See "what is still open".

## What actually blocks V2.1 — it is not the word budget

67% of V2.1 rounds (36/54) are already inside a legal word window, yet only 5
pass. Of those 36:

- 5 PASS
- 4 `craft:repetition` · 4 `craft:restated_fact` · 4 `content:key_terms`
- 4 `length:total_words` (legal for LONG, run in SHORT — mode mismatch, not bloat)
- 3 `hook:question` · 3 `craft:formal_connector` · 3 `length:hook_words`
- 2 `length:per_scene_cap` · 2 `content:whatif_gap` · 1 `meta:hook_headline` · 1 other

Repetition, restating the fact instead of escalating from it, failing to name the
mandatory key terms, opening on a question. These are **writing failures**, and
they are exactly the gates 12/12 human-approved legacy scripts clear.

This also **corrects the standing claim in CLAUDE.md** that "18 of 36 rounds (50%)
died on pure length arithmetic". Across the fuller 54-round corpus, length-family
gates account for 22/54 (41%), and a third of those are a short/long mode
mismatch rather than an over-long draft.

## Measurement error found and fixed (recorded so it is not repeated)

My first V2.1 word counts were inflated 20–30 words (median reported 133; true
median 109.5). A round's `beats` list **is** the full spoken sequence —
`beats[0]` is the hook and `beats[-1]` is the payoff, both *also* stored
separately. Joining `hook + beats + payoff` double-counts them.

Caught by cross-checking against the word counts `validate()` printed in its own
error strings: 0/13 agreed before the fix, 13/13 after. `legacy_v21_replay.py`
now runs that cross-check on every invocation and **refuses to emit a comparison**
if it ever disagrees.

## What is disproven

- **"The gates broke a working Writer."** No. 12/12 known-good scripts pass.
- **"Legacy 8.14 vs V2.1 5.57 is comparing different scorers."** No — same
  function, same rubric, unchanged since before the controls; the one changed
  hint touches 1 of 7 criteria on 3 of 12 controls.
- **"Length is the dominant V2.1 blocker."** No. Two thirds of rounds are already
  a legal length and still fail, on craft and content.

## What is still open (not claimed as answered)

- The V2.1-only **traceability and semantic-support** layer is untested here and
  untestable against legacy artifacts. If a gate stack is miscalibrated, that is
  where it would be — it is the one layer with no legacy control.
- No same-input scorer test was run (it needs a provider call). The comparability
  argument is from code identity, which is strong but not a live A/B.
- N=12 controls and one 54-round corpus. Not a population estimate.

## Recommendation for flagship #8: **CHANGE WRITER FIRST**

Merging PR #83 first is fine and costs nothing — it is exact-head certified — but
it will not move this number. #83 fixes repair *plumbing*; the evidence says the
constraint is the quality of what the Writer produces before repair.

The highest-value next step is the one thing this mission could not do at $0: a
same-input scorer test. Feed a legacy control's exact narration through
`score_script` today. If it still scores ~8, the scorer is stable and the Writer
gap is fully confirmed. That is one provider call, and it is the cheapest
remaining question in the project.

## Boundaries

No merge, no flagship, no provider call, no paid render, no Release, no Publer,
no posting, no deploy, no secret change. `AUTO_PUBLISH_ENABLED` untouched. No
production prompt, gate, floor, repair or model change. PR #82, #80 untouched;
PR #83 not modified during this mission.

---

# Open-PR triage (read-only inventory — nothing merged, closed or commented)

**29 open PRs**, not the ~20 previously assumed. Every classification below was
checked against the actual main checkout, not against PR titles.

| class | n | PRs |
|---|---|---|
| MERGE CANDIDATE | 3 | #80, #81, #83 |
| KEEP EXPERIMENT | 1 | #82 |
| SUPERSEDED — CLOSE | 2 | #46 (→#44), #67 (→#80) |
| NEEDS DECISION | 2 | #37, #44 |
| **OBSOLETE — CLOSE** | **21** | #42, #43, #45, #47–#56, #68–#71, #73, #74, #75, #77 |

**21 of 29 open PRs are stale duplicates of work already on main.** For each, the
PR's own distinctive module/symbol/report was confirmed present in the main
checkout. Eight of them additionally cannot merge as-is (dirty/unstable, or based
on a non-main branch). This is the graveyard, and it is most of the list.

## The three merge candidates each fix a defect verified still live on main

- **#83** — the current minimal release candidate. Based on `024b0b8`, clean,
  `test` + `factory-proof` green on exact head `fe943d5`, 1598 zero-quota checks.
- **#80** — main still has **four** bare `sudo apt-get update -qq` calls
  (`render.yml:65`, `quality_certification_render.yml:103`,
  `production_realism_proof.yml:51`, `tests.yml:190`). Verified by grep. Merging
  it also retires #67, whose diff #80 deletes outright.
- **#81** — `quality_downstream_factory_proof.py:142` still reads
  `work = Path(dest).parent / "master_work"`, i.e. mastering scratch is still
  written into the uploaded artifact directory. Verified by grep. This is the
  ~190 MB half of the Actions-storage overage.

## The two that need Jacob, because they are NOT already shipped

- **#37** — half-landed. Domain canonicalisation is on main; the workflow gate is
  not: `.github/workflows/expand_bank.yml` still commits topic-bank changes
  **without running the zero-quota suite first**. Its CI is currently red.
- **#44** — wholly unlanded, and it touches production judging. `main.py:792` on
  main still reads `JUDGE_MODEL = "llama-3.3-70b-versatile"`, and the fal clip
  safety check still samples a single frame. I re-verified this line by hand
  after initially misreading a truncated grep as a refutation.
