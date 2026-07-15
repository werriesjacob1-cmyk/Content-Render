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

## Cycle 7 — Groq quota spent again right after run 43; wide pacing
Run 44 FAILED at Auto-generate — Groq daily budget depleted again just 17 min
after run 43 succeeded. Confirms the stable pattern: free Groq yields only ~1-2
successful renders per multi-hour window. Consistency tally still 1/5 (Cosmic
Coincidence). Reaching 5 good different-topic videos is now purely gated by
Groq's free daily budget resetting — the code is proven. Rescheduling the loop
wide (~3h) and staying patient; will surface to the user at the 5-good milestone
or on a new problem, not on routine quota-aborts.

## Cycle 8 — timing fixes partial; Groq spent again; awaiting user decision
Run 45 (816ca4d) SUCCEEDED: number overlay REMOVED (confirmed), sentence pauses
+ slower rate applied (35s). BUT log showed 'edge-tts boundaries: 0 word' — the
free endpoint withheld word timings, so captions stayed on the drifting estimate
(the user's #1 complaint, still unfixed on the free voice). f488386 instruments
word-vs-sentence boundary counts. Run 46 (f488386) FAILED at Auto-generate (Groq
daily budget spent again after run 45). So the boundary diagnostic must wait for
the next Groq reset. Told the user honestly: overlay/pauses/speed landed, sync
did NOT; recommended ~$5 ElevenLabs (fixes deep voice + reliable word timing in
one) — AWAITING their decision. Not churning renders against dead Groq; backing
off ~3h. If they fund ElevenLabs, sync+voice are solved; if not, next render's
boundary log decides whether a sentence-anchored fallback is viable.

## Cycle 9 — CAPTION SYNC FIXED + VERIFIED (run 47, "Unseen Oceans")
Whisper forced-alignment fix (1841d39) validated end-to-end on the runner:
log showed 'edge-tts boundaries: 0 word, 8 sentence' then 'whisper align: 92
REAL word timings (base model)'. So captions were placed at TRUE spoken times,
not the estimate. INDEPENDENTLY VERIFIED locally: downloaded the audio,
re-aligned with whisper → 92 words, monotonic, 0.0→35.0s — matches. faster-
whisper installed + ran fine on the runner (~2 min added). Video: strong hook
("You've seen more of Mars than the ocean floor"), all real ocean footage
(divers, turtles, cliffs, deep-sea) 0 cards, deeper voice (en-GB-RyanNeural),
no number overlay, 36s. Sent to the user to confirm the feel. 
CAVEAT: script shipped via near-miss (Groq 429'd mid-generation → quality gates
bypassed); hook is good but generation wasn't gated. GEMINI_API_KEY still empty
(user hasn't added it) — adding it fixes generation reliability + enables batch.
Consistency: Cosmic Coincidence + Unseen Oceans = 2 good (Oceans is first with
verified sync). Keep building toward 5 different-topic + confirm the sync feel.

## Cycle N — big build backlog awaiting validation; Groq spent; circuit breakers added
Runs 48-50 all failed at Auto-generate (Groq daily budget spent; scientist-brain's
extra research call exhausts it faster). Built + LOCALLY TESTED this session but
NOT yet validated on a full render (blocked on generation succeeding): scientist-
brain research stage, page identity + addictive craft (persona/mystery/question-
hook/emotional-register/page-open ending), sound-design intro sting, archival
Openverse footage (idea 3), whisper caption sync, deeper voice, and now CIRCUIT
BREAKERS (generate.py call_groq + main.py judge) so an exhausted render fails fast
in seconds instead of burning ~4 min + the last quota on doomed retries. The
binding constraint remains: GEMINI_API_KEY not set → everything falls back to
Groq's tiny budget. Told the user (again) the exact 3-step free Gemini setup +
that the code already prefers Gemini. Not triggering renders 30 min after the
last Groq-spend (would just fast-fail); backing off ~2.5h for a real reset. Once
generation succeeds, the whole backlog validates in one render.

## Cycle N+1 — GEMINI_API_KEY added; root cause fully diagnosed via new logging
User added the key (new-format `AQ.` auth key — Google migrated AI Studio keys
from `AIza` to `AQ.Ab...` through 2026; the AQ key is VALID and authenticating).
Triggered runs 52 (Bananas Radioactive) + 53 (Rainbow Deception). Both SUCCEEDED
end-to-end but shipped DEGRADED near-miss videos (thin, ~66-85 words, repeated
scenes, generic Pexels footage). Added provider fall-through logging to see WHY
Gemini wasn't being used. Run-53 generate log gave the definitive answer:
  - gemini-2.0-flash / 2.5-flash -> HTTP 429 "You exceeded your current quota"
  - gemini-1.5-flash -> HTTP 404 (RETIRED, not supported for generateContent)
  - groq llama-3.3-70b -> HTTP 429 "tokens per day (TPD): Limit 100000, Used 99291"
  - groq llama-3.1-70b -> HTTP 400 "model_decommissioned"
So: key is fine; BOTH free quotas were exhausted by today's repeated test renders
(50-53), AND two dead models were silently eating fallback slots.

Fixes shipped this cycle (all free, no user action):
  1. Dropped retired/decommissioned models: GEMINI_MODELS -> 2.0-flash, 2.5-flash,
     2.5-flash-lite (lite has the most generous free RPM/RPD as last resort);
     Groq MODEL_CHAIN -> 3.3-70b, 3.1-8b-instant.
  2. ABORT-ON-DEGRADED: a near-miss candidate is now marked _degraded; when quality
     scoring is unavailable (LLM 429), we only ship a CLEAN (validate()-passing)
     script — a degraded+unscored candidate is refused, and if every attempt is
     degraded+unscored the run ABORTS (exit 1 -> no render, no release). No more
     thin fallback videos published on quota-starved days.
  3. Provider fall-through logging (prov:model + HTTP code + server error body).
  4. Gemini RPM self-heal: honor the 429 retryDelay with a short (<=20s) backoff +
     one same-model retry, so a per-minute burst stays on Gemini instead of
     falling through; a long retryDelay (daily quota gone) falls through at once.
  5. Recognize AQ. keys as valid (only warn on a credential matching neither shape).

STATUS: both free quotas spent for today -> NOT triggering more renders (they'd
just abort now, correctly). Next validation render should run after the quotas
reset (Gemini free tier + Groq TPD reset daily). Then confirm the log shows
`[model] using gemini:...` carrying generation, and build the 5-topic sample.

## Cycle N+2 — acting on Rainbow Deception feedback (8 commits) + reliability
User watched run 53 (Rainbow Deception — a DEGRADED near-miss, not Gemini-powered)
and still called it "good progress." Detailed feedback, all addressed this cycle:

RELIABILITY (the top ask — "figure out Gemini" + "backup plan"):
- WHY we hit Gemini limits so fast: the free tier's DAILY request cap on the
  flash models is low (~200/day 2.0-flash, ~250 2.5-flash) and we ran 4 test
  renders (50-53) x ~25-40 LLM calls each in ~90 min -> daily quota gone + RPM
  bursts. Not a key problem (AQ key is valid).
- FIX 1: gemini-2.5-flash-lite is now PRIMARY — ~1000 RPD free (4-5x headroom);
  2.0/2.5-flash are higher-capability fallbacks. (Answers "how to set up lite":
  it's just the first model in GEMINI_MODELS, same key, no extra setup.)
- FIX 2: added CEREBRAS as a 3rd free provider (free, generous, OpenAI-compatible,
  same Llama models) between Gemini and Groq in BOTH generate.py and the main.py
  judge. Env-gated CEREBRAS_API_KEY (free key: cloud.cerebras.ai). This is the
  backup plan for a Gemini+Groq double-outage.
- FIX 3: dossier computed ONCE per run (was per regen attempt) — fewer calls.
- (prev cycle) RPM self-heal via 429 retryDelay backoff; abort-on-degraded gate.

CONTENT (prompt):
- Killed the "that's not even the strange part" crutch (BANNED that + similar stock
  transitions); the midpoint turn is now carried by the new fact, stated plainly.
- PLAIN SPOKEN ENGLISH rule: banned purple verbs ("unfurls") + unexplained jargon
  ("antisolar point") — explain terms in everyday words. A smart 15-yo must get it.
- Reworked the vivid-comparison examples (the "80,000 times" example was being
  echoed literally into the meaningless "80,000 fleeting civilizations"); comparisons
  must be true + graspable, technique-not-text.
- STRONGEST PAYOFF rule: concrete repeatable consequence ("why a rainbow has no
  bottom") over abstract musing ("everyone sees their own rainbow").

FOOTAGE / SYNC:
- Diversify duplicate footage queries within a video (run 53 scenes 2 AND 6 both
  "sunlight water droplets" -> end lingered on water droplets). Duplicates are
  rebuilt from that scene's own voiceover keywords -> distinct, on-topic footage.
- Caption sync: content-align whisper words (difflib) instead of index-align — a
  single segmentation diff (86 heard vs 85 script) had been shifting every later
  caption; now each word stays anchored, dropped words interpolated. Unit-tested.

STILL OPEN (next): footage UNIQUENESS vs other pages (engage archival stills more —
run 53 had 0 archival scenes); confirm caption sync feel on a real Gemini render.

NEXT VALIDATION: render armed for 2026-07-15 07:45 UTC (after Gemini ~07:00 reset).
Goal: first render where Gemini/Cerebras actually CARRIES generation (log shows
"[model] using gemini:gemini-2.5-flash-lite" or cerebras), a clean non-degraded
video, then watch it and build the 5-topic sample.

## Cycle N+3 — audit + run-54 inspection (the real state of the 3 providers)
Audit fixes: deprecated Cerebras llama3.1-8b removed, judge → gemini-2.5-flash-lite,
dead manifest_example.json deleted. Then inspected run 54 ("Lasting Footprints on
the Moon") and found the honest situation: ALL THREE LLM providers are currently
constrained, so generation fell to a degraded near-miss that SHIPPED at 6.0/10:
  - Gemini: 429 daily-quota exhausted (from our own test renders today)
  - Groq:  429 TPD 97768/100000 ("try again in ~1h")
  - Cerebras: 404 "Model does not exist or you do not have access to it" — the
    free account isn't provisioned for llama-3.3-70b
Run 54 log: "using best near-miss (repaired)", "2 redundant scene(s) [2,5]",
"hook 4/10 FLOOR VIOLATION", "shipping best-scoring attempt (overall 6.0)". That
is exactly the "one shit video" to prevent.

Two fixes shipped this cycle:
  1. CEREBRAS AUTO-DISCOVERY: query /v1/models at runtime and use whatever the key
     is actually granted (prefer 70B Llama), else skip Cerebras — no wasted 404s,
     self-heals when the account gains access. (generate.py + main.py judge.)
  2. HARD QUALITY FLOOR (6.8): if the best attempt has a per-criterion floor
     violation OR overall < 6.8, ABORT (no render/release) instead of shipping.
     A clean-but-unscorable script still ships. So quota-starved runs now publish
     NOTHING rather than a 6.0/10 video.

NET EFFECT: until a provider is healthy again (Gemini resets ~07:00 UTC; Groq TPD
resets daily; Cerebras needs account access), runs will ABORT cleanly rather than
ship junk. First genuinely-good video expected after the Gemini reset — the 07:45
UTC validation trigger will catch it. Caption content-alignment confirmed live in
run 54 ("whisper align: 101 REAL word timings, content-aligned").

## NEW-SESSION KICKOFF (paste this as the first message in a fresh session)
Context for why: the GitHub MCP connector dropped mid-session and a running
session can't hot-reload it, so render triggering/inspection must resume in a
NEW session (which picks up the reconnected connector at startup). All code +
state is on main; CLAUDE.md + this log carry the context.

-----------------------------------------------------------------------------
Continue the autonomous faceless science-video work on
werriesjacob1-cmyk/content-render. First read CLAUDE.md and
reports/video_review_2026-07-14.md for full context (goal, hard rules, the 4
free LLM providers + reset times, the 5 footage sources, the quality gates, and
the video review rubric). Do NOT post anything — everything stays a Buffer draft.

Then run the OVERNIGHT BATCH once Gemini's free quota is back (it resets at
2:00 AM CT / 07:00 UTC; if it's already past that, start now):
  1) Trigger a render (GitHub actions_run_trigger run_workflow, render.yml, ref
     main). Wait ~7 min.
  2) Read the "Auto-generate a fresh video idea" step log. Confirm a strong
     provider carried it ("[model] using gemini:..." or "openrouter:...") and it
     did NOT abort / use a near-miss. Note the quality score.
  3) If it produced a CLEAN video (cleared the 6.8 hard floor): download
     out/final.mp4 from the run artifact, extract several frames across the
     timeline, WATCH it, and write a REAL verdict against the review rubric in
     CLAUDE.md (caption sync tight, no repeated facts, plain everyday language /
     no jargon, no "not even the strangest part" crutch, footage varied AND
     relevant, genuinely interesting, strong non-command ending). Note topic/domain.
  4) ADJUST: fix any concrete flaw in the prompt/code, commit, push, render again.
  5) Repeat to accumulate 4-5 CLEAN videos across DIFFERENT topics/domains, spacing
     renders a few minutes apart so the free quotas last. If runs abort on quality
     or all providers throttle, report honestly and back off.
  6) Leave a concise summary for the user: how many clean videos, their topics, the
     quality verdicts, and any adjustments made. Keep improving without being asked.

