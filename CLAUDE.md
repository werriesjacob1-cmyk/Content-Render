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
1. **Gemini** (`GEMINI_API_KEY`): models `gemini-2.0-flash`, `gemini-2.5-flash`.
   NOTE: `gemini-2.5-flash-lite` 404s for newly-created keys ("not available to
   new users") — do NOT add it back. Free daily cap ~450 reqs; resets **midnight
   Pacific = 2:00 AM CT / 07:00 UTC**.
2. **OpenRouter** (`OPENROUTER_API_KEY`): `meta-llama/llama-3.3-70b-instruct:free`
   — the strongest free model; separate free daily bucket (small, ~50/day).
3. **Cerebras** (`CEREBRAS_API_KEY`): models **auto-discovered** via `/v1/models`
   (this key only has `gemma-4-31b` + `gpt-oss-120b`, NOT llama). RPM-limited on
   free tier; has a per-minute self-heal retry.
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
`topic_bank.json` — 70 verified facts across 15 domains. `memory_science.json`
tracks used facts; `used_footage_science.json` dedups clips across runs.

## Free-tier reality (be honest with the user about this)
Nightly volume is capped by free daily quotas. A big batch/queue **accumulates
over days** as quotas reset — it does NOT come from one night on free tier. The
only fast unlock is a cheap paid LLM tier, which the user has declined for now.

## Known pending improvements (not yet done)
- **Wall-clock budget on generation**: when ALL providers are throttled, the
  stacked backoffs grind ~10 min before aborting. Add an elapsed-time cap in
  `main()`'s generation loop so a fully-throttled run fails fast. (Deferred —
  only bites when everything is throttled; test before shipping.)
- Idea 2 (series/binge architecture: numbered series + cross-video callbacks) is
  PARTIAL — see PLATFORM.md.

## Cross-session note
Scheduled `send_later`/trigger reminders are tied to the session that made them;
a NEW session does NOT inherit them. Re-establish any needed resumption in the new
session. All durable state is in git + this file + the review log.
