# Preregistered craft metric — written and committed BEFORE any pair delta was computed

Git history is the timestamp. Nothing in this file may change after the 36-pair
results are read; a later mission that wants a different metric must add a new
one and say why, not edit this.

## Why not `score_script`

`generate.score_script()` is **an LLM call** (`call_groq(prompt)`, `generate.py:3375`),
not a deterministic function. Rescoring the corpus with it would:

- cost ~72 provider calls for a retrospective pass, and a **recurring** per-render
  cost for a prospective `diagnostic_craft_score` (recurring paid spend is
  reserved to Jacob);
- build the measurement on a **stochastic** instrument. The corpus already shows
  an LLM judge moving `critic_avg` 7.11 -> 6.56 and `semantic_violation_count`
  0 -> 3 on **byte-identical** narration (flagship_04, attempt 0, round 1->2). An
  instrument whose noise is comparable to the effect cannot resolve the effect.

So the retrospective rescore is done with **deterministic, already-shipped,
zero-LLM diagnostics** instead. This also removes the entire
"diagnostic score must not affect eligibility" risk surface: these modules
already return `"gating": False` and are not consulted by
`select_best_candidate`, `_clears_quality_floor`, or `classify_repair`.

## Sources (all pure, no network, no provider)

- `writer_v21_editorial_diagnostics.editorial_diagnostics`
- `writer_v21_story_shape.shape_signature`
- `writer_v21_hook_payoff.payoff_proof_report`

## The circularity exclusion — the part that matters most

"Mechanical/factual improvement" is defined as: `mechanical_hard_count` fell, OR
`semantic_violation_count` fell, OR the parent had a `validate_err` and the child
does not. So **any craft signal that mirrors a `validate()` check is circular**:
the child would score better precisely because it cleared the violation used to
label it improved.

`validate()` failures actually observed in this corpus: script word count, hook
length, hook phrased as a question, "scenes N and M too similar (repetition)",
formal connectors, "the verified fact is restated in N scenes", hook_headline
duplicating the spoken hook, whatif curiosity gap never opened.

**EXCLUDED as circular** (available, deliberately unused):

| signal | mirrors |
|---|---|
| `low_information_gain` | "verified fact is restated in N scenes" |
| `adjacent_repetition` | "scenes N and M too similar (repetition)" |
| `payoff_restates_hook` / `hook_payoff_overlap` | fact-restatement family |
| `spoken_sentence_too_long` | script/scene word-count checks |
| `monotone_sentence_rhythm` | derived from the same word counts |

## The metric: 5 components, no invented weights

| # | component | source | direction |
|---|---|---|---|
| 1 | `generic_ai_moralizing` hit count | editorial_diagnostics | lower is better |
| 2 | `generic_payoff_hits` count | payoff_proof_report | lower is better |
| 3 | `unique_function_count` | shape_signature | higher is better |
| 4 | `repeated_primary_runs` | shape_signature | lower is better |
| 5 | `resolution_cue_present` (0/1) | payoff_proof_report | higher is better |

None of the five is checked by `validate()`, so none can move merely because a
validator violation was cleared.

**Per-pair verdict** — deliberately no weighted scalar, because any weighting
would be invented after the fact:

    improved  = number of the 5 components that moved in the better direction
    degraded  = number that moved in the worse direction
    verdict   = IMPROVED  if improved > degraded
                DEGRADED  if degraded > improved
                FLAT      if equal (including all-unchanged)

Raw per-component magnitudes are reported alongside the verdict, never replaced
by it.

## Honest limits, stated in advance

- 36 pairs from 6 flagship runs on a handful of topics is a **convenience
  corpus**, not a sample of any population. No significance testing, no
  confidence intervals, no generalisation beyond "this is what these runs did".
- These five signals are **proxies**. They do not measure whether a human enjoys
  the video. A repair could improve all five and still read worse aloud.
- The metric is blind to prose quality within a line. It sees vocabulary
  novelty, sentence function, and known AI-tell patterns — nothing else.
