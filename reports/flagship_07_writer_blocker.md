# Flagship #7 — the Writer blocker, classified

Run **34404373120**, `workflow_dispatch`, main `024b0b8`, `topic=auto` →
`greenland_shark_age`, treatment `ONE_OBJECT_JOURNEY`. Failed at
`writer_v21_bundle` after 3 bounded candidates. Fixture:
`tests/fixtures/writer_corpus/flagship_07_greenland_shark_age.json`.

## What is now FIXED, confirmed in a real run

- **Length arithmetic is no longer the terminal cause.** PR #79's length contract
  works. Across 9 rounds there was exactly ONE length rejection (att 3 round 1,
  122 words) and the repair fixed it. Historically 50% of rounds died here.
- **Provider health works.** Groq 429'd continuously on both `gpt-oss-120b` and
  `gpt-oss-20b`; the bounded cooldown absorbed it, fell through, and
  `gemini-flash-latest` carried 4 calls. No permanent suppression, no fail-open.
- **Runner prerequisites are clean.** The apt incident cleared; step 7 passed.

## The blocker: repair monotonically DEGRADES quality, and never approaches the floor

| att | round | overall | hook | esc | payoff | rewatch | mech-hard | sem-viol | validate_err |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | – | – | – | – | – | 2 | 5 | whatif curiosity gap never opened |
| 1 | 1 | – | – | – | – | – | 1 | 4 | hook length |
| 1 | 2 | – | – | – | – | – | 0 | 2 | whatif curiosity gap never opened |
| 2 | 0 | **5.57** | 5 | 4 | 4 | 6 | 0 | 3 | — |
| 2 | 1 | **4.14** | 5 | 4 | 3 | 6 | 1 | 4 | — |
| 2 | 2 | – | – | – | – | – | 1 | 7 | fact restated in scenes [1,2] |
| 3 | 0 | **5.14** | 5 | 5 | 4 | 5 | 2 | 2 | — |
| 3 | 1 | – | – | – | – | – | 2 | 0 | word count 122 out of range |
| 3 | 2 | **4.00** | 5 | 3 | 3 | 3 | **0** | **0** | — |

**0 of 4 scored repair rounds improved the score. Every one made it worse.**
Best score in the entire run: **5.57** against a hard floor of **6.8** — a gap of
1.23, not a near miss.

### Finding 1 — mechanical perfection and craft are anticorrelated here

Attempt 3 round 3 is the cleanest output the run produced: `mechanical_hard_count
0`, `semantic_violation_count 0`, `semantic_verified true`. It also scored its
**worst**: 4.00, with escalation 3, payoff 3, rewatch 3.

The repair achieved exactly what it was asked to and destroyed the video. Compare
the same beat before and after provenance repair:

    round 1  "It weathered sub-zero Arctic water without breaking down,
              shielded by stabilizing chemicals."
    round 3  "Massive concentrations of urea protect her proteins from
              denaturation."

    round 1  "This creature was already a century old before modern science
              even began."
    round 3  "The oldest dated shark, born between 1504 and 1744, lived during
              the Ming Dynasty, making it the longest-lived vertebrate of its
              time."

The first pair is a video. The second is a citation. The provenance critic
flagged the round-1 payoff as `UNSUPPORTED_ADDITION` — it is *true and follows
from the cited facts*, but it is not a restatement of them, and the repair
replaced evocative-but-entailed language with literal-but-dead language.

### Finding 2 — two gates contradict each other, reproducibly

`validate()` **requires** a whatif curiosity-gap question in the first four
lines. Attempt 1 was rejected twice for its absence:

    "whatif curiosity gap never opened -- the hook or one of the first few
     scenes must pose a real question, not just state facts"

Attempt 3 supplied exactly that question, and the round-3 repair plan attacked
it:

    "Beat 2 is a rhetorical question that stalls the narrative and fails to
     raise the stakes, breaking the escalation curve."

One gate demands the question; the critic scores it as an escalation defect. In
attempt 1 the ping-pong is visible inside a single candidate: round 1 added the
question and broke the hook length; round 2 fixed the hook and lost the question
again.

This is the same defect class as the "Did you know" incident, where the prompt
banned a phrase nine lines below an example that used it — a rule fighting its
own instructions.

## What was deliberately NOT done

No gate was changed, no retry added, no floor moved. The instruction was to
classify, and the evidence says the problem is not gate strictness in isolation:
a candidate that satisfies every mechanical and semantic gate perfectly scores
4.00. Loosening a gate would ship that video.

## The cheap next experiment

`writer_replay.py` + this fixture replays all 9 rounds offline at **$0**. The
question worth answering there, before spending another flagship:

> Does the repair prompt ever *preserve* craft, or is provenance repair
> structurally a downgrade? If the latter, the fix is in what repair is allowed
> to trade away — not in the floor it is measured against.