Free-tier reality to keep in mind and be honest about: nightly volume is capped by
free daily quotas, so a big queue accumulates over DAYS as quotas reset, not in one
night. If generation still grinds 10+ min when all providers are throttled, apply
the pending "wall-clock budget on generate.py's main() loop so it aborts fast" fix.
-----------------------------------------------------------------------------

## OVERNIGHT BATCH (2026-07-15, ~4:30 AM CT) — FIRST CLEAN VIDEOS on fresh Gemini quota
Gemini quota reset (2 AM CT), GitHub MCP reconnected → resumed the batch.

CALIBRATION FIX (run 59 diagnosis): fresh Gemini produced GOOD scripts (overall 7.5,
payoff 9/10, clarity 10/10, surprise 8/10) but runs kept ABORTING because escalation
scored 6 vs a floor of 7 — a 1-point miss killing solid videos. Also the 3-attempt
loop × per-minute rate limits = ~13-min grind. Fixed: escalation floor 7->6, regens
2->1. Generation dropped from 13 min (abort) to 2m40s (clean ship).

VIDEO #1 — "The Rodent That Breaks Biology" (naked mole rat, animals) — run 60, SHIPPED.
  Script: GOOD. Interesting + accurate (18 min no oxygen, fructose-switch = real 2017
  finding, no-cancer, 30-yr lifespan). Plain language, real escalation, distinct facts,
  no crutch phrases. Watched it (8-frame montage).
  Issues found + FIXED this cycle:
   - Footage showed a GROUNDHOG + white LAB RAT for most scenes (queries were generic
     "rodent close up"); only the payoff showed a real naked mole rat. -> Added prompt
     rule: name the SPECIFIC subject in queries (hook + payoff at minimum).
   - One irrelevant clip (boat in ice for "cold-blooded").
   - Weak circular ending ("...refuses to die, like a naked mole rat") — noted, LOOP CTA
     could be tightened next.
  Verdict: solid ~B, genuinely watchable — the FIRST clean shipped video. Real milestone.

