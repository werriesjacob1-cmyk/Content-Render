# CLAUDE.md — project state & how to continue (read this first)

This repo is an **autonomous faceless-video pipeline** for a short-form science
channel. A new session should read this file plus the latest
`reports/video_review_*.md` to catch up, then continue the work below.

## The goal (standing, do not drift from this)
- Produce **consistently GOOD, genuinely interesting** short science videos across
  **different topics** — not "1 good then 1 bad." The page should feel addictive
  in both presentation AND content ("scientist brain," strange-but-true facts).
- **Do NOT post yet.** Everything publishes to a GitHub Release that a Zapier/Buffer
  hook picks up **as a Draft**. Posting happens only after the profile is
  consistently good and the user approves.
- **Free tier only.** The user does NOT want to pay for anything until the
  platforms show traction. Maximize free providers; never require a paid key.
- **Consistency over cadence:** better to publish NOTHING than a weak video. The
  quality gate is allowed (and expected) to abort a run.

## Overnight session 2026-08-04 to 08-07 — first render-verified successes + one more real bug
Continuation of the same overnight push (multi-day due to session gaps, not separate work).
The 2x/day cron kept firing on its own per the "no more triggered renders" instruction; two
of those runs SUCCEEDED and were downloaded + watched frame-by-frame end to end for the
first time this session (previous renders all aborted before reaching main.py).

- **Render 233, "The Organ That Grows Back"** (commit 57d50e2, 37.4s, body/visceral):
  **A-/B+**. Every one of 7 scenes landed real Pexels footage (judge 6-9/10), ElevenLabs
  succeeded (81 word timings), captions tight (QA judge 10/10), payoff is a genuine
  mechanism ("an invisible biological sensor stops the expansion") not a number. Two fal
  AI-video attempts (scenes 1 and 7) were CORRECTLY rejected by the vision-relevance check
  (0/10, 2/10) and fell back to strong stock -- the safety net worked. Real flaw: the
  payoff scene's stock footage (generic hospital/brain-scan imagery) isn't literally
  liver-specific -- inherent to how hard "an invisible sensor" is to film, not a bug.
- **Render 230, "Why Water Breaks the Rules of Physics"** (commit 61a81b0, 40.5s,
  chemistry/awe): **A-/B+ with one real, now-fixed defect.** Scored a clean 7.71/10 on
  attempt 3 (no rescue needed) -- the tightest script reviewed this session, genuine
  escalation ending on a resonant idea. ElevenLabs succeeded (85 word timings). BUT: the
  fal AI hero shot accepted for scene 1 ("ice floating water") had garbled, hallucinated
  pseudo-text baked into the frame (visible on inspection: "...ATE", "FE БSLMAA",
  overlapping the caption) -- exactly what the final-QA judge's own report flagged
  ("Frame 1 contains garbled, unreadable text baked into the source video footage"), but
  nothing upstream screened for it before shipping.
