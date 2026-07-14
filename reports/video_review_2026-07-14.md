# Video review log — 2026-07-14 (multi-topic consistency)

## Cycle 1 — the "every render is identical" disaster (root-caused)

**Finding:** renders 34, 35, 36, and 38 are ALL the identical video "The Flock
With No Leader" (starling murmuration). This is the worst possible form of the
user's "1 good then 1 shit" complaint — the profile was publishing the SAME
video over and over.

**Root cause (confirmed, not the dedup code):**
- `manifest_example.json` IS the murmuration video.
- `render.yml` ran `python generate.py manifest.json || cp manifest_example.json manifest.json`.
- So *every time `generate.py` failed, the workflow shipped the hardcoded
  murmuration example.*
- `generate.py` was failing because Groq's free-tier quota/rate-limit was
  exhausted: I (and prior loop cycles) triggered many renders in a short window
  (34→38 inside ~40 min, plus each render makes many LLM calls — 5 generation
  attempts × regenerations + quality scoring + punch-up + footage judging).
  `generate_candidate`'s 5-attempt backoff (8·attempt s) couldn't outlast a
  sustained quota block → all attempts threw → `generate.py` exited 1 → fallback.
- The generate step took ~4 min then fell back — consistent with total Groq
  exhaustion, not a code bug. (Last SUCCESSFUL generations: "Morning Height
  Boost" 02:35 and "Crushing Pressure" 02:42, before the burst.)

**Why the dedup fix looked broken but wasn't:** the flocking dedup
(BANNED_CONCEPTS / `_metaphor_too_similar` / domain-window) never even runs when
`generate.py` fails before producing a candidate — the murmuration came from the
static example file, not from generation.

**Fixes applied this cycle:**
1. `render.yml` — REMOVED the `|| cp manifest_example.json` fallback. A failed
   generation now retries once after 90s, then ABORTS the run (no render, no
   release, no duplicate). No video is far better than the same video 5×. This
   makes "consistently good" actually enforceable — a failed generation can
   never masquerade as content again.
2. Loop pacing (next cycle) — stop bursting 3 renders at once (that is what
   exhausts Groq). Render at most 1 per cycle, well spaced, so generation
   actually succeeds and each video is a genuinely different topic.

**Not yet judged on merit:** because renders 34–38 are the fallback example, the
actual iteration-1 quality fixes (caption sync, pacing, voice, ≤2 cards) have
NOT been validated on a real generated video yet. The two real videos that did
generate (Morning Height Boost, Crushing Pressure) predate the caption/pacing
fixes. Next real, unique render is the first true test — must watch its frames.

**Honest note on iteration speed:** free-tier Groq quota caps how fast this loop
can render/iterate. Rapid generate→watch→improve cycles are not feasible on the
free tier; realistic cadence is a few good renders spaced out, not a burst.