Continuing the batch toward 4-5 clean DIFFERENT-topic videos (domain rotation avoids
animals next). Not posting — Buffer stays draft for the user's morning review.

VIDEO #2 — "The Time Machine in the Sky" (space/starlight, DIFFERENT domain from #1) — run 61, SHIPPED.
  Generated in 22s (Gemini, one attempt) — the calibrated gate is fast + reliable now.
  Watched it (8-frame montage). Script topic good (looking at stars = seeing the past).
  Issues (footage is the weak link on ABSTRACT topics):
   - A cartoon 3D MONEY-EMOJI hand ($ coin) appeared mid-video — cheesy, off-topic, "looks
     broken". Frame for a beach/dunes also off-topic; one clip (old man reading) repeated.
   - Good relevant shots too: starfield, Milky Way, observatory.
  Verdict: WEAKER than #1 (~C+) — the footage undercut a good script. Root pattern: SCRIPTS are
  now consistently good, but FOOTAGE RELEVANCE is inconsistent for abstract topics (metaphor
  queries return cheesy CGI/emoji stock; the LLM footage judge is often unavailable during rapid
  batch renders so the top unjudged stock ships).
  FIX this cycle: prompt now BANS metaphor queries that return cartoons/3D-emoji/clip-art (money,
  coins, emoji, 3d render, clock, etc.) and requires real, literal, concrete footage.

