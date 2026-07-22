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
2. **OpenRouter** (`OPENROUTER_API_KEY`): `meta-llama/llama-3.3-70b-instruct:free`
   — WAS the strongest free model, but as of **2026-07-22 it returns HTTP 404
   "This model is unavailable for free. The paid version is available now"** —
   OpenRouter discontinued the free tier for it. The chain falls straight through
   to `github:gpt-4o-mini` (weak — overshoots word count then trims to mush;
   shipped the 6.83/surprise-4 near-miss in render 130). Until a strong free
   replacement is found, the **Gemini quality-rescue** (below) is what keeps
   quality up.
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
- **Footage brightness filter**: a few clips came out dark (night-side Earth,
  dark ocean). Add a min-brightness reject in footage selection or lift the grade.
- **Multi-word phrase captions**: blocked on ASS `WrapStyle: 2` (no wrap) + wide
  font — needs a font-size/wrap change, best verified with a real render.
- Idea 2 (series/binge architecture: numbered series + cross-video callbacks) is
  PARTIAL — see PLATFORM.md.

## Cross-session note
Scheduled `send_later`/trigger reminders are tied to the session that made them;
a NEW session does NOT inherit them. Re-establish any needed resumption in the new
session. All durable state is in git + this file + the review log.
