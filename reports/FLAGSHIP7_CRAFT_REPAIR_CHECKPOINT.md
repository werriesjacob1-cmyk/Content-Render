# Flagship #7 craft-preserving repair — mission checkpoint

- **branch**: `claude/flagship7-craft-preserving-repair-20260909`
- **base SHA**: `a3f13d4295657842a34cedd33ab66c8cffb38dc0` (= main `024b0b8` + flagship-7 evidence)
- **main SHA**: `024b0b8d1dc56454c7c245864535f46b235852af` (verified)
- **pushed SHA**: see `git log -1`

## Completed phases
- A corpus study — **DONE** (`reports/flagship7_repair_delta_matrix.md`, 36 pairs)
- B semantic ruling — **DONE** (overturns the previous session's claim)
- C narrative-function contract — **DONE**
- D advancement policy — **EVALUATED AND DECLINED ON EVIDENCE** (finding B6)
- E curiosity-gap conflict — **RECLASSIFIED** (finding A2)
- F challenger — **DONE** (`tests/test_craft_preserving_repair.py`, 30 assertions)

## Boundaries not crossed
No merge, no flagship, no provider call, no paid generation, no Release, no
Publer, no posting, no deploy, no secret change, `AUTO_PUBLISH_ENABLED` untouched.

---

## FINDING B1 — the critic was RIGHT, and the previous report was WRONG

`reports/flagship_07_writer_blocker.md` (written by the previous session, i.e. by
me) said of the rejected payoff:

> "The provenance critic flagged the round-1 payoff as `UNSUPPORTED_ADDITION` —
> it is *true and follows from the cited facts*"

**That is incorrect.** The line was:

    "This creature was already a century old before modern science even began."

The topic bank's own `whatif` field — which `build_claim_inventory` turns into
`base_004` verbatim (`writer_v2.py:406-426`, source `topic_bank.whatif_answer`) —
reads:

    "A Greenland shark alive now could have been swimming since the 1600s,
     meaning it was already a century old before AMERICA was even a country."

The writer took the evidence's own framing and swapped the supported referent
(**America**, founded 1776) for an unsupported one (**modern science**). Ruling:

- **not** directly supported;
- **not** logically entailed — it requires an external date for "when modern
  science began", which appears in no claim;
- and on the most common reading it is **false**: a shark born in the 1620s was
  a century old around the 1720s, by which point the Royal Society (1660) and
  Newton's *Principia* (1687) were long established.

So this is category **5 — genuinely unsupported**, exactly as the brief's own
test prescribed ("If the shark line requires outside knowledge to define 'modern
science began', call it unsupported. Do not rationalize it because it sounds
good.").

**No new semantic taxonomy category is warranted on this evidence.** The existing
`UNSUPPORTED_ADDITION` verdict fired correctly. Adding a `SUPPORTED_INFERENCE`
escape hatch to accommodate this line would have admitted a false claim.

## FINDING B2 — this makes the craft indictment STRONGER, not weaker

The obvious reading of B1 is "the critic was right, so repair had no choice but
to flatten." **The evidence refutes that.**

`base_004` was in the claim inventory, cited by the hook itself
(`violations[0].cited_claim_ids == ["base_001", "base_004"]`). A fully supported,
equally vivid payoff was therefore sitting in the repair's own evidence block:

    supported AND vivid    "...already a century old before America was even a country"
    what repair produced   "The oldest dated shark, born between 1504 and 1744, lived
                            during the Ming Dynasty, making it the longest-lived
                            vertebrate of its time."

Factual safety did **not** force citation prose here. The repair had a better,
safe option in front of it and did not take it.

## FINDING B3 — the PROVENANCE instruction contains an explicit licence to flatten

`writer_v2_repair.build_repair_prompt`, the PROVENANCE branch, ends:

> "It is fine for a rewritten beat to be more general/qualitative if the evidence
> doesn't support a specific number or name."

Nothing anywhere in that prompt states what the beat is FOR. The prompt carries:
the full script, the evidence claims, the diagnosis, `must_preserve` (literal
terms only — "MUST PRESERVE EXACTLY (do not rephrase or drop these)"),
`must_also_satisfy` (deterministic constraints), and a do-not-touch-other-beats
instruction. **The beat's narrative role never reaches the repairer.** A payoff
and a setup beat are repaired by identical instructions.

## FINDING B4 — acceptance is already safe; ADVANCEMENT is not

Reading the controller rather than assuming:

- `select_best_candidate` (`writer_v2_repair.py:1197`) is **already lexicographic
  and already safe**: zero hard violations AND no `validate_err` are mandatory
  filters, and only then does `_candidate_better` compare score with critic
  average as a near-tie break. An unsafe high-scoring candidate can never win.
  Every round is appended to `candidates` (`orchestrator:238`), so a bad repair
  cannot destroy an earlier good candidate's eligibility.
- **But `writer_v21_orchestrator.py:336` advances unconditionally**:
  `writer_out = new_writer_out`. Round N+1's repair always branches from round
  N's output even when that output bought nothing and scored worse.

So the controller defect is narrower than "repair acceptance is broken". It is:
the repair CHAIN always continues from the newest state rather than from the best
safe state. With `MAX_REPAIR_ROUNDS = 2` this compounds at most once — which is
exactly what flagship #7 attempt 3 shows (5.14 → unscored → 4.00).

---

## FINDING B5 — the real mechanism is EVIDENCE GRAVITY, not "flattening"

"Provenance repair turns lines into citation prose" is too narrow, and two of the
three attempts contradict it:

- **attempt 1**: repair moved the payoff TOWARD the good supported line —
  it ended at *"A shark alive now was already swimming before America was even a
  country."* Repair is capable of finding the vivid supported option.
- **attempt 2**: the payoff never changed at all across all three rounds, yet
  overall still fell 5.57 -> 4.14.
- **attempt 3**: the payoff did flatten into a date-stuffed citation.

Attempt 2 is the decisive case. The repair targeted beats [1, 3, 4] and changed
EXACTLY those three; every non-targeted beat stayed byte-identical, so the
targeting machinery worked as designed. And `coherence` still collapsed **7 -> 2**
(clarity 8 -> 5, surprise 5 -> 4, payoff 4 -> 3).

The cause is visible in beat 1:

    before  "The journey belongs to a single protein locked inside its eye."
    after   "This eye-lens protein, formed once in the embryo, makes the
             Greenland shark the longest-lived vertebrate."

The repair made beat 1 supported by reaching for the strongest, most-quotable
claim available — and that claim is the video's CONCLUSION. It imported the
payoff's punchline into the second line of the script. The payoff then restates
it, so the script announces its ending up front and coherence collapses.

**ROOT CAUSE (generic).** PROVENANCE repair receives the entire evidence
inventory and one instruction — make this beat supported — with no statement of
what the beat is FOR, no statement of what it must NOT say because a later beat
says it, and an explicit licence to generalise. The cheapest way for a model to
make a line "supported" is to restate the most-quotable claim in the inventory,
which is usually the conclusion. So repair pulls beats toward the payoff's
content and toward citation phrasing, collapsing the information ORDERING that
makes a script escalate — even when it edits only the beats it was told to edit.

Flattening (attempt 3) and pre-empting the payoff (attempt 2) are two symptoms of
that one cause.

## FINDING B6 — the fix is NOT the advancement policy

Checked before building it, and the evidence says a repair-frontier / re-basing
policy would not have helped:

| attempt | craft drop | which repair caused it |
|---|---|---|
| 1 | (unscored) | first repair |
| 2 | 5.57 -> 4.14 | **first** repair |
| 3 | 5.14 -> 4.00 | **first** repair (payoff flattened at round 0 -> 1) |

In every case the damage is done by the FIRST repair, from the only base that
existed. Re-basing round 2 on a better round 0 could not have prevented any of
it, and it would introduce the stale-evidence hazard the orchestrator already
warns about at lines 290-304 (a plan computed for one text applied to another).

`select_best_candidate` is already lexicographically safe and already keeps every
round as a candidate, so acceptance needs no change either. **Controller
unchanged; the defect is in the repair plan and prompt.**

## FINDING A1 — the systematic-degradation claim is UNMEASURABLE, not proven

The brief (and my own earlier report) said "every scored repair reduced quality".
Extracting all **36 parent->child pairs** across flagships 02-07 shows that is not
a claim this data can carry:

| | count |
|---|---|
| both parent and child scored | **1 of 36 (2.8%)** |
| unscored on at least one side | **35 of 36 (97%)** |
| bucket A — factual gain + craft gain | **0** |
| bucket C — factual gain + craft LOSS | **0** |
| bucket E — repair introduced a NEW violation | **8 of 36 (22%)** |

`score` is populated **iff `validate_err` is null**, so "mechanical improvement"
and "both sides scored" **never co-occur (0 of 36)**. Bucket C — the mission's
central hypothesis — is not merely empty, it is **structurally impossible to
populate with the current instrumentation.**

So the honest answer to "is craft degradation systematic?" is **INSUFFICIENT**,
and it will stay insufficient no matter how many more flagships run, until the
rubric score is computed for structurally-invalid drafts too. That is the single
highest-value follow-up this mission found and it is NOT fixed here.

The "0 of 4 scored repairs improved quality" figure was round-level, not
pair-level. It does not mean what it appears to mean, and I repeated it before
checking.

## FINDING A2 — the curiosity-gap "contradiction" is classification B/C, not A

The validator is not overconstrained. `validate()` requires an early question;
the critic separately judged one supplied question to be weak ("stalls the
narrative"). Both can be true at once — a required question can still be a bad
question. What was missing is the instruction that a repair changing that
question must replace it with a BETTER curiosity gap rather than drop the
requirement. The narrative contract now states each beat's obligation, which
covers this generically without weakening the gate.

## FINDING A3 — two deterministic gates were fighting over an abbreviation

`deterministic_mechanical_trim` shortened "the United States" to "the U.S." to
fit a hook word cap, changing nothing else. The provenance checker then flagged
`U.S` as an unsupported entity: semantic violations **0 -> 5** plus a new hard
violation, manufacturing a PROVENANCE repair — the repair type most likely to
damage the script — for a defect that does not exist.

Verified directly, and my first attempt at this was wrong: passing raw claim
dicts without their precomputed `allowed_entities` made verbatim "United States"
look broken too. With a real `build_claim_inventory`, the verbatim form was
**always clean**. The bug is the abbreviation case only, now fixed by computing
initialisms rather than by any abbreviation list.

## Corpus findings NOT asked for but real
- **Critic non-determinism on byte-identical text**: flagship_04 attempt 0 round
  1->2 has identical hook, all 8 beats and payoff, and `semantic_violation_count`
  still moved 0 -> 3 with `critic_avg` 7.11 -> 6.56. Even a same-text pair is not
  a clean zero-effect control, which further weakens any craft inference.
- Repair aim is imprecise but not wild: of 32 parseable pairs, 26 changed exactly
  the targeted beats, 5 under-applied, 1 changed an extra beat.

## Gates confirmed unchanged so far
Nothing modified yet. `QUALITY_HARD_FLOOR` 6.8, `MAX_REPAIR_ROUNDS` 2, word
budget, semantic checks, provenance checks all untouched.

## Exact next action
Exact-head CI on the draft PR, then the merge decision is Jacob's.

**Recommendation: FIX BEFORE NEXT FLAGSHIP — but the fix that matters most is
not in this branch.** This branch removes three real structural defects and one
gate-vs-gate conflict, all evidence-backed. It cannot be shown to raise craft,
because *nothing* can be shown to raise or lower craft while 97% of repair
transitions are unscored. Spending another flagship now would produce one more
mostly-unmeasurable corpus entry.

The unblocking change is to **score structurally-invalid drafts too** (or record
a craft score alongside every `validate_err`), so bucket C can exist at all. That
is a contained change to the orchestrator's scoring call, and until it lands,
"does repair make scripts better or merely cleaner?" is unanswerable by
construction.