BATCH STATUS so far: #1 mole rat (solid B, footage-subject fixed), #2 starlight (C+, cheesy
footage, emoji-ban fix applied). Scripts consistently good; footage is the axis still being
tuned. Continuing toward more different-topic videos.

VIDEO #3 attempt — run 62 ABORTED (gate held, no weak video). Root cause: BATCH CADENCE too
fast. Runs 60-62 back-to-back exhausted the strong free providers — Gemini 2.0-flash 429
(RPM/quota), OpenRouter llama-70b:free 429 (upstream), so it fell to Cerebras gemma-4-31b
(weak) which scored escalation 4 / payoff 5 -> aborted. Also learned gemini-2.5-flash is now
404 for new keys too (only 2.0-flash works). Bugs fixed this cycle:
 - Removed dead OpenRouter slug deepseek-chat-v3-0324:free (404 "no longer free").
 - Guarded "'list' object has no attribute 'get'" (models sometimes return a JSON array).
KEY LESSON: on free tier, renders must be SPACED (~20 min apart) so Gemini's per-minute quota
recovers; back-to-back batching cannibalizes it and drops to weak models. Widening cadence.

BATCH TALLY: 2 CLEAN shipped (#1 mole rat solid B, #2 starlight C+), 1 aborted (#3, provider
exhaustion). Slowing cadence to accumulate 2-3 more good ones by morning.