- **Fixed the garbled-text gap**: `main._fal_clip_relevant`'s vision check only ever asked
  Gemini "does this match the subject" -- never "is the frame itself clean". Text
  hallucination is a well-known, SEPARATE AI-video failure mode from subject accuracy (this
  exact clip would have scored well on relevance alone). Extended the same single-frame
  check with an independent `garbled_text` field and reject on EITHER failure now.
  Extracted the decision into a pure `_fal_clip_verdict()` (unit-tested without mocking the
  network call, matching this session's established pattern). **880 zero-quota checks
  passing (+8)**, pushed to `main`.
- Both videos' full final.mp4 sent to the user directly (SendUserFile) alongside a written
  rubric-based rating -- this is the first time in the session a complete render→watch→
  rate→fix loop closed all the way through on real render output, not just logs.

## Overnight session 2026-08-04 — real-render bug hunt after the Gemini top-up
Driven by "run render, then rate every aspect honestly" + "work through the night."
Two renders right after the Gemini top-up (runs 30942748084, 30947501802, both
commit c7b37dd) still ABORTED — correctly, per the quality gate, but the logs
exposed three concrete, fixable bugs (not just inherent model variance). All
fixed same night, test-verified (**872 zero-quota checks**, up from 857), pushed
directly to `main` between renders (pushing never triggers a render — safe to do
without the user's live confirmation each time).

- **Gemini model ranking bug, CONFIRMED both broken and then fixed live**: the
  first render still showed `gemini_models()` picking `gemini-flash-lite-latest`
  (deliberately weaker/cheaper) over `gemini-3.6-flash` (full, non-lite) for a
  rescue attempt, because the old ranking sorted purely on whether a name
  contained `"-latest"` with no idea "lite" is a quality-tier signal, not a
  freshness tag. Extracted `_rank_gemini_models()` (pure, unit-tested): full
  models before ANY lite variant regardless of `-latest` tagging; preview/exp
  ids stay lowest even when `-latest`-tagged (the function's own stated intent
  the old code silently broke). **Confirmed working in the very next render**:
  discovery returned `['gemini-flash-latest', 'gemini-3.6-flash',
  'gemini-3.5-flash']` — no lite model in the top 3 at all.
- **Prompt self-contradiction (real recurring failure)**: gemini-flash-latest
  opened a caption with "Did you know" TWICE in one generation cycle, correctly
  caught both times by `BANNED_HOOK_OPENER_RE` (burning two attempts) — despite
  the prompt explicitly banning that exact phrase. Root cause found nine lines
  above the ban: the COMMENTS engagement rule's own worked example for a
  "binary question" was literally `'Did you know this — yes or no?'` — a
  positive example using the exact banned phrase. A second copy of the same
  rule (`CTA_ENDING_RULES["COMMENT"]`) had a different but also broken example
  (`'Would you or no?'`, not even a complete question). Fixed both to `'Real or
  myth?'` — a model pattern-matches a concrete positive example much more than
  an abstract ban nine lines away.
- **`UNSTOCKABLE_Q` false-positive on physical "___ system(s)" queries**: two
  renders rejected perfectly filmable queries — `'solar system planets'`,
  `'tree root system soil'` — as "un-filmable" because the regex banned the
  bare word "system(s)" anywhere (added for the render-181 "resilient
  communication systems" incident, an ABSTRACT system with nothing physical to
  film). Fixed with a negative-lookbehind exemption list (solar/root/river/
  weather/mountain/cave/reef/canyon) for known-physical systems, leaving every
  abstract/functional system (nervous, digestive, communication, economic...)
  banned exactly as before. Verified against BOTH the two real false-positive
  queries AND the original render-181 regression test in the same test run.
- **Also cleaned up stale docs**: CLAUDE.md's "Known pending improvements" list
  had two items that were actually already shipped in earlier sessions
  (footage brightness lift, series/binge architecture) — removed, with a note
  to cross-check this section against actual code rather than trust it blindly.

**Still not render-verified end-to-end**: neither render reached `main.py` (both
aborted at script generation), so Pollinations/iNaturalist/the FAL cap raise/
final-QA memory persistence from the prior session remain unexercised by a
successful run. A NEW session (or the next cron) should check the next
completed render's logs for all of the 2026-08-03 session's still-unverified
items PLUS confirm these three fixes hold: no Lite Gemini model used unless
nothing stronger is available, no "Did you know" mechanical rejections, and no
"un-filmable terms" rejection on a query that's actually a real physical
subject.

## Session 2026-08-03 — free footage sources, final-QA memory persistence, funding crisis
Driven by "photos are boring, we need free relevant video" + a real live incident with
paid-provider funding. Branch `main` directly (established pattern this session — the
render.yml cron runs off `main`, so fixes land there, not a feature branch). All
test-verified (**849 zero-quota checks**, up from 825).

- **ElevenLabs CONFIRMED WORKING** (render 223, commit f1e5926): the user re-updated the
  secret and it finally cleared — `ElevenLabs SUCCESS (91 word timings)`. The long-running
  "still 401ing after the key update" saga from prior sessions is resolved; no code change
  needed, it was purely a stale/wrong key value.
- **Final-QA verdict now persisted to memory** (`main._persist_qa_to_memory`, called right
  after `_final_qa_check()` in `main()`): the audio-listening judge's report
  (footage_matches_narration, narration_flow, visual_variety, biggest_issue) previously
  only reached the ephemeral `out/qa_report.json` release asset; now it's merged into
  `memory_<page>.json`'s history entry for that video_id (both on the abort AND success
  path), so a repeatedly-weak fact/domain leaves a trace for future sessions to learn from.
  `render.yml`'s "Commit footage dedup history" step now also stages `memory_*.json`.
- **Pollinations.ai (free Flux) as the AI-illustration provider, tried BEFORE paid Imagen**
  (`main._pollinations_image`, gated on `POLLINATIONS_API_KEY` — free signup at
  enter.pollinations.ai, no billing ever; user has set the secret). Genuinely free image
  API, no per-call cost, unlike the existing Imagen fallback (billed per image, capped at
  `MAX_AI_IMAGES`). Imagen now only fires if Pollinations is unset/fails/capped. Shared
  subject-anchored prompt (`_illustration_prompt`) extracted so both providers stay
  anchored on the scene's literal `search_query`, not a metaphorical voiceover line.
- **iNaturalist as the FIRST archival-still source**, ahead of Openverse/Wikimedia
  (`main._inaturalist_image`). No API key, explicitly automation-friendly (unlike Pixabay
  — see below). For the (mostly animal/plant) topic bank, a real species-verified
  observation photo beats a generic keyword-matched still. **Live-tested before building**:
  most iNaturalist observations are `cc-by-nc` (non-commercial, unusable on a monetized
  channel) — the query's `photo_license` filter is NOT trusted alone;
  `_inaturalist_safe_photo_url` re-checks each candidate PHOTO's own `license_code` before
  download (pure/testable helper).
- **Ruled out after live research, not just docs**: Pixabay's API terms explicitly
  prohibit automated/unattended calls (exactly what our CI cron is — confirmed live, not
  assumed); Higgsfield has no free-tier API/CLI access at all (paid Creator-plan-only,
  and its free tier is watermarked besides); Pollinations' own VIDEO endpoint is
  paid-gated (Pollen credits), only its image endpoint is genuinely free. Also live-tested
  the ALREADY-integrated Wikimedia video source against real scene queries and confirmed
  its recall is genuinely thin ("octopus swimming" → 0 hits, "shrimp claw macro" → 0
  hits) — the free-video ceiling is close to already reached with Pexels/NASA/
  Wikimedia/Archive; that's WHY fal.ai AI-video gap-fill exists, not a gap in what's wired up.
- **`FAL_MAX_CLIPS` raised 2 → 4** (repo Variable, zero code change — user set it). fal.ai
  is a real, funded account (`$14.44` balance confirmed via the user's own dashboard,
  `~$0.18/day` burn at the old cap) — doubling the cap roughly doubles burn to `~$0.36/day`
  (~40 days runway), spending an already-committed balance to directly convert more weak
  scenes into real AI video instead of a still, which is the one lever that actually
  answers "we need more real video" (Pollinations/iNaturalist only improve the STILLS tier).
- **GEMINI FUNDING CRISIS (live incident, resolved)**: mid-session, Gemini started 429ing
  on EVERY model + grounded search, with the code's own RPM self-heal (`_gemini_retry_delay`
  / `GEMINI_RPM_MAX_WAIT`) never firing — meaning Google returned no/long `retryDelay`, the
  signature of real exhaustion, not a transient per-minute burst. Checked
  `aistudio.google.com/usage` → "Default Gemini Project" credit balance was **-$0.01**
  (the earlier ~$10 top-up fully drawn down — July's total usage was only ~$0.50, so this
  wasn't a spend spike, just a low balance finally hitting zero after this session's own
  extra manually-triggered renders on top of the 2x/day cron). User added **$10** to
  Gemini; a render was immediately triggered to confirm generation recovers. **This is the
  key lesson for future sessions: Gemini is CHEAP (~$0.50/month at normal cadence) but NOT
  unlimited even on the paid tier — check `aistudio.google.com/usage` FIRST on any
  suspicious wall of 429s before assuming it's a code/quota-config bug.**
