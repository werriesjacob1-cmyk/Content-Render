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

## LLM providers (free), tried in this order — all env-gated
1. **Gemini** (`GEMINI_API_KEY`): models `gemini-2.0-flash`, `gemini-2.0-flash-lite`
   (each is a SEPARATE free daily bucket — flash-lite unblocked evening renders
   once flash was spent). NOTE: `gemini-2.5-flash` AND `-2.5-flash-lite` now 404
   for new keys ("no longer available to new users") — do NOT add them back.
   Free daily cap is small (~200/model/day); each render burns ~20-50 calls
   (generation + per-scene footage judge), so the free tier realistically yields
   ~5-8 good videos/DAY across ALL consumers (this loop + daily cron + any other
   session). Resets **midnight Pacific = 2:00 AM CT / 07:00 UTC**.
2. **OpenRouter** (`OPENROUTER_API_KEY`): `meta-llama/llama-3.3-70b-instruct:free`
   — the strongest free model; separate free daily bucket (small, ~50/day).
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
`topic_bank.json` — **91 verified facts across 19 domains** (added materials/
weather/deep_time/history/geology/senses + high-wow facts). `memory_science.json`
tracks used facts; `used_footage_science.json` dedups clips across runs.
Domain selection now dedups by FAMILY (`DOMAIN_FAMILIES`: geology/earth/weather
= one family) so two deep-earth videos don't run back-to-back.

## Zero-quota test suite — RUN THIS before shipping generate.py/main.py changes
`GROQ_API_KEY=x python tests/test_pipeline.py` — **80 checks** over the trickiest
PURE logic (caption content-alignment, footage `_footage_intent` anchoring,
`_diversify_scene_queries`, timing, `validate()` across 5 topic fixtures + broken
ones, fast-fail-when-throttled, domain families, **`critique_script` merge,
script-buffer FIFO/empty/malformed, `_xfade_offsets` math**). No ffmpeg, no
network, no LLM. It already caught a real validate() false-positive.

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
