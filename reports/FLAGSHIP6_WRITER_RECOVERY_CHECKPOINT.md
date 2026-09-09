# Flagship #6 Writer recovery — mission checkpoint

Recovery state for resuming in a fresh session. Concise by design.

- **branch**: `claude/flagship6-writer-repair-policy-20260909`
- **base/main SHA**: `fed4b0fd80ca353668fe80283bbe23e3fcbcd8ca`
- **pushed SHA**: see `git log -1` (updated each milestone)
- **source artifact**: run 34305189931, artifact 10086461186, topic
  `greenland_shark_age`, treatment INSIDE_THE_SYSTEM, 3 candidates / 9 rounds

## Irreversible boundaries NOT crossed
No merge, no flagship, no provider/Gemini call, no paid visual generation, no
Release, no Publer, no posting, no deploy, no secret change,
`AUTO_PUBLISH_ENABLED` untouched.

---

## Finding 1 — the post-#76 length contract WORKED (new evidence)

Per-fixture replay of the whole corpus, same tokenizer/constants `validate()`
uses:

| fixture | rounds | total_word | scene_cap | hook_len | hook_is_q | key_terms | connector |
|---|---|---|---|---|---|---|---|
| flagship_02 | 6 | 2 | 0 | 1 | 1 | 0 | 0 |
| flagship_03 | 9 | 2 | 0 | 0 | 3 | 0 | 1 |
| flagship_04 | 12 | 4 | 2 | 0 | 0 | 0 | 1 |
| flagship_05 | 9 | 4 | 3 | 0 | 0 | 1 | 0 |
| **flagship_06** | **9** | **0** | **0** | **3** | **0** | **3** | **2** |

Runs 2–5: 17 length failures / 36 rounds (47%). Run 6: **0 / 9**.

The open question carried out of the last session — *does Gemini obey a stated
budget?* — is answered YES for total-word and per-scene cap. Not a statistical
claim (n=9, one run), but the mechanism is exact: the contract states total
words + per-scene cap, and precisely those two families went to zero.

The failure mode MOVED to the deterministic constraints the repair is never
told about: hook length, mandatory key terms, forbidden formal connectors.

## Finding 2 — ROOT CAUSE: `classify_repair()` is a single-winner selector

Confirmed in code and in all 9 rounds of the artifact. `classify_repair()`
returns ONE plan. Tier 1 (hard + semantic violations) `return`s immediately, so
`validate_err` is **discarded entirely**, and that branch hardcodes
`must_preserve: []`.

Artifact proof — `repair_type` / `tier` / whether validate_err reached the plan:

| candidate | r0 | r1 | r2 | validate_err reached repair? |
|---|---|---|---|---|
| 1 | PROVENANCE t1 | PROVENANCE t1 | PROVENANCE t1 | **never** |
| 2 | PROVENANCE t1 | PROVENANCE t1 | PROVENANCE t1 | **never** |
| 3 | PROVENANCE t1 | HOOK t2 | PROVENANCE t1 | once (r1 only) |

Tier 2 was reachable exactly **once in 9 rounds** — candidate 3 round 1 — and
only because `semantic_violation_count == 0` that round. Semantic violations
were non-empty in 8/9 rounds, so the constraint that actually decides
accept/reject was structurally starved by the one that is almost always
non-empty.

Consequences visible in the artifact:
- **Candidate 1**: the byte-identical "only 1/3 mandatory key terms" error at
  rounds 0, 1 AND 2. Never targeted. Critic average *fell* 6.0 → 5.22 → 5.56.
- **Candidate 2**: r0 repair rewrote the hook to 17 words; r1 and r2 both
  blocked on that 17-word hook while the repair chased beat-4 semantics.
- **Candidate 3**: r1 fixed the hook (the one tier-2 round), r2 reintroduced
  "Thus" and 5 semantic violations.

## Finding 3 — more rounds would NOT have helped (disproves the obvious fix)

Candidate 1 carried the same validate_err through its entire budget while
semantic violations stayed non-empty. A round 3, 4 or 10 would classify tier 1
again and never see the key-term defect. This is a control-flow defect, not a
budget-size defect — so `MAX_REPAIR_ROUNDS` stays at 2.

## Refinement of the brief's hypothesis

The brief proposed "repair budget allocated poorly". Directionally right,
mechanically imprecise: the problem is not distribution *across rounds* but
that each repair carries only ONE dimension. Fix = let one bounded repair carry
the primary factual/semantic target **and** the deterministic constraints its
rewritten narration will be judged against.

---

## Finding 4 — measured provider waste (S9)

Counted from the run's own job log (102320299424), not estimated:

- **9 paid sleeps** on Groq `gpt-oss-120b` 429s, totalling **99.51 s**
- 10 `failed HTTP 429` fall-throughs
- retry-after values **5.80–14.47 s** (median 10.48)
- writer stage wall clock **164 s** (02:57:40 → 03:00:24)
- **61% of the writer stage was spent asleep on one rate-limited model**

Excluding sleeps, ~65 s of work spread over ~18 calls ≈ 3.6 s median spacing —
well inside every observed retry-after. So after the first 429 records a
cooldown, subsequent 120b attempts land inside a live cooldown and become
instant skips. The first bounded in-loop retry is deliberately preserved, so
the eliminable portion is the other 8 sleeps: **~89 s of ~99.5 s**, roughly
**55% of writer wall clock**. Exact saving depends on inter-call spacing, which
the log only gives in aggregate — stated as an estimate, not a measurement.

## Workstream status

- **A — replay new corpus**: DONE (`flagship_06_fed4b0f.json` + INDEX; matrix
  above; runs 02-05 baseline re-pinned to its own fixtures).
- **B — repair policy**: DONE. `must_also_satisfy` rides with the primary
  target at every tier; `must_preserve` protects already-named key terms.
- **C — anti-drift contract**: DONE. `narration_deterministic_contract()` from
  validate()'s own constants; HOOK_WORD_LO/HI, KEY_TERMS_MIN_NAMED and
  FORBIDDEN_CONNECTORS extracted so prompt and validator cannot diverge.
- **D — provider session health**: DONE. Per-(provider,model) cooldown from the
  provider's own retry delay, clamped, checked in `_walk` and in the
  certification strict loop, cleared on success, evidence in a separate channel.
- **E — champion/challenger**: structural evidence covered by the F suite
  (contract reaches prompt, factual target preserved, gates unchanged). No
  counterfactual acceptance claimed — offline replay cannot know what a model
  WOULD have written.
- **F — adversarial tests**: DONE. 15 checks in
  `tests/test_repair_policy_and_provider_health.py`, all ten named classes.
- **G — CI**: exact-head run pending on the PR.

## Local proof
57 suites green; 1598 zero-provider checks; new suite registered in tests.yml.

## Exact next action
Implement `must_also_satisfy` in `writer_v2_repair.classify_repair()` (populated
from the CURRENT `validate_err` + runtime narration contract regardless of
tier), render it in `build_repair_prompt()`, and populate `must_preserve` with
mandatory key terms when the validate_err is a key-term failure. Tier priority
for the PRIMARY target stays exactly as-is — no gate weakened, no extra rounds.
