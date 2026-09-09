# Writer V2.1 flagship rejection audit — 2026-09-08

Primary evidence: private `quality-certification-render` artifacts, no provider calls made for this audit.

## Source runs

- run #2: `34257803289`
- run #3: `34263047438`
- run #4: `34264652218`
- run #5: `34284331800`

Together: **13 candidate attempts / 36 recorded repair rounds / 0 accepted candidates**.

## Validation failure matrix

| Family | Rounds |
| --- | ---: |
| total script length | 12 |
| per-scene length | 5 |
| repetition / restatement | 7 |
| hook-question conflict | 4 |
| formal `Thus` connector | 2 |
| spoken-flow / overloaded entity clause | 2 |
| headline restates hook | 1 |
| missing mandatory key terms | 1 |
| hook length | 1 |
| no validate error | 1 |

**Length constraints account for 17/36 rounds = 47.2%.** The observed short-mode validator was target **78-98** total words, hard **68-108**, with **25 words max per scene**.

## Treatment distribution

- `TIMELINE_TRANSFORMATION`: 21 rounds
  - total length 6
  - repetition/restatement 5
  - hook-question conflict 3
  - formal connector 2
  - per-scene length 2
  - spoken-flow 2
  - headline restatement 1
- `INSIDE_THE_SYSTEM`: 15 rounds
  - total length 6
  - per-scene length 3
  - repetition 2
  - missing key terms 1
  - hook length 1
  - hook-question conflict 1
  - no validate error 1

This sample is enough to identify concrete failure families, **not** enough to declare either treatment generically bad. Only two treatments are represented.

## Repair-budget hypothesis check

Repair plans across the corpus:

- `PROVENANCE`: 33 rounds
- `STRUCTURAL`: 3 rounds

At first glance this looked like provenance repair was starving craft repair. The round evidence does **not** support that as the primary cause.

Only **2/36 rounds (5.6%)** were simultaneously:

- `mechanical_hard_count == 0`
- `semantic_violation_count == 0`
- `semantic_verified == true`

Those two Tier-1-clean rounds still had a structural validator defect (one repetition case, one total-length case). In the other 34 rounds there was a real traceability/semantic problem that legitimately outranked craft repair.

Conclusion: do **not** buy quality by simply adding more repair rounds or bypassing provenance priority. Improve what the Writer and repair model are instructed to produce so fewer Tier-1 defects and hidden-contract defects are created in the first place.

## Confirmed control-plane defects

### 1. Runtime length contract was hidden from Writer V2.1

`generate.validate()` enforces dynamic SHORT/LONG word windows and the per-scene cap. Before the recovery branch, `writer_v21_orchestrator` called `writer_v2.build_writer_prompt_v2()` without telling the Writer those runtime values.

The legacy writer prompt had `LENGTH_HINT`; the promoted V2.1 path did not.

Therefore nearly half the real repair rounds were being judged against length rules the producing model could not see.

### 2. Hook/question instructions were internally ambiguous against the validator

The V2 HOOK section correctly says **never open on a question mark** and to move a literal question to a later beat. But the same static prompt's CURIOSITY GAP rule says the required early `?` may appear in **"the hook OR one of the first 3 beats"**. Production `generate.validate()` is stricter: a question-mark hook is always rejected and the curiosity gap belongs in scene 2 or later.

So this was not a simple "prompt requires a question hook" bug. It was an internal instruction ambiguity: one rule forbids a question hook while another explicitly lists the hook as an allowed location for the required question. Four real rounds chose the invalid interpretation and failed exactly at that boundary.

The recovery branch makes the final runtime contract unambiguous: scene 1 is a statement and any literal curiosity question belongs in scene 2 or later.

### 3. Initial-call-only fixes are insufficient

A provenance/semantic repair can rewrite narration and reintroduce length, repetition, jargon, or hook-shape defects. The exact same runtime narration contract therefore needs to be visible to **repair calls**, not only the initial draft call.

## Recovery-branch response

`superchad/flagship-writer-recovery-20260908` adds one runtime narration contract, derived directly from the live `generate.py` constants and treatment beat count, and appends that same contract to:

1. the initial Writer V2.1 prompt;
2. every Writer V2.1 repair prompt.

The contract explicitly states:

- active target + hard total-word windows;
- per-scene hard cap;
- exact treatment scene shape;
- scene-1 shock statement, not a question;
- no fake interrogatives;
- distinct information per beat / no consecutive mechanism restatement;
- plain-language translation of necessary technical terms;
- natural insertion of mandatory key terms;
- concrete payoff rather than generic uplift;
- no `Thus` / `Therefore` spoken openings.

No quality, factual, semantic, provenance, or validation gate is loosened.

## What this audit does NOT prove

- It does not prove the new prompt will pass a paid live run; that requires separate provider authorization.
- It does not justify widening the word windows.
- It does not prove `INSIDE_THE_SYSTEM` should be removed or demoted; treatment-fit needs a broader sample.
- It does not justify extra repair rounds; the current corpus argues for better first-pass/repair instructions first.
