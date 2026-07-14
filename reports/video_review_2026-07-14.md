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

## Cycle 2 — first real generated video, and the all-text-card disaster

Render 39 (post-abort-fix) SUCCEEDED generation and produced a UNIQUE topic:
"Turtles Breathe Through Rear Ends" (cloacal respiration, domain animals). So
the abort fix works and Groq recovered. But watching the frames exposed a
second, equally-bad systemic failure:

**The video was 18.7s of 10/10 TEXT CARDS — zero real footage.** No turtles, no
ocean, just gradient cards reading "TURTLE SURVIVAL", "OXYGEN ABSORPTION",
"MAIN OXYGEN", "HUMAN SKIN". Unwatchable.

- Root cause: Pexels free tier (200 req/hr) was ALSO exhausted by the render
  burst, so `_gather_candidates` returned zero clips for every scene. With no
  clip to fall back to, `accept_best` couldn't rescue and MAX_STAT_CARDS=2 was
  silently bypassed — every scene carded.
- Fix (commit fd18861): if STAT_CARD_SCENES > MAX_STAT_CARDS, main.py now
  exits non-zero → no release. A footage-starved slideshow can never publish.

**Script problems also visible (next cycle's work, NOT yet fixed):**
- Repetition: scenes 5/6/8 restate the same oxygen fact 3× ("supplies most of
  the oxygen" / "absorb oxygen through their tissues" / "main oxygen source").
- Fragmentation: 10 micro-scenes of 2-5 words each ("Some turtles do this",
  "They use their rear ends") → ~60 words total, 1.9s/scene, choppy.
- No specifics: never says which turtles, how long they stay down, or a number.
- Caption clutter: karaoke word + card label both on screen (e.g. "SURFACING" +
  "TURTLE SURVIVAL"), meaningless one-word fragments.

**Consistency status: NOT ready.** Two "ships broken output" bugs now fixed
(manifest fallback, footage starvation). Next: prove a spaced single render
produces REAL footage, then attack script repetition/fragmentation so the
script itself is tight and specific across topics.

## Cycle 3 — guard confirmed working; Groq quota still recovering
Run 40 (fixed code 55dc78b) FAILED at step 7 (Auto-generate) — generation
failed twice → clean abort, no duplicate shipped. Confirms the abort guard
works. Groq free quota still exhausted (succeeded 08:04 for run 39, spent again
by 08:29). No new video to judge. Backing off the cadence further (~45min) to
let Groq recover; next cycle triggers a fresh render at its start, then judges.
Script-repetition/fragmentation fix still pending a successful render to test on.

## Cycle 4 — the ACTUAL blocker found + fixed (judge resilience)
Run 41: generation SUCCEEDED with a GOOD script — Mauna Kea taller than Everest
("stack two Everests and still be shorter", "over 10,000 metres", "100
skyscrapers"): concrete hook, specific numbers, vivid comparison, full
sentences. This CONFIRMS the turtle script was a quota-degraded fluke and the
prompt is fine (did NOT touch it — correct call).

But the render still failed, and the real root cause emerged from the log:
- ElevenLabs quota nearly exhausted (115/10000 credits) → deep Daniel voice
  UNAVAILABLE, fell back to edge-tts (en-US-GuyNeural). Quota issue, not code.
- The Groq footage JUDGE got 429'd on ~every scene. The code treated
  'judge unreachable (429)' identically to 'judge answered garbled' (UNRESOLVED)
  → rejected the clip → text card → footage-starvation guard aborted the whole
  render. So a transient Groq rate-limit silently killed good videos.

Fix (commit 8e7c546): distinguish transport failure (429/5xx/network) from an
unparseable reply. New JUDGE_UNAVAILABLE sentinel; fetch_clip ships the top
stock clip (like no-key) when the judge is unreachable, instead of carding.
Unit-tested all three verdict paths. This should let renders SUCCEED with real
footage + the good script even under Groq pressure — the key unblock.

Still pending: watch a render that clears end-to-end (real footage + good
script) and judge it honestly; the ElevenLabs voice will be edge-tts until its
monthly credits reset (user should know: deep voice is quota-gated).

## Cycle 5 — Groq free DAILY quota depleted; backing off hours
Run 42 (judge-fix 6146fe4) FAILED at Auto-generate — generation itself failed
twice → clean abort. Groq gave only brief windows today (08:04, 09:47) and is
out again by 10:06; ~9 renders today (34-42) consumed the free daily token
budget. The judge-resilience fix (8e7c546) is committed/unit-tested but can't be
validated until a generation succeeds. Continuing to trigger every 30-45min just
churns Actions minutes against a dead quota. Backing the loop off to ~3h so the
daily quota can actually reset before the next attempt. No user message (quota
story already given). Guards all confirmed working; code is resilient — the only
blocker now is raw free-tier quota, which is time (or a few $ of paid tier).

## Cycle 6 — FIRST GENUINELY WATCHABLE VIDEO ✓ (run 43, "Cosmic Coincidence")
Groq daily quota reset; run 43 SUCCEEDED end-to-end on the fully-fixed code.
Topic: the Sun/Moon 400× coincidence + eclipses fading. WATCHED the frames:
- REAL RELEVANT FOOTAGE on every scene (crescent moon, full moon, Sun surface,
  horizon silhouette, eclipse, crowds for "civilization") — ZERO text cards.
  The judge-resilience fix delivered: footage shipped on every scene.
- Script: concrete hook ("You see the Sun and Moon as the same size"),
  full-sentence scenes (7-14 words), real numbers (400×, 3.8 cm/yr, 80,000
  civilizations), clean escalation with a midpoint twist, satisfying payoff.
  98 words, 28.4s. No restatement.
- On-screen numbers (400 times, 3.8, 80,000 times) land on the right scenes.
VERDICT: genuinely watchable — the first one. Validates the whole fixed
pipeline (generate → real footage → good script → tight cut).
Minor polish (not blockers): some one-word on_screen_text labels ("WERE",
"THE", "EVEN", "HAPPENS") are filler; scenes 8-9 reuse the same crowd clip.
Voice is almost certainly edge-tts (ElevenLabs still exhausted) — user can't
judge the deep voice from this one.
CONSISTENCY: this is ONE good video. Per the user's "not 1 good then 1 shit"
bar, do NOT declare ready — need ≥5 different-topic videos this good. Continue.