- **OpenRouter remains fully depleted** (`anthropic/claude-sonnet-5` / `openai/gpt-5` both
  hard 402 "can only afford ~70 tokens" on every render this session) — user explicitly
  declined to re-fund it ("I don't want to fund OPENROUTER again unless absolutely
  necessary"), reasoning: the quality-floor gate means a degraded writer produces MORE
  ABORTS (fewer videos shipped), not worse videos that actually publish — a cadence cost,
  not a quality cost, and Gemini being funded again may make OpenRouter unnecessary since
  it was only added as a backstop for Gemini's free-tier unreliability in the first place.
  Do NOT recommend re-funding OpenRouter without the user raising it first.

**NOT yet render-verified end-to-end**: everything above (Gemini recovery, FAL_MAX_CLIPS=4,
Pollinations, iNaturalist, final-QA memory persistence) landed in code/config across several
renders that each aborted before exercising all of it in one pass (one aborted at final-QA
before the memory-persistence code existed; one aborted at generation before Pollinations/FAL
raise could be tested). A render was triggered immediately after the Gemini top-up — if this
session is gone, a NEW session must check that render's logs for: `[model] using gemini:...`
succeeding without a 429 wall, up to 4 `[fal] AI video clip` lines, either
`"Pollinations (free) + Ken Burns"` or `"iNaturalist CC image + Ken Burns"` appearing,
`ElevenLabs SUCCESS`, and a `final_qa` sub-dict in the newest `memory_science.json` entry.

## Overnight batch — 2026-07-25/26 (POP + reliability + content quality)
Long session driven by LIVE TikTok analytics + user feedback. All merged to main
(PRs #23–#31+), 159 zero-quota checks. Shipped:
- **Reliability (PR #23)**: `call_groq` waits out per-minute 429s on strong writers
  before falling to a weak model — "always ship a video" without dropping the bar.
- **Faster cutting**: `build_scene` cuts between 2–6 sub-clips/scene
  (`SCENE_MULTICLIP`, `CLIP_SECONDS=1.9`, `MAX_SUBCLIPS=6`). Footage-capped on
  narrow topics (few distinct stock clips → cycles).
- **Video over photos**: `fetch_clip` `accept_best=True` + `SOFT_VIDEO_FLOOR=3` —
  a real moving clip beats a static archival photo; stills are now the exception.
- **Auto-cover**: `main.make_cover()` → `out/cover.jpg` (most colorful clean frame +
  `hook_headline` burned on, yellow accent, `@CHANNEL_HANDLE`), attached to release.
  Kills the "black tile on the grid" problem.
- **No double caption**: removed the on-screen hook-headline overlay (clashed with
  the karaoke captions). `hook_headline` is COVER-only now.
- **No black stretch**: per-sub-clip `_shadow_lift` (dark sub-clips reused the
  primary clip's lift → read black mid-scene).
- **Animated captions**: per-word overshoot bounce; keyword pops bigger + gold.
- **Music**: `_ensure_music_bed()` — `MUSIC_URL` var (paste a royalty-free link) >
  committed per-profile track (the bundled `music_*.mp3` are weak 8s loops —
  REPLACE) > synthesized license-safe pad. Never silent now. `music_vol` 0.10→0.14.
- **Cut SFX**: subtle pink-noise whooshes at scene boundaries (`SFX_CUTS`,
  `_make_cut_whooshes`) — needs the user's ears.
- **Punchier grade**: science saturation 1.12→1.30, contrast 1.08→1.16,
  `zoom_speed` 0.0006→0.0009.
- **Content quality (biggest)**: "big/small is NOT interesting" — removed the
  `SCALE_SHOCK` hook, added the WHO-CARES test, rubric scores magnitude-only ≤3.
  Curated `topic_bank.json` (now **103**): removed card_shuffle_52,
  more_trees_than_stars, eye_colors, phone_vs_apollo; added wood_frog_freeze,
  stomach_self_digest, cleopatra_timeline. FRONT-LOAD-THE-SHOCK hook rule (the 0:01
  drop-off is the #1 retention lever; banned "did you know"/wind-up openers).
- **Analytics loop**: `perf_science.json` has 4 videos — turtle 0.206 (best, 2
  follows) > space 0.138 > jellyfish 0.109 > color 0.061. Pattern: weird/visceral/
  concrete + scenario hooks WIN; passive/abstract/scale LOSE.

OPEN for the user: set repo Variables `CHANNEL_HANDLE=@waitwhatscience` and
`MUSIC_URL` (a royalty-free track); confirm cut-whoosh + music by ear; add trending
TikTok audio at upload. **NOT yet render-verified end-to-end** on a FRESH-topic
render (the deck re-renders were replays of an old magnitude script) — a self-check
trigger watches the 09:00 UTC cron; if this session is gone, a NEW session must
verify that render against every bullet above.

## Session 2026-07-26 (afternoon) — PAID tier, reliability, analytics loop
Driven by live TikTok analytics + user watching each render. Branch
`claude/epic-edison-jybjd1`; all test-verified (**200 zero-quota checks**). The
user funded OpenRouter (~$5) + fal (~$11-23) and wants **2-3 postable videos/day**.
Shipped:
- **Paid OpenRouter primary writer** (see provider #2 above) — the fix for the
  string of aborted renders (157-159). Render 160 verified at 9.33.
- **COHERENCE hard-gate** (`generate.py`): render 160 ("Pluto's Eternal Orbit")
  scored 9.33 but was INCOHERENT ("your great-grandparents saw Pluto's start, but
  it won't finish" — start/finish of WHAT?). The old rubric's `clarity` only checked
  simple WORDS, not sense. Added a scored `coherence` criterion WITH A FLOOR (6) →
  a confusing script now ABORTS. Writer prompt gains a MAKE-LITERAL-SENSE rule using
  that exact Pluto line as the banned example.
- **fal.ai AI-video gap-fill** (`main.py`, `FAL_KEY` secret set): when a scene's
  stock clip is off-topic (judge < `FAL_RELEVANCE_FLOOR`=5) or missing, generate an
  on-topic AI VIDEO (`fal-ai/ltx-video`, env `FAL_VIDEO_MODEL`) instead of the
  render-160 "girl+rabbit / ocean-waves on a Pluto video". Capped `FAL_MAX_CLIPS`=2/
  video, fires only on weak scenes ($0 on good-stock topics). No key = no-op.
  **NOT yet render-verified** (renders 161/163 aborted before the render step).
- **On-topic cover** (`main.py`): cover now comes from scene 1 (the hook = the
  primary subject), not the most-colorful frame across the whole video (which put an
  OCEAN thumbnail on a Pluto video). Falls back to full body if scene 1 unusable.
- **No fake cuts** (`main.py`): multi-clip only when ≥2 DISTINCT clips exist; a
  single source gets ONE smooth motion (was panning the same Moon photo 3 ways).
- **Cut whooshes OFF by default** (`SFX_CUTS=0`; user disliked them).
- **A/B video length** (`generate.py`, user chose "A/B both"): SHORT (~28-32s, 55-74
  words, 5-8 scenes) vs LONG (~40-46s, 95-110 words, 7-10 scenes), alternating per
  render off memory-history parity (`LENGTH_MODE=short|long|auto`). Word/scene bounds
  are ONE source of truth (build_prompt + validate + near-miss). NOTE render 163
  aborted because SHORT was first shipped with the LONG 7-scene floor (models
  overshot the word cap); fixed to 5-8 scenes for SHORT.
- **8-second retention rule** (writer prompt): analytics show avg watch ~8s on ~40s
  videos — scene 2 must ESCALATE, never explain; "the video is lost in the first 8
  seconds or not at all."
- **Saves + comments in perf memory** (`generate.py` `_perf_score`): jellyfish's 6
  saves + turtle's 3 comments were invisible to generation; now weighted (watch .45/
  follows .22/saves .15/shares .10/comments .08). `--record` aliases save/comment/like.
- **Empty-response retry** (`generate.py`): OpenRouter occasionally returns an empty
  body (twice in render 163) — one immediate re-call before spending the attempt.

**Live analytics recorded** (`perf_science.json`): turtle 0.226 watch / 2 follows /
3 comments (visceral → comments); jellyfish 0.205 / 2 follows / 6 saves (mesmerizing
→ saves); space 0.275 watch / 0 follows (thrill retains but doesn't convert); color
0.122 (abstract = worst). Pattern: **wonder/visceral converts followers; abstract/
passive loses; the 8s cliff is the #1 lever.**

**OPEN**: render-verify SHORT length + fal firing + coherence gate end-to-end (in
progress). Cross-render git contention: do NOT push to the branch while a render runs
on it (concurrent pushes stalled render 161's memory-commit in a push-retry loop).

## Architecture (one render)
`generate.py` (LLM writes a manifest.json script) → `main.py` (TTS, footage,
ffmpeg render → out/final.mp4) → `repackage.py` (7 platform cuts + captions +
funnel) → GitHub Release → Zapier → Buffer (Draft). Driven by
`.github/workflows/render.yml` (manual `workflow_dispatch` + daily `schedule` at
13:00 UTC / 8:00 AM CT). PAGE=science.

## LLM providers, tried in this order — all env-gated
1. **Gemini** (`GEMINI_API_KEY`): models are **auto-discovered** at runtime via
   the ListModels API (`gemini_models()` in generate.py, `JUDGE_GEMINI_MODEL` in
   main.py) — do NOT hardcode a version. A newly-created key is locked to the
   NEWEST models only: `gemini-2.0/2.5-*` all 404 ("not available to new users");
   as of 2026-07 the key resolves `gemini-flash-latest` / `gemini-3.5-flash`.
   `gemini-3.5-flash` is a THINKING model — reasoning consumes `maxOutputTokens`,
   so generation uses `maxOutputTokens: 24000` with thinking ON (a small budget
   or thinkingBudget=0 truncates JSON or tanks quality — learned the hard way in
   runs 103-105). The user has added **paid billing (~$10)** to this key, so it is
   no longer strictly free-tier; spend it deliberately. Generation is grounded on
   live Google Search (`_call_gemini(..., ground=True)`), and the footage judge
   has a **vision** path (`_gemini_vision_pick`) that looks at Pexels thumbnails.
   Resets **midnight Pacific = 2:00 AM CT / 07:00 UTC**.
2. **OpenRouter** (`OPENROUTER_API_KEY`): **NOW PAID + PRIMARY WRITER (2026-07-26)**.
   The free `...:free` slug was discontinued (404). The user funded OpenRouter (~$5),
   so `generate.py` now uses the **paid** slug `meta-llama/llama-3.3-70b-instruct`
   (env-overridable via `OPENROUTER_MODEL`). This is THE reliability fix: Gemini's
   free quota 429s on every model most of the day, and OpenRouter-paid catches it
   with a strong, non-rate-limited writer for a few cents/render. **Render 160
   verified**: OpenRouter carried it, script scored **9.33** on the first attempt
   (vs the 4.67-6.5 the free chain produced before aborting). A 429 from Gemini now
   falls through in ~3 log lines to OpenRouter — Gemini is NOT the bottleneck.
   NOTE: 160 also exposed that a high self-score can hide an INCOHERENT script — see
   the coherence gate in the 2026-07-26 session notes below.
3. **Cerebras** (`CEREBRAS_API_KEY`): models **auto-discovered** via `/v1/models`.
   Only `gemma-4-31b` returns clean JSON; `gpt-oss-*` and `zai-glm-*` reply with
   non-JSON reasoning and are excluded (`cerebras_models()` denylist). RPM-limited
   on free tier; has a per-minute self-heal retry. gemma is weak — it produces
   escalation-4 near-misses that the hard floor rightly aborts, so it's a
   last-resort backstop, not a substitute for Gemini/OpenRouter.
4. **Groq** (`GROQ_API_KEY`): `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`.
   100k tokens/day free.
Provider chain, circuit breakers, and 429/RPM backoffs live in `generate.py`
`call_groq()`. The footage-relevance judge in `main.py` `_groq_chat()` uses the
same providers.

## Footage sources (free), chained in `main.py` `_gather_candidates()`
Pexels (key) → NASA (no key) → **Wikimedia Commons** (no key, video + archival
stills) → **Internet Archive** (no key, documentary film, 45 MB cap) → Coverr
(dormant). Plus Openverse CC stills in the archival-still fallback. Within-video
duplicate `search_query`s are diversified (`_diversify_scene_queries`).

## Quality gates (in `generate.py`) — this is how "no bad videos" is enforced
- `validate()` structural checks + `check_information_gain()` (LLM redundancy) +
  `score_script()` rubric (hook/surprise/escalation/payoff/rewatch/clarity).
- `QUALITY_CRITERION_FLOORS` (hook≥6, escalation≥7, payoff≥6) force regeneration.
- **`QUALITY_HARD_FLOOR = 6.8`**: if the best attempt has a floor violation OR
  overall < 6.8, the run **ABORTS** (exit 1 → no render, no release). A
  clean-but-unscorable script still ships.
- Degraded near-miss + unscorable → also aborts.

## The review rubric — judge EVERY generated video against the user's feedback
Watch the actual video (extract frames + read the script). It must have:
- Captions **tightly synced** to narration (whisper content-alignment is in
  `main.py` `_align_words_by_content`).
- **No repeated facts/numbers** — each scene a NEW point (the "42 degrees twice"
  complaint).
- **Plain, everyday language** — no jargon ("antisolar point") or purple verbs
  ("unfurls"). Explain terms, don't name them.
- **No crutch phrases** — banned: "that's not even the strangest part" etc.
- **Footage varied AND relevant** to what's being said (no lingering on one clip;
  no generic stock that ignores the narration).
- **A concrete, interesting payoff** and a resonant ending — NOT a command
  ("screenshot this") and NOT restating the premise.
- Genuinely interesting "scientist-brain" content, different from other pages.

## How to continue (the loop)
1. Trigger a render (GitHub MCP `actions_run_trigger` run_workflow on
   `werriesjacob1-cmyk/content-render`, `render.yml`, ref `main`), or wait for the
   daily cron.
2. Read the "Auto-generate a fresh video idea" step log. Confirm a strong provider
   carried it (`[model] using gemini:...` / `openrouter:...`) and it did NOT abort.
3. If clean: download `out/final.mp4` from the run artifact, extract frames, WATCH
   it, and write a verdict against the rubric above.
4. Fix any concrete flaw in the prompt/code, commit, push, render again.
5. Accumulate **4–5 clean videos across DIFFERENT topics/domains**, then ask the
   user to review consistency before proposing to post.

## Topic bank
`topic_bank.json` — **104 verified facts across 20 domains** (2026-07-18: deduped
5 twin facts that shared a topic under different IDs, then added 18 high-wow
"leaves-you-thinking" facts weighted to thin domains — math/chemistry/senses/
materials/weather/history/biology/geology/deep_time/plants). Each fact carries
`key_terms` (real names/numbers the script MUST say), a `whatif` question (opens
the curiosity gap — validate() enforces a '?' in the first 4 lines), and a `wow`
escalation detail. `memory_science.json` tracks used facts; `used_footage_science.json`
dedups clips across runs.
Domain selection now dedups by FAMILY (`DOMAIN_FAMILIES`: geology/earth/weather
= one family) so two deep-earth videos don't run back-to-back.

## Zero-quota test suite — RUN THIS before shipping generate.py/main.py changes
`GROQ_API_KEY=x python tests/test_pipeline.py` — **109 checks** over the trickiest
PURE logic (caption content-alignment, footage `_footage_intent` anchoring,
`_diversify_scene_queries`, timing, `validate()` across 5 topic fixtures + broken
ones incl. the 7-scene floor, fast-fail-when-throttled, domain families,
**`critique_script` merge, script-buffer FIFO/empty/malformed, `_xfade_offsets`
math, `_shadow_lift_filter` brightness lift**). No ffmpeg, no network, no LLM.
It already caught a real validate() false-positive.

## Resource-exhaustion resilience shipped 2026-07-22 (branch `claude/epic-edison-jybjd1`)
Render 130 ("Pineapple: The Fruit That Digests You") came out 31s, robotic, weak
(6.83/surprise-4). Root cause was NOT code — **two free resources hit their caps
the same night**, so the pipeline silently ran on its weakest fallbacks:
- **ElevenLabs free credits exhausted** (`401 quota_exceeded`, 102/10000 left) →
  every render falls to **Piper** (robotic — the "choppy narrator" complaint).
  Won't return until the monthly reset.
- **OpenRouter free llama-70b discontinued** (`404`, see provider #2) →
  generation falls to weak `github:gpt-4o-mini`.
Two fixes (both test-verified, **109 zero-quota checks**; render-verify on the
branch before/after merge to main):
- **Voice: edge-tts BEFORE Piper** (`main.py` `tts_full`). edge-tts's Azure
  *neural* voices are free/unlimited and markedly smoother than Piper; Piper is
  kept as the offline last-resort so a render never breaks if edge's endpoint
  403s. edge's slower cadence also lifts the ~31s stub toward ~38s. **`VOICE_ENGINE`
  env** (`edge` default / `piper`) lets the user A/B by ear — NEEDS the user's ears
  to confirm which voice to lock.
- **Script: frugal Gemini quality-rescue** (`generate.py` `main()`). When the free
  chain's best draft is weak (`draft_is_weak()` = below `QUALITY_THRESHOLD` 7.5 OR
  a floor violation) and a paid Gemini key exists, spend ONE grounded Gemini
  attempt before shipping-weak/aborting. Fires ONLY on weak nights ($0 otherwise);
  `_FORCE_GEMINI_GEN` one-shot flag routes `call_groq` to Gemini-first for the
  retry. This is the "use Gemini but be frugal" trade — pennies only when they buy
  back a good video. NOTE: the `--dequeue` buffer path does NOT run the rescue (it
  replays pre-scored manifests), so buffered scripts written under weak providers
  ship as-is; the branch force-push wiped the stale `queue_science/` so live-gen
  (with rescue) runs until buffer.yml refills.
- **Word window 80-100 → 85-115 (target 95-110)** — the ACTUAL cause of the
  aborts. The free models write ~110-140-word science drafts; the old tight cap
  rejected every one, and the near-miss repair trimmed whole SCENES to fit — each
  dropped scene a lost escalation rung → escalation floor violations → aborted
  runs (and render 130 only shipped at 6.83 because ONE attempt trimmed cleanly;
  it was a coin flip). 85-115 matches what the models produce, so a clean draft
  keeps ALL its scenes (escalation) intact AND Gemini's ~105-word rescue drafts
  pass instead of being trimmed to mush. Prompt now says "tighten wording, never
  delete a scene" when over length. Renders ~40-46s on the neural voices.

**MERGED TO MAIN 2026-07-22 (PR #11, squash `71a8aa4`) — render-VERIFIED.** Branch
render 132 ("Turtles Breathe Through Their Rear Ends", animals): edge-tts carried
the voice (ElevenLabs 401'd → edge, NOT Piper), **37.5s** (was 31s), shipped **7.0
with all 8 scenes intact** (no floor violation), whisper recovered 90/90 word
timings, rescue fired + correctly declined a weaker Gemini draft. B/B+ — a clear
step up from render 130 (C+/B−). Still OPEN for the user: (1) **confirm the voice
by ear** (edge vs piper via `VOICE_ENGINE`); (2) ceiling is ~7.0 on free
gpt-4o-mini — Gemini rescue can't lift it much because Gemini ALSO overshoots word
count for this dense format, so the only path to consistent 8.0+ is a stronger
writer (Gemini-first, or a cheap paid script tier) — the user's call.

## Overnight quality batch shipped 2026-07-18 (branch `claude/epic-edison-jybjd1`)
Reviewed render 105 ("Cosmic Proof of Relativity", muon time dilation — Gemini
`gemini-flash-latest` carried it, grounded + vision judge fired; a solid B/B+
with 3 concrete flaws). Fixed the flaws and pushed further. All test-verified
(then 97, now 109 zero-quota checks); **not yet render-verified — do one render
after the 07:00 UTC reset and WATCH it**:
- **CI staging bug (critical)**: `git add memory_*.json manifest.json … queue_*`
  aborts ATOMICALLY when `queue_*` matches nothing (the empty-buffer live-gen
  case), so the manifest + `memory_science.json` history never committed — topic
  diversity silently froze and the branch kept a stale manifest. Split the
  always-present paths onto their own `git add` (render.yml + buffer.yml).
- **Footage brightness (was pending)**: `_clip_luma()` samples across ~8s (not 4
  early frames) and `_clip_too_dark` now rejects a near-black STRETCH too; dim-
  but-real footage (space/deep-sea/night) is **lifted** (`_shadow_lift_filter`,
  a capped gamma/brightness eq, unit-tested) instead of rejected, so no scene
  reads as a black screen and science footage never collapses into text cards.
- **Prompt**: the whatif curiosity-gap is now a HARD mechanical rule mirroring
  validate() (a '?' in the first 4 lines, shown as a statement-hook + question-
  scene-2 pattern) so drafts pass first try; the keyword must be PLAIN search
  words (jargon like "einstein time dilation" is banned — it also pops on-screen).
- **Pacing**: scene floor 6 → 7 (ceiling still 10) to kill single-clip linger
  (run 105 sat 8s on one Roman-ruins aerial) → shorter scenes = more clips.
- **Creativity/relevance**: +2 hook frames (SCALE_SHOCK, COMPARISON_COLLISION);
  vision judge given explicit scoring bands (score 0-3 when nothing matches → a
  re-search fires) + a penalty for text/watermark/cartoon/3D thumbnails.

## Quota-efficiency batch shipped 2026-07-17 (branch `claude/epic-edison-jybjd1`)
User asked to solve free-tier quota fragility. Root cause seen in render 82:
6265-token requests hit Groq's 12000 tokens/MINUTE cap (barely 2/min) + HTTP 413
on smaller-context providers. Shipped (all test-verified, no render needed):
- **Prompt trim ~30%** (`build_prompt`): consolidated 3 duplicate number-passages
  + the 33-line footage block to 20 lines; every unique rule/example kept. Fewer
  input tokens on EVERY LLM call → more fit under the TPM cap, fewer 413s.
- **Merge info-gain + score** (`critique_script`): one Groq call does the
  redundancy gate AND the rubric score (were two). Score stashed on the manifest
  (`_quality`) and reused by main()'s ratchet; safe because a strong clean draft
  skips punch-up. Rewrite paths pop the stash and re-score. ~1 call/render saved.
- **Dossier cache** (`dossier_cache_<page>.json`, committed): `research_dossier`
  keyed by sha1(fact) — zero LLM on a repeated fact (retry / buffer / recurrence).
- **Script buffer / split write-from-render**: `generate.py --enqueue` writes a
  manifest into `queue_<page>/` (memory still updates → batch stays diverse);
  `--dequeue` pops oldest to manifest.json with ZERO LLM (exit 3 = empty → live
  gen). `render.yml` tries `--dequeue` first (empty queue = old behaviour exactly;
  commit step stages `queue_*` with `-A` so a drained file's deletion is pushed).
  New **`buffer.yml`** (manual + 07:20 UTC cron) batches N scripts when buckets
  are fresh. Answer to "more videos than the daily quota": bank when fresh, drain
  over days.
- Earlier same-batch: Piper local voice fallback (below ElevenLabs), zero-LLM
  keyword footage match, judge reordered off Gemini, Together/Fireworks/Mistral
  providers, punch-up skipped on strong drafts, 07:12 UTC reset cron.

### NOT yet render-verified (do after the 07:00 UTC quota reset)
- **`SCENE_XFADE`** (main.py, default 0 = OFF): opt-in video-only cross-dissolve
  between scenes (audio stays hard-cut, never clipped). Offset math unit-tested;
  captions anchor to hard-cut boundaries so a real render must confirm sync
  before flipping the default on. Enable per-render with `SCENE_XFADE=0.2`.
- The buffer/dequeue path + prompt-trim quality: trigger a render after reset,
  confirm `[queue] dequeued ...` or a clean live gen, then WATCH the video.

## Free-tier reality (be honest with the user about this)
Nightly volume is capped by free daily quotas. A big batch/queue **accumulates
over days** as quotas reset — it does NOT come from one night on free tier. The
only fast unlock is a cheap paid LLM tier, which the user has declined for now.

## Improvements shipped 2026-07-15/16 (branch `claude/epic-edison-jybjd1`)
Watched every render frame-by-frame and fixed the concrete flaw before the next.
- **Wall-clock budget + circuit-aware backoff skip** (DONE — the old pending item):
  a fully-throttled run aborts in seconds, not ~10 min.
- **Footage anchoring** (`main._footage_intent`): judge/requery lead with the
  scene's `search_query` subject, not the metaphor voiceover — killed the "Dubai
  skyline on a forest video" bug. Biggest single relevance win.
- **No command endings**: dropped SHARE cta_style; `GENERIC_SAVE_CMD` now also
  rejects send/tag/share phrasings. Endings = resonant payoff / loop / question.
- **~40s pace**: `EDGE_RATE -12% → -5%` (keeps dense scripts, speaks a bit
  faster; whisper re-aligns captions) + word target 76-92 (validate cap 100).
- **Caption polish** (`main._merge_stopword_events`): folds function words so no
  lone "THE"/"TO" caption frame (one-word style kept — WrapStyle 2 = no wrap).
- **validate() contradiction-guard fix**: same-unit measurements ("243 vs 225
  Earth days") no longer falsely flagged; count contradictions still caught.

### Results
5 renders shipped, **4 post-worthy in a row across different domains**: Krakatoa
(physics, A−), Oregon honey fungus (fungi, A−/B+), Hawaiian conveyor belt
(geology, A, 40s), The Star Inside Earth (earth, A−/B+). See
`reports/video_review_2026-07-15_overnight.md`.

## Known pending improvements (not yet done)
- **Multi-word phrase captions**: blocked on ASS `WrapStyle: 2` (no wrap) + wide
  font — needs a font-size/wrap change, best verified with a real render.
- (2026-08-04 cleanup: removed two stale items from this list that were actually
  already shipped — the footage brightness filter is `main._shadow_lift_filter`/
  `_clip_too_dark`, and the series/binge architecture is BUILT per PLATFORM.md.
  If you're reading this file to catch up, don't trust this section blindly —
  cross-check against the actual code before treating anything here as truly
  outstanding.)

## Cross-session note
Scheduled `send_later`/trigger reminders are tied to the session that made them;
a NEW session does NOT inherit them. Re-establish any needed resumption in the new
session. All durable state is in git + this file + the review log.