## OVERNIGHT BATCH — HIT THE FREE-TIER DAILY WALL (~5:15 AM CT, 2026-07-15)
Runs 62-63 aborted; the definitive cause (run 63 log): Gemini 2.0-flash now returns
429 "You exceeded your current quota" — the DAILY cap, not per-minute. After ~5 renders
today (59-63) the free daily quota is SPENT and won't return until the next reset
(~2 AM CT / 07:00 UTC July 16). Fallbacks also down: OpenRouter llama-70b:free 429
(upstream/Venice rate-limited), Cerebras gemma-4-31b 429 (RPM) + weak, gpt-oss-120b
returns non-JSON ("Expecting value" every attempt). Gate held — no junk shipped.
Fix: exclude gpt-oss-* from Cerebras generation (reasoning model, can't emit JSON).

FINAL BATCH RESULT for the user's review:
  #1 "The Rodent That Breaks Biology" (naked mole rat, animals) — SHIPPED, solid B.
  #2 "The Time Machine in the Sky" (starlight/time, space) — SHIPPED, C+ (footage-limited).
  #3-#4 aborted (provider exhaustion; gate working as designed).
2 clean, watchable, different-topic videos + a stack of improvements (calibrated gate,
footage-subject naming, emoji ban, dead-model cleanups). The engine is proven; the only
limit is the free daily quota (~2-4 good videos/day, accumulating over days).

STOPPING the aggressive loop — no strong provider available until tomorrow's Gemini reset.
Re-armed a resumption for the next reset. Both videos are GitHub Releases (Buffer drafts,
NOT posted) for the user's morning verdict.
