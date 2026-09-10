# Flagship #8 release prep — checkpoint

- **branch**: `claude/flagship8-deterministic-release-20260910` (fresh from main)
- **main SHA**: `024b0b8d1dc56454c7c245864535f46b235852af` (verified)
- **experiment branch, untouched**: `claude/flagship7-craft-preserving-repair-20260909`
  head `651b74f`, PR **#82**, DRAFT, UNMERGED
- **pushed SHA**: see `git log -1`

## What this release contains — the whole production delta

**One production file, ONE production fix: `writer_v2_repair.py`, all of it
inside `classify_repair`. Traceability is byte-identical to main.**

**Critic `must_preserve` reaches every repair tier.** The critic is asked, in its
own schema, for "a short list of specific things in the beats you are NOT
flagging that the rewrite must not disturb". `classify_repair` used it on tier 3
only; tier 1 (unsupported claim) and tier 2 (validate failure) computed it and
threw it away — and those two tiers fire in nearly every real round.

Carrying it into tier 1 unfiltered introduces a contradiction main could not
produce, so the fix ships with its own guard: an entry naming text this round's
own violations say must change is dropped, and the list is deduplicated
case-insensitively. Without that, one prompt could say "remove Atlantis, it is
unsupported" and "MUST PRESERVE EXACTLY: Atlantis". `test_7`/`test_8`/`test_9`
pin it.

### WITHDRAWN after adversarial review: the initialism fix

An earlier version of this release also taught traceability that a cited
multi-word entity's initialism counts as that entity. It is **gone**, for two
independent reasons:

1. **It opened a hole in the HARD provenance gate.** Initials are a lossy hash,
   so a fabricated entity passes whenever its initials collide with an unrelated
   cited one — cite "Deep Nautical Analysis" and a fabricated "DNA" is admitted.
   Verified against a faithful reconstruction of the withdrawn helpers in
   `test_6`, which then proves the hard gate rejects it today.
2. **Its justification was mis-attributed.** The claim was that two deterministic
   gates fought: `deterministic_mechanical_trim` abbreviated the hook and
   provenance rejected the result. That function explicitly refuses to touch the
   hook or payoff and never invents text, so the abbreviation came from an LLM
   repair round. There was no gate conflict to resolve.

**Correction to how (1) was first written up.** The repro that raised it —
"The US government funded this secret ice mission" against a cited "Ultraviolet
Sensor" — does return zero hard violations, but not because of the initialism
rule: "us" is a pronoun in `_CONNECTIVE_STOPWORDS`, so "US" never reaches the
entity check on any version of this code, including plain main. A single-word
entity in sentence-initial position is separately classified WEAK and reported
soft by deliberate V2.1 design. The hole is real; that particular line did not
demonstrate it. `test_6` demonstrates it with a non-stopword acronym placed
mid-sentence.

Consequence: "U.S." is still rejected against a cited "United States" — a known,
accepted false positive. A factual gate failing CLOSED is the correct direction,
and `test_5` pins it so nobody re-opens the hatch by accident.

Nothing else in production changed. `writer_v21_orchestrator.py` is **untouched**:
its `treatment_name`/`treatments` delta on PR #82 existed solely to feed the
narrative-function contract, so it does not belong here.

## What is deliberately EXCLUDED

The narrative-function craft experiment — `beat_role`, `beat_purpose`,
`narrative_function_contract`, the "WHAT THESE BEATS ARE FOR" prompt block, the
payoff-stealing warning, and the PROVENANCE instruction rewrite. It targets a
real single-case failure (flagship #7 attempt 2) but **the corpus does not show
the epidemic it was written for**, so it is not a proven production improvement.
It stays on PR #82, draft and unmerged.

`test_10` asserts its absence, including that the PROVENANCE instruction is
byte-for-byte the shipped one and that no treatment plumbing reached the
orchestrator.

## Non-production tooling included

`writer_craft_rescore.py`, `reports/CRAFT_METRIC_PREREGISTRATION.md`, the rescore
output, the 36-pair delta matrix, and the flagship-07 corpus fixture.

**Proof it cannot affect eligibility** — none of `generate.py`,
`writer_v2_repair.py`, `writer_v21_orchestrator.py`, `main.py` imports
`writer_craft_rescore` or any of the three diagnostic modules it composes
(`writer_v21_editorial_diagnostics`, `writer_v21_story_shape`,
`writer_v21_hook_payoff`). It is forensic only: zero provider calls, zero
network, no recurring cost, and no path to candidate eligibility, repair
classification, quality-floor clearing, selection or publishing.

## The corrected flagship #7 result (canonical)

The hypothesis "provenance repair systematically degrades craft" is **NOT
supported**. Under the old LLM `score.overall` the question was **INSUFFICIENT**
(1 of 36 pairs measurable). Under the deterministic proxy rescore it is
**approximately NEUTRAL**:

| population | IMPROVED | FLAT | DEGRADED |
|---|---|---|---|
| all pairs (N=36) | 11 | 12 | 13 |
| factual/mechanical improvement (N=24) | 10 | 5 | 9 |
| PROVENANCE (N=32) | 11 | 8 | 13 |

**Instrument limits, explicit**: five preregistered components, only three move
within pairs. All are lexical/structural proxies. They do not measure prose
quality, rhythm, surprise, emotional payoff, or watchability. This is a cheap
deterministic pre-flight and longitudinal record — **not** an acceptance gate,
**not** a replacement for the 6.8 floor, **not** a human-preference metric.

**Semantic correction**: "already a century old before modern science even began"
was **genuinely unsupported**; the evidence supported "before America was even a
country". `UNSUPPORTED_ADDITION` fired correctly and the taxonomy is unchanged.

**Byte-identical control (N=1)**: on the corpus's one identical parent->child
pair the deterministic checks held (`mechanical_hard_count` 0 -> 0) while the LLM
judge moved (`critic_avg` 7.111 -> 6.556, `semantic_violation_count` 0 -> 3).
Since semantic violations drive tier-1 repair this is worth remembering, but N=1
bounds nothing and it is **not** a reason to weaken semantic checking.

## Gates unchanged
`QUALITY_HARD_FLOOR` 6.8 · `QUALITY_CRITERION_FLOORS` (hook 6, escalation 6,
payoff 6, coherence 7) · `MAX_REPAIR_ROUNDS` 2 · word windows · semantic taxonomy
· repair tier priority · candidate advancement · `select_best_candidate`.

## Boundaries not crossed
No merge, no flagship, no provider call, no paid render, no Release, no Publer,
no posting, no deploy, no secret change, `AUTO_PUBLISH_ENABLED` untouched.
PR #80 untouched.

## Post-merge plan (for whenever Jacob authorises)
1. Merge this PR; confirm actual-main CI green.
2. Run `python writer_craft_rescore.py` as a **$0 pre-flight / evidence capture**
   — not a gate.
3. Trigger exactly ONE private `topic=auto` certification-only flagship.

Its purpose is **not** to validate the excluded experiment. It is to answer:
**does the production Writer, with this one deterministic correction, produce a
certified candidate and reach the renderer?**

## Backlog
C7 PARTIAL (until a real Writer success) · S10 ADVANCED/PARTIAL (36/36 pairs
deterministically measurable) · S4 OPEN (human preference still missing) ·
C8 COMPLETE, do not reopen · S9 PARTIAL (cost routing, off critical path) ·
A11 PR #80 optional hardening, untouched.
