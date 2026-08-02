#!/usr/bin/env python3
"""
generate.py — the content brain.
Calls Groq to write ONE fresh science video per run. Rotates 5 viewer-jobs, builds
in completion/save/comment/search optimizations, never repeats recent topics.
Writes manifest.json for the render engine and appends to memory.json (regression record).

Env: GROQ_API_KEY
"""

import os, sys, json, re, time, urllib.request, urllib.error, random, datetime, collections, hashlib

ROOT = os.path.dirname(os.path.abspath(__file__))
PAGE = os.environ.get("PAGE", "science")
SERIES = os.environ.get("SERIES", "").strip()        # e.g. "The Body's Hidden Systems"
SERIES_PART = os.environ.get("SERIES_PART", "").strip()  # e.g. "2"
MEMORY = os.path.join(ROOT, f"memory_{PAGE}.json")
# Research dossiers are keyed by the verified fact text and cached across runs:
# the same fact costs one Gemini/Groq call to research the FIRST time, then zero
# on every retry (aborted-run reruns, pre-generated buffer, a fact that recurs
# after the 14-entry memory window forgets it). See research_dossier().
DOSSIER_CACHE = os.path.join(ROOT, f"dossier_cache_{PAGE}.json")
# SPLIT WRITE FROM RENDER (script buffer): generate.py normally writes one
# manifest and the workflow renders it immediately. But generation is what's
# quota-bound, not rendering — so when the free buckets are fresh we can
# pre-generate a BATCH of manifests into a queue and render them later (even on
# days the buckets are spent). Modes:
#   --enqueue : generate ONE manifest into queue_<page>/ instead of manifest.json
#   --dequeue : pop the oldest queued manifest to manifest.json (no LLM at all);
#               exit 3 if the queue is empty so the caller falls back to live gen
# Default (no flag) is unchanged: generate one manifest to OUT_MANIFEST.
_ARGV = list(sys.argv[1:])
GEN_MODE = "normal"
if "--dequeue" in _ARGV:
    GEN_MODE = "dequeue"; _ARGV.remove("--dequeue")
elif "--enqueue" in _ARGV:
    GEN_MODE = "enqueue"; _ARGV.remove("--enqueue")
elif "--record" in _ARGV:
    # Feed real analytics back into perf_<page>.json so generation learns what
    # works. Usage:
    #   python generate.py --record <video_id> views=18400 watch=0.63 follows=41 shares=210
    # 'watch' is watch_through_pct (0..1). Any subset of metrics is fine. This is
    # how a human OR a future analytics-pull automation writes the feedback loop's
    # data — no dashboard integration required to start.
    GEN_MODE = "record"; _ARGV.remove("--record")
OUT_MANIFEST = _ARGV[0] if _ARGV else os.path.join(ROOT, "manifest.json")
QUEUE_DIR = os.path.join(ROOT, f"queue_{PAGE}")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
# Google Gemini free tier has a FAR higher daily quota than Groq's free tier
# (~1500 requests/day vs a handful of renders), so when GEMINI_API_KEY is set we
# prefer it for generation — this is what lets many videos batch-render in a day
# without hitting the wall that keeps aborting renders on Groq. Groq stays as an
# automatic fallback. Get a free key at aistudio.google.com (no card) and add it
# as the GEMINI_API_KEY repo secret.
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
# AI Studio keys come in TWO valid shapes: the legacy "AIza..." (~39 chars) and
# the new "AQ.Ab..." auth keys that Google rolled out through 2026 (legacy
# unrestricted "AIza" keys are being rejected from June 2026, so new keys are
# AQ.* by default). Both work against generativelanguage.googleapis.com with the
# x-goog-api-key header we use. Only warn on something that matches NEITHER shape
# (e.g. a "ya29." OAuth access token pasted by mistake), since that really will
# 400. Get keys at https://aistudio.google.com/apikey .
if GEMINI_KEY and not (GEMINI_KEY.startswith("AIza") or GEMINI_KEY.startswith("AQ.")):
    print(f"  [model] WARNING: GEMINI_API_KEY starts with '{GEMINI_KEY[:3]}...', which is "
          f"neither a legacy 'AIza' key nor a new 'AQ.' auth key. If Gemini 400s, get a "
          f"fresh key at https://aistudio.google.com/apikey")
# Only models a NEWLY-CREATED free key can actually call.
# - gemini-1.5-flash: RETIRED (404 "not supported for generateContent").
# - gemini-2.5-flash-lite: 404 "no longer available to NEW users" — a fresh AQ
#   key cannot use it. Removed (see history). Do NOT add it back.
# - gemini-2.5-flash: as of 2026-07-15 this ALSO started 404ing for this key
#   ("no longer available to new users" — run 65 log), so Google has now closed
#   it to new keys the same way. Removed so it stops wasting a chain slot.
# What a new key CAN reach (they 429 with quota, i.e. authenticate): 2.0-flash.
# gemini-2.0-flash-lite is added as a SECOND model on purpose: each Gemini model
# has its OWN free daily-quota bucket, so when 2.0-flash's daily cap is spent
# (which is what blocks late-in-day renders), flash-lite's untouched bucket can
# still carry generation. If this key can't reach flash-lite it simply 404s and
# falls through harmlessly — no worse than before. Cerebras (auto-discovered)
# remains the capacity backstop when both Gemini buckets are out.
# 2026-07: Google keeps 404'ing hardcoded ids — a NEWLY-created key is restricted
# to only the newest models ("no longer available to new users" on 2.0-flash AND
# 2.5-flash). So we AUTO-DISCOVER what this key can actually call via ListModels
# (like cerebras_models) instead of guessing. GEMINI_MODEL env still forces a
# specific list if you want; otherwise gemini_models() picks live.
GEMINI_MODELS_FALLBACK = [m.strip() for m in os.environ.get(
    "GEMINI_MODEL", "gemini-flash-latest").split(",") if m.strip()]
_GEMINI_MODELS_CACHE = None


def gemini_models():
    """Models THIS key can call for generateContent, discovered live (newest flash
    first). Google restricts older ids on new keys, so a hardcoded value 404s;
    discovery self-heals. Falls back to GEMINI_MODELS_FALLBACK (GEMINI_MODEL env,
    default gemini-flash-latest) on any failure. Cached for the run."""
    global _GEMINI_MODELS_CACHE
    if _GEMINI_MODELS_CACHE is not None:
        return _GEMINI_MODELS_CACHE
    if os.environ.get("GEMINI_MODEL"):          # explicit override wins, no discovery
        _GEMINI_MODELS_CACHE = GEMINI_MODELS_FALLBACK
        return _GEMINI_MODELS_CACHE
    if not GEMINI_KEY:
        _GEMINI_MODELS_CACHE = GEMINI_MODELS_FALLBACK
        return _GEMINI_MODELS_CACHE
    try:
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
            headers={"x-goog-api-key": GEMINI_KEY, "User-Agent": "content-render/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        flash, other = [], []
        for m in data.get("models", []):
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            nm = m.get("name", "").split("/")[-1]
            if any(b in nm for b in ("vision", "thinking", "image", "tts", "embedding", "aqa", "learnlm")):
                continue
            (flash if "flash" in nm else other).append(nm)
        # prefer flash (cheap/fast), stable over preview/exp, newest id first
        def _rank(lst):
            stable = [n for n in lst if "preview" not in n and "exp" not in n and "-latest" not in n]
            latest = [n for n in lst if "-latest" in n]
            rest = [n for n in lst if n not in stable and n not in latest]
            return latest + sorted(set(stable), reverse=True) + sorted(set(rest), reverse=True)
        picked = _rank(flash) or _rank(other)
        _GEMINI_MODELS_CACHE = picked[:3] or GEMINI_MODELS_FALLBACK
        if picked:
            print(f"  [model] gemini models available to this key: {_GEMINI_MODELS_CACHE}")
    except Exception as e:  # noqa: BLE001
        print(f"  [model] gemini model discovery failed ({e}); using {GEMINI_MODELS_FALLBACK}")
        _GEMINI_MODELS_CACHE = GEMINI_MODELS_FALLBACK
    return _GEMINI_MODELS_CACHE
# Path A: try strongest available model first; fall back automatically if blocked (403) or rate-limited.
# llama-3.1-70b-versatile was DECOMMISSIONED by Groq (400 "model_decommissioned"),
# so it too wasted a slot; dropped. 3.3-70b (quality) then 3.1-8b-instant (cheap).
MODEL_CHAIN = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
# THIRD free provider (backup to Gemini + Groq). Cerebras' free tier is far more
# generous than Groq's (millions of tokens/day, high RPM) and serves the same
# Llama models on an OpenAI-compatible endpoint, so it's the workhorse fallback
# when Gemini is rate-limited and Groq's tiny daily budget is spent — the exact
# double-outage that shipped degraded videos. Optional: env-gated, no key = skip.
# Free key (no card): https://cloud.cerebras.ai . Add as CEREBRAS_API_KEY.
CEREBRAS_KEY = os.environ.get("CEREBRAS_API_KEY", "")


_CEREBRAS_MODELS_CACHE = None


def cerebras_models():
    """Which Cerebras models THIS key can actually use, discovered at runtime.
    A hardcoded list is fragile: run 54 showed the key 404'ing llama-3.3-70b with
    'Model does not exist or you do not have access to it' — the free account
    simply wasn't provisioned for it, and every call wasted a fall-through. So we
    ask Cerebras' /v1/models what this key is entitled to and use that (top pick =
    a 70B Llama if present). Cached for the process. Empty (no key, no access, or
    the lookup failed) → Cerebras is silently skipped in the chain, no wasted
    404s. Self-heals the moment the account gains access — no code change."""
    global _CEREBRAS_MODELS_CACHE
    if _CEREBRAS_MODELS_CACHE is not None:
        return _CEREBRAS_MODELS_CACHE
    out = []
    if CEREBRAS_KEY:
        try:
            req = urllib.request.Request(
                "https://api.cerebras.ai/v1/models",
                headers={"Authorization": f"Bearer {CEREBRAS_KEY}", "User-Agent": "content-render/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
            ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
            # Exclude reasoning models that don't return clean JSON: gpt-oss-*
            # replies with reasoning/markdown ("Expecting value: line 1 column 1",
            # run 63) and zai-glm-4.7 returns non-JSON too ("Extra data: line 1
            # column 2", run 71) — every generate attempt on them fails to parse,
            # worse than skipping them. gemma-4-31b is the reliable JSON one.
            _JSON_HOSTILE = ("gpt-oss", "glm")
            ids = [i for i in ids if not any(bad in i.lower() for bad in _JSON_HOSTILE)]
            # prefer a 70B llama, then any llama, then whatever else is granted
            ids.sort(key=lambda x: (0 if "70b" in x.lower() else 1,
                                    0 if "llama" in x.lower() else 1, x))
            out = ids[:2]
            print(f"  [model] cerebras models available to this key: {out or 'NONE'}")
        except Exception as e:  # noqa: BLE001
            print(f"  [model] cerebras /v1/models lookup failed ({e}); skipping Cerebras this run")
    _CEREBRAS_MODELS_CACHE = out
    return _CEREBRAS_MODELS_CACHE


# FOURTH free provider: OpenRouter. Its free tier ("...:free" model slugs) serves
# genuinely strong models — notably llama-3.3-70b — which is a big step up from
# Cerebras' free gemma-4-31b for a weak-model day, and it's a SEPARATE free daily
# bucket, so it stretches how many videos we can render for $0. OpenAI-compatible
# endpoint, so it reuses _call_openai_compat. Optional/env-gated (no key = skip).
# Free key (no card): https://openrouter.ai/keys . Add as OPENROUTER_API_KEY.
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
# The FREE llama-3.3-70b slug ("...:free") was discontinued — OpenRouter 404s it
# ("This model is unavailable for free. The paid version is available now - use
# this slug instead: meta-llama/llama-3.3-70b-instruct"). With paid credits on the
# key we use that PAID slug (drop ":free"): a strong, NON-rate-limited writer — a
# few cents per render — that catches the nights Gemini's quota 429s. This is the
# reliability fix for the aborted renders (every strong free writer was exhausted).
# Env-overridable (OPENROUTER_MODEL, comma-separated) so the model can change with
# NO code edit — e.g. set it to deepseek/deepseek-chat-v3 for a stronger writer.
_OR_RAW = os.environ.get("OPENROUTER_MODEL", "").strip()
OPENROUTER_MODELS = [m.strip() for m in _OR_RAW.split(",") if m.strip()] or \
    ["meta-llama/llama-3.3-70b-instruct"]
# More free/separate-bucket providers, all OpenAI-compatible and ENV-GATED (no
# key = skipped, zero behaviour change). Each is its own daily bucket, so adding
# any one key gives a whole extra pool of strong-model generation on free tier —
# the direct fix for "we burn through Gemini/OpenRouter too fast". Together and
# Fireworks both host a free Llama-3.3-70B; Mistral's free tier serves a capable
# small model as a lighter backup.
TOGETHER_KEY  = os.environ.get("TOGETHER_API_KEY", "")
FIREWORKS_KEY = os.environ.get("FIREWORKS_API_KEY", "")
MISTRAL_KEY   = os.environ.get("MISTRAL_API_KEY", "")
# Model IDs are env-overridable (comma-separated for >1) so a wrong/inaccessible
# model can be fixed WITHOUT a code change — e.g. Fireworks 404'd on
# llama-v3p3-70b-instruct for an account that hadn't deployed it; set
# FIREWORKS_MODEL to one the account actually has. Empty env keeps the default.
def _models_env(var, default):
    raw = os.environ.get(var, "").strip()
    return [m.strip() for m in raw.split(",") if m.strip()] or default
TOGETHER_MODELS  = _models_env("TOGETHER_MODEL",  ["meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"])
FIREWORKS_MODELS = _models_env("FIREWORKS_MODEL", ["accounts/fireworks/models/llama-v3p3-70b-instruct",
                                                   "accounts/fireworks/models/llama-v3p1-8b-instruct"])
MISTRAL_MODELS   = _models_env("MISTRAL_MODEL",   ["mistral-small-latest"])
# GitHub Models (free, OpenAI-compatible): gpt-4o-mini is a genuinely strong
# writer, separate free bucket, and we already run inside GitHub Actions. Prefer a
# PAT with the models:read scope (GITHUB_MODELS_TOKEN); fall back to the built-in
# GITHUB_TOKEN when the workflow grants `permissions: models: read`.
GHM_KEY    = os.environ.get("GITHUB_MODELS_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
GHM_URL    = os.environ.get("GITHUB_MODELS_URL", "https://models.inference.ai.azure.com/chat/completions")
GHM_MODELS = _models_env("GITHUB_MODELS_MODEL", ["gpt-4o-mini"])
BANK_PATH = os.path.join(ROOT, "topic_bank.json")

# ---------------------------------------------------------------------------
# QUALITY RATCHET — pre-publish self-critique scoring (improvement loop, part 1)
# ---------------------------------------------------------------------------
# After a script is built, validated, and punched up, one more Groq call
# scores it against an explicit rubric BEFORE it ever reaches main.py's
# expensive render pipeline (TTS + footage search/judge + ffmpeg encode).
# Below QUALITY_THRESHOLD, the whole video is regenerated from scratch,
# bounded to QUALITY_MAX_REGENERATIONS extra attempts so the unattended daily
# run has a hard time/cost ceiling. If nothing clears the bar, the
# best-scoring attempt ships anyway — this gate must never be able to stop
# the daily run from producing a video.
#
# QUALITY_THRESHOLD started modest on purpose while the channel had no track
# record. RATCHET THIS UP over time (e.g. 7.0 -> 7.5 -> 8.0) once
# perf_<page>.json (see PERF_PATH below) shows higher-scoring scripts actually
# perform better in real engagement data. Raised 7.0 -> 7.5 after "You're
# Always Living in the Past" shipped at overall 7.17 despite payoff:5 and
# blatant 5x repetition of its one reveal — averaging across six criteria let
# a badly broken script hide behind a couple of high scores (rewatch:9).
QUALITY_THRESHOLD = 7.5

# PER-CRITERION FLOORS — the averaging failure above is why these exist. A
# script can have a great hook/surprise/rewatch and still be a bad video if
# it never pays off, doesn't escalate, or opens on a confusing hook — no
# average should be able to paper over that. ANY real score (not a fail-open
# None) below its floor forces a regeneration REGARDLESS of the overall
# average, even if overall clears QUALITY_THRESHOLD. This alone would have
# caught the Sun video: payoff scored 5, floor is 6.
# escalation was 7, but real Gemini runs (run 59) kept scoring otherwise-strong
# scripts at escalation 6 while overall was 7.5 with payoff 9 / clarity 10 —
# genuinely good videos, aborted over a single 1-point miss. Escalation 6 ("builds
# well, not perfectly") is not a broken video; 5 or below is. Floor set to 6 so a
# solid script (hook>=6, payoff>=6, escalation>=6, overall>=6.8) ships instead of
# grinding forever. Hook/payoff stay at 6 — a 4/10 hook or payoff really is a bad
# video and must still abort.
QUALITY_CRITERION_FLOORS = {
    # RE-RAISED 2026-07-30 (render 173 "T. rex is closer to you" — a DANGLING
    # comparative with no "than ___", shipped and confused the user). That script
    # passed the OLD, STRICTER gate below (hook/escalation/payoff>=6, hard floor
    # 6.8) from BEFORE the 2026-07-29 loosening — proof the loosening was never
    # what let it through, and that self-scored 6-7s are not a reliable coherence
    # signal on their own. Raising the floors back up is the honest fix, paired
    # with a MECHANICAL, zero-LLM dangling-comparative check in validate()
    # (DANGLING_COMPARATIVE_RE) that catches this exact pattern regardless of how
    # the self-grader scores it — self-scoring is now a second layer, not the only one.
    "hook": 6,
    "escalation": 6,
    "payoff": 6,
    # COHERENCE raised 6 -> 7: the single highest-value floor (kills the render-160
    # Pluto AND render-173 T. rex classes of bug). Simple-sounding but muddled must
    # still ABORT even at a 6/10 self-score.
    "coherence": 7,
}
# HARD FLOOR — the line below which we publish NOTHING rather than a weak video.
# The quality loop keeps the best attempt and, if none clear QUALITY_THRESHOLD,
# used to ship the best regardless ("never block the daily run"). That shipped
# the run-54 "Lasting Footprints" video at overall 6.0 with hook 4/10 and 2
# redundant scenes — exactly the "one shit video" the channel must never post.
# Now: if the best attempt still has a per-criterion floor violation OR sits
# below this overall hard floor, ABORT (no render, no release). We are not
# posting yet and the bar is consistency, so no video beats a bad one; the daily
# cron simply tries again. A CLEAN script that merely couldn't be SCORED
# (fail-open, best_quality is None) is still allowed through — it passed every
# structural gate, we just couldn't grade it.
QUALITY_HARD_FLOOR = 6.8   # RESTORED 2026-07-30 (was briefly 6.0 2026-07-29). The
                            # loosening was based on believing GPT-4o's 6.1-6.9 drafts
                            # were "coherent, just harshly scored on payoff/escalation"
                            # — but render 173 proved a script that cleared the ORIGINAL
                            # 6.8 floor (from before any loosening) still had a real,
                            # user-visible coherence break. The self-scorer in the 6-7
                            # range is not trustworthy enough to lower the bar for; 6.8
                            # + the new coherence floor (7) + the mechanical dangling-
                            # comparative check are the actual quality backstop now.
QUALITY_MAX_REGENERATIONS = 1   # extra attempts beyond the first (so 2 total).
                                 # Was 2 (3 total), but each attempt re-runs the full
                                 # generate+validate+info-gain+punch-up+score pipeline
                                 # (~5 LLM calls), and on the free tier the per-minute
                                 # rate limit turns 3 attempts into a ~13-min backoff
                                 # grind (run 59). With the escalation floor relaxed to
                                 # 6, a strong first attempt usually clears the bar and
                                 # breaks early, so 2 attempts is enough and keeps the
                                 # run well under the 30-min job timeout.
# WALL-CLOCK BUDGET on the whole generation loop — a hard backstop that
# complements the smaller regen count above. When ALL free providers are
# throttled, the circuit breaker (call_groq) eventually opens, but before it
# does the stacked per-attempt backoffs (generate_candidate's 8*attempt sleeps)
# still burn time for nothing. Once the generation loop in main() has spent this
# many seconds with no shippable script, stop attempting and abort fast (no
# render, no release) instead of grinding. A HEALTHY run finishes every attempt
# well under this (each LLM call is seconds, not minutes), so it never trips
# normal operation — it only bites a fully-throttled run. Env-overridable.
GEN_WALL_BUDGET_S = int(os.getenv("GEN_WALL_BUDGET_S", "420"))
QUALITY_RUBRIC_CRITERIA = ["hook", "surprise", "escalation", "payoff", "rewatch", "clarity", "coherence"]

# ---- A/B VIDEO LENGTH (analytics-driven) --------------------------------------
# TikTok analytics (2026-07-26): avg watch ~8s on ~40s videos — almost nobody sees
# the back half, and completion is ~7%. So we A/B two lengths and let perf_<page>.json
# reveal which retains better on THIS page: SHORT (~28-32s: higher completion% and
# watch-ratio) vs LONG (~40-46s: full escalation arc). Scene COUNT stays 7-9 either
# way (escalation is sacred) — SHORT just uses fewer words per scene. LENGTH_MODE=
# short|long forces one; the default "auto" ALTERNATES per render off the memory
# history length (one entry per render), so consecutive videos flip with no new state.
def _resolve_length_mode():
    mode = os.getenv("LENGTH_MODE", "auto").strip().lower()
    if mode in ("short", "long"):
        return mode
    try:
        hist = json.load(open(MEMORY)).get("history", [])
        return "short" if (len(hist) % 2 == 0) else "long"
    except Exception:  # noqa: BLE001 — no/broken memory => default to the proven long
        return "long"

# Per-scene hard word cap -- mode-independent (SHORT and LONG both use natural
# ~6-16 word scenes; this is just the ceiling for an occasional longer beat).
# ONE constant read by validate(), the writer prompt, AND the near-miss repair's
# per-scene trim below, so the three can never drift out of sync with each other.
SCENE_WORD_CAP = 25

LENGTH_MODE = _resolve_length_mode()
if LENGTH_MODE == "short":
    # SHORT's 55-74 word budget was NEVER hit natively (renders 187-191: every
    # writer model — gpt-4o AND deepseek/deepseek-chat, five straight aborts —
    # wrote 83-111 words regardless of the instruction). This is the exact same
    # failure shape already diagnosed and fixed for LONG mode 2026-07-22 (see the
    # "Word window 80-100 -> 85-115" note below): a tight cap that doesn't match
    # what the models actually produce forces near-miss SCENE-dropping on every
    # single attempt, and each drop has good odds of collaterally deleting the
    # scene carrying a mandatory key term / the whatif question / a unique fact —
    # so the run aborts on a SECONDARY violation even after the trim "succeeds."
    # Fix = the same one that worked for LONG: widen the window to match reality
    # so a clean draft ships with ALL its scenes (and their content) intact.
    WORD_LO, WORD_HI, WORD_HARD_LO, WORD_HARD_HI = 78, 98, 68, 108   # ~32-38s
    SCENE_MIN, SCENE_MAX = 5, 8
    WORDS_PER_SCENE = "~12-15 words (6-7 scenes x ~13 words = ~85 total)"
    LENGTH_HINT = ("THIS IS A SHORT ~32-38s video. Structure: hook (scene 1) → 4-5 escalating fact "
                   "beats → PAYOFF (final scene, the reframe that recontextualises everything). "
                   "Land the payoff HARD and FAST — with only 6-7 scenes there is no room to wander, "
                   "so every scene earns its place and the last one must reframe, not summarise. COUNT "
                   "your words as you write and STAY at 78-98 total; do NOT overshoot and rely on trimming.")
else:
    WORD_LO, WORD_HI, WORD_HARD_LO, WORD_HARD_HI = 95, 110, 85, 115  # ~40-46s
    SCENE_MIN, SCENE_MAX = 7, 10
    WORDS_PER_SCENE = "~12-14 words (8 scenes x ~13 words = ~104 total)"
    LENGTH_HINT = ("THIS IS A ~42s video: 7-9 scenes that ESCALATE to a genuine payoff — the final "
                   "scene must reframe, never just restate the premise.")


def draft_is_weak(overall, quality):
    """True when a scored draft is genuinely weak — below the clean threshold OR
    breaking any per-criterion floor. Gates the frugal Gemini quality-rescue in
    main(): a weak best-draft is worth ONE paid Gemini attempt; a strong one (or
    an ungradable-but-clean one, where overall/quality is None) is not. Pure so
    the rescue trigger is unit-tested without any LLM."""
    if overall is None or quality is None:
        return False   # a clean script we simply couldn't grade — leave it be
    if overall < QUALITY_THRESHOLD:
        return True
    return any(quality.get(k, 10) < fl for k, fl in QUALITY_CRITERION_FLOORS.items())

# ---------------------------------------------------------------------------
# PERFORMANCE MEMORY — bias future generation using REAL engagement data
# ---------------------------------------------------------------------------
# perf_<page>.json is OPTIONAL and does not exist by default. Paste one in
# yourself once you have real analytics for videos this pipeline has posted.
# Format — a flat object mapping video_id -> engagement metrics:
#
#   {
#     "science_2026-07-11_sharks-vs-trees": {
#       "views": 18400,
#       "watch_through_pct": 0.63,
#       "follows": 41,
#       "saves": 320,
#       "shares": 210,
#       "comments": 88
#     },
#     "science_2026-07-12_the-void-within": {
#       "views": 2100,
#       "watch_through_pct": 0.31,
#       "follows": 2,
#       "shares": 4
#     }
#   }
#
# Keys are the "video_id" values generate.py writes into manifest.json (and
# main.py copies into out/post.json) on every run — match them up against
# whatever your posting step or analytics dashboard tells you about that
# video. Values:
#   views                total plays
#   watch_through_pct    average fraction of the video watched, 0..1 (63% -> 0.63)
#   follows              follows attributed to this video
#   saves                bookmark/save count  (strong "keep this" intent signal)
#   shares                share count
#   comments             comment count        (drives reach)
# Any subset of keys is fine; missing keys count as 0. A missing, empty, or
# malformed perf_<page>.json is completely safe: with no usable data,
# generation is byte-for-byte identical to today's plain random.choice()
# selection (see score_by_key()/main() below) — no regressions, ever.
PERF_PATH = os.path.join(ROOT, f"perf_{PAGE}.json")
PERF_UNSEEN_FLOOR = 0.15   # weight floor given to a fact/job with NO perf data yet,
                           # so unproven options keep getting picked instead of the
                           # pool collapsing onto whichever option happened to score first
EXPLORE_EPSILON = 0.30    # even once perf data exists, this fraction of picks ignore
                           # the weights and choose uniformly at random — explore, don't
                           # just exploit past winners forever

def load_bank():
    try:
        with open(BANK_PATH) as f:
            return json.load(f).get("facts", [])
    except Exception:
        return []
_WORKING_MODEL = None  # cached once we find one that responds
# One-shot switch for the Gemini quality-rescue (main() sets it True for a single
# grounded attempt when the free chain could only manage a weak draft, then clears
# it). While True, call_groq puts the paid Gemini chain FIRST regardless of the
# free-first default — the rescue explicitly wants Gemini to author the retry.
_FORCE_GEMINI_GEN = False

VIEWER_JOBS = [
    ("REFRAME",
     "Flip a SPECIFIC scientific fact the viewer thought they understood. Must center on a real, "
     "verifiable mechanism (how/why something actually works). The payoff rewires their mental model. "
     "End so they think 'I'll never see X the same way.' NOT vague philosophy — a concrete fact."),
    ("SOCIAL_CURRENCY",
     "Built around ONE stunning, TRUE, specific number or comparison (with the actual figure) so striking "
     "the viewer repeats it to sound smart. Must include a real measurable fact, not a feeling."),
    ("EXISTENTIAL_CHILL",
     "Take a REAL, specific scientific fact about reality/the body/time/the universe that happens to be "
     "awe-inducing, and explain the actual science of it. The chill comes from a TRUE mechanism, not from "
     "vague poetry. NO fortune-cookie lines like 'time is a river' — state the real fact and why it's true."),
    ("HOW_TO",
     "A simple, SAFE, surprising science demonstration the viewer can do with common household items, then the science of WHY it works. "
     "STRICT SAFETY: only classic, well-established, proven-safe demos. NO fire, flames, heat, ingestion, swallowing, "
     "chemicals beyond plain kitchen items, electricity, mains power, sharp blades, glass that could shatter, or anything "
     "that could injure a person, child, or pet or damage property. If unsure whether a demo is safe, DO NOT use it. "
     "Good examples: pepper + dish soap surface tension, static-electricity bending water, a teabag 'rocket' is borderline "
     "(involves flame) so AVOID it, salt lifting an ice cube, a balloon stuck by static. The save trigger ('try this') is native."),
    ("MYTH_BUSTER",
     "Take something the viewer has been told their whole life and show it's wrong, with the real science. "
     "Designed to spark comments — people will argue. Plant one line they'll want to reply to."),
]

# ---------------------------------------------------------------------------
# CTA STRATEGY — rotated, content-fit endings (save-worthiness overhaul)
# ---------------------------------------------------------------------------
# The channel used to hard-code the SAME closing command on every single video
# ("Save this so you remember it."). A command doesn't make anyone save a
# video -- saves come from the content actually being worth referencing again,
# plus (sometimes) a natural trigger. So: (1) the CONTENT gets an explicit
# reference-worthy requirement independent of how the video ends (see
# REFERENCE_WORTHY_RE / the validate() check below and the prompt rule in
# build_prompt), and (2) the ENDING is chosen per-video from four distinct
# mechanics instead of one recycled line. Exactly one style per video, picked
# here in main() (weighted by perf_<page>.json once real data exists, same
# scaffold as VIEWER_JOBS/fact selection) and threaded through build_prompt /
# punch_up / score_script so every stage of the pipeline agrees on what
# "sticking the landing" means for THIS video.
# SHARE was removed from the rotation: its ending is by design a literal command
# ("send this to the friend who...", "tag the person who needs this"), which is
# exactly the command ending the user's rubric bans — it undercut the otherwise
# A-grade Krakatoa video (render 67) with a hollow "send this to a friend" close.
# The remaining three all end on a NON-command note: a resonant payoff, a
# seamless rewatch loop, or a genuine question. Organic shares are better earned
# by a mind-blowing resonant payoff than by begging for a tag. SHARE's rule is
# kept defined below in case it's ever wanted, but it is not assigned.
CTA_STYLES = ["SAVE_WORTHY", "LOOP", "COMMENT"]

# HOOK FRAMES — the SHAPE of the opening line, rotated per video (like cta_style)
# so the page stops feeling same-shaped (every video opening with the same
# "question or bold claim"). The frame changes the STRUCTURE of the first beat;
# all the normal hook rules (concrete, instantly pictured, 8-14 words) still
# apply on top. One is picked per render in main(), avoiding the last one used.
HOOK_FRAMES = [
    ("DIRECT_QUESTION",
     "Open on a concrete question the viewer instantly starts answering in their head — name a "
     "real thing in it (e.g. 'How much of what you taste is actually smell?'). Not abstract."),
    ("MYTH_FLIP",
     "Open by stating a belief the viewer HOLDS, then flip it in the same breath (e.g. 'You were "
     "taught your tongue has taste zones — it doesn't'). The rest proves the correction."),
    ("EVERYDAY_UNSEEN",
     "Open on something the viewer does or sees EVERY DAY and reveal it as secretly strange (e.g. "
     "'Every time you smell rain, you're smelling bacteria'). Make the familiar suddenly alien."),
    ("CHALLENGE",
     "Open with a dare the viewer will get wrong (e.g. 'Name something older than trees — whatever "
     "you guessed is probably wrong'). It provokes them to argue and keep watching."),
    ("BODY_SCENARIO",
     "Open on a vivid thing happening RIGHT NOW in the viewer's own body or surroundings (e.g. "
     "'Right now, microbes in your gut are voting on what you crave'). Immediate and physical."),
    ("IMPOSSIBLE_FACT",
     "Open on a flat claim so specific it sounds fake but is TRUE (e.g. 'Sharks are older than "
     "Saturn's rings'). The brain can't scroll past needing the 'how is that possible' answer."),
    ("COMPARISON_COLLISION",
     "Open by smashing together two things the viewer would never connect, as a plain statement of "
     "fact (e.g. 'The Amazon rainforest is kept alive by a desert on another continent'). The "
     "collision itself is the hook; the curiosity is 'wait, how are those two even related?'"),
    ("STAKES_SCENARIO",
     "Open on a high-stakes 'what happens if this happens to YOU' scenario — survival, danger, or "
     "the viewer's own body under extreme conditions (e.g. 'An airlock bursts and you're sucked into "
     "space — you have about fifteen seconds'). Life-or-death stakes happening to the VIEWER means "
     "they physically cannot scroll until they see how it ends. This is the channel's HIGHEST-"
     "retention hook shape, proven in analytics: 2.5x the average watch time and 4x the completion "
     "rate of a passive 'how many / can you see' question. Frame the fact as a consequence the "
     "viewer would live through, not a trivia question they can shrug off."),
]

CTA_ENDING_RULES = {
    "SAVE_WORTHY": (
        "ENDING STYLE FOR THIS VIDEO: RESONANT PAYOFF. End on the single most striking, "
        "mind-expanding line the script has earned -- the fact's biggest implication, or the "
        "detail that quietly reframes how the viewer will see this everyday thing from now on. "
        "State it cleanly and let it land. ABSOLUTELY NO call-to-action or instruction of ANY "
        "kind: never tell the viewer to save, screenshot, remember, look up, keep, or do anything "
        "-- phrases like 'save this', 'worth a screenshot', 'you'll want this again' are BANNED and "
        "read as hollow filler. The last line is a thought that stays with them, not a command. "
        "Best of all is a final line that recasts the hook -- so the thing they thought they "
        "understood at the start now means something bigger."
    ),
    "LOOP": (
        "ENDING STYLE FOR THIS VIDEO: LOOP FOR REWATCH. The final line should echo the FEELING or "
        "central image of the hook so a replay feels seamless — but do NOT simply restate the hook's "
        "fact or repeat its exact words/number. Do NOT bolt on an unrelated NEW fact either (a real "
        "shipped failure: hook was 'an octopus' heart stops every time it swims — how?' and the video "
        "ended on 'blood chemistry so strange it can cause allergies in humans' — a random trivia "
        "tidbit with zero connection back to the heart-stopping hook, so the loop never closes). The "
        "last line must gesture back at the SAME image/question the hook opened, not introduce a "
        "fresh one. Repeating the opening claim verbatim reads as the "
        "video repeating itself (e.g. a hook about fingernail-growth speed must NOT end by saying "
        "'at the same speed your fingernails grow' again). Instead, land a NEW resonant thought that "
        "leaves the hook's image ringing. No call-to-action language (no 'save', 'share', 'comment')."
    ),
    "COMMENT": (
        "ENDING STYLE FOR THIS VIDEO: COMMENT BAIT. The final line must pose a genuine binary "
        "question ('Team A or Team B?', 'Would you or no?') or state a claim people will actually "
        "want to argue with ('and that means everything you learned about X is wrong') -- something "
        "a real person would stop and type a reply to, not a rhetorical throwaway. Do not also tell "
        "them to save or share in this line."
    ),
    "SHARE": (
        "ENDING STYLE FOR THIS VIDEO: SHARE TRIGGER. The final line must hand the viewer a concrete, "
        "identity-specific reason to send this to one particular kind of person ('send this to the "
        "friend who still doesn't believe you', 'tag the person who needs to see this') tied "
        "DIRECTLY to the fact just taught -- not a generic 'share this video'. Do not also tell them "
        "to save or comment in this line."
    ),
}

# Rubric wording for score_script()'s "rewatch" criterion -- scored per the
# style actually assigned to this video, not a one-size-fits-all "did it ask
# for a save" question.
CTA_RUBRIC_HINTS = {
    "SAVE_WORTHY": "does the ending land on a striking, resonant final thought or implication "
                    "(ideally recasting the hook), with ZERO command/instruction language "
                    "('save', 'screenshot', 'remember', 'look up' are all disqualifying)?",
    "LOOP": "does the ending loop back cleanly to the hook/opening image so a replay feels seamless, "
            "with no bolted-on CTA language?",
    "COMMENT": "does the ending pose a real binary question or arguable claim a viewer would "
               "actually reply to?",
    "SHARE": "does the ending give a specific, identity-relevant reason to send this to one "
             "particular kind of person, tied to the fact just taught?",
}

# Ending rule handed to punch_up()'s rewrite pass -- same style-specific intent,
# phrased for a line-level rewrite instruction rather than first-draft generation.
CTA_PUNCHUP_RULES = {
    "SAVE_WORTHY": "Final line: a striking, resonant closing thought or implication that ideally "
                   "recasts the hook. NO command/instruction of any kind -- 'save', 'screenshot', "
                   "'remember', 'look up', 'keep this' are all banned. A thought, never an order.",
    "LOOP": "Final line: a NEW resonant thought that echoes the hook's feeling/image so a replay feels "
            "seamless — but must NOT restate the hook's fact or repeat its exact words/number. No CTA language.",
    "COMMENT": "Final line: a genuine binary question or an arguable claim -- something a real "
               "viewer would type a reply to.",
    "SHARE": "Final line: a specific, identity-relevant reason to send this to one particular kind "
             "of person, tied to the fact just taught.",
}

# Banned generic save-command phrasing -- the exact production failure this
# overhaul targets ("Save this so you remember it." on every video). Now that
# SAVE_WORTHY is a pure resonant payoff with NO nudge allowed, the guard is
# broadened to reject ANY save/screenshot-style command ending (user feedback:
# "that number's worth a screenshot" -- why? it isn't). These hollow commands
# fail validation regardless of the assigned CTA style.
GENERIC_SAVE_CMD = re.compile(
    r"\bsave (this|it|that)\b"
    r"|\bscreenshot (this|it|that|that one)\b"
    r"|\bworth a screenshot\b"
    r"|\b(take|grab|get) a screenshot\b"
    r"|\bmake sure (you|to) save\b"
    r"|\bdon'?t forget to (save|screenshot)\b"
    r"|\byou'?ll (want|need) (this|that|it) again\b"
    # share/tag command endings — same hollow-CTA failure as the save commands.
    # SHARE is out of the rotation, but this belt-and-suspenders guard rejects
    # any "send this to..."/"tag a friend"/"show this to..." close that a model
    # might still produce, so no video ends on a command to redistribute it.
    r"|\bsend (this|it) to\b"
    r"|\bshare (this|it|that) with\b"
    r"|\btag (a|the|your|someone|that)\b"
    r"|\bshow (this|it) to (the|a|your|someone)\b"
    r"|\bsend (this|it) to the (friend|person|one)\b",
    re.I)

# A "save-worthy" moment is engineered into the CONTENT, not just the ending:
# a concrete number, or a stated comparison/rule-of-thumb pattern. This is a
# heuristic, not a semantic check -- it exists to catch the case where a
# script has literally nothing a viewer could reference again (see
# validate()). Bank-fact videos almost always pass automatically via their
# key_terms; this exists for jobs/scripts without a bank fact behind them.
# Renders 194/195/197/198/200 kept aborting an otherwise-fine near-miss on
# this exact gate once Gemini started carrying generation again (2026-08-02) --
# "\d" only matches DIGIT characters, so a script that spells a number out in
# words ("a dozen species," "three thousand years," "a hundred times") reads
# as having zero reference-worthy content even though it plainly does. Widen
# to also catch spelled-out cardinals/scale words, the same "match what
# writers actually produce" fix applied to the word-count window above.
REFERENCE_WORTHY_RE = re.compile(
    r"\d"                                    # any concrete number
    r"|\bthe (size|weight|length|height|speed) of\b"
    r"|\bequivalent to\b|\bthe same (as|size)\b"
    r"|\byou could\b|\benough to\b|\bfor every\b"
    r"|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"dozen|hundred|thousand|million|billion|trillion)\b",
    re.I)

# The specific abstraction failure the Sun video's hook shipped with: a
# "perception vs. reality" construction that only makes sense once the viewer
# already knows the twist ("You're seeing the Sun as it was, not as it is").
# As a FIRST line this reads as confusing, not curious. Deliberately narrow
# (this exact construction) rather than a general vagueness detector, which
# would be too easy to false-positive on legitimately concrete hooks.
ABSTRACT_HOOK_RE = re.compile(
    r"\bas it (was|is),?\s*not as it (is|was)\b"
    r"|\bnot as it (seems|appears)\b"
    r"|\bthings? (aren'?t|are not) what (it|they) (seem|seems|appear|appears)\b"
    r"|\breality isn'?t what it seems\b",
    re.I)

# DANGLING COMPARATIVE — the render-173 "T. rex is closer to you" bug: a hook
# self-graded coherence 8+/10 (and cleared the OLD, stricter 6.8-hard-floor gate
# before any recalibration) yet is objectively broken — "closer to you" than
# WHAT? A comparative word with no completing "than ___" in the SAME sentence
# is meaningless standing alone as an opener; the viewer has nothing to compare
# against. This is a MECHANICAL, zero-LLM check — self-scored "coherence" missed
# this exact pattern, so it can't be the only backstop. Narrow by design (only
# fires on true comparatives), so it can't false-positive on a normal hook.
_COMPARATIVE_WORD = (r"closer|farther|further|nearer|longer|shorter|bigger|smaller|"
                      r"faster|slower|older|younger|earlier|later|more|less|heavier|"
                      r"lighter|higher|lower|deeper|hotter|colder|stronger|weaker")
DANGLING_COMPARATIVE_RE = re.compile(
    rf"\b({_COMPARATIVE_WORD})\b(?!.*?\bthan\b)", re.I)

# TOO-FORMAL / "SOUNDS LIKE A TEXTBOOK" — user feedback on 'Continents in Motion':
# every word can be plain (no jargon) and the script can still sound too smart,
# because the SENTENCE CONSTRUCTION is stiff, not the vocabulary. Three MECHANICAL,
# zero-LLM patterns from the exact shipped lines that read wrong out loud:
# 1) a formal INVERTED question with a long subject crammed between the verb and
#    the predicate ("But is the distance between New York and London fixed?") —
#    nobody talks like this; a real person says "That distance isn't fixed" or
#    "Is that gap staying the same?" (short subject, not a locked-in inversion).
FORMAL_INVERSION_RE = re.compile(
    r"\b(but|and|so|yet)\s+(is|are|was|were|does|do|has|have)\s+(the|this|that|these|those)\b"
    r"[^?]{15,}\?",
    re.I)
# 2) a lone "No."/"Yes."/"Wrong." as an ENTIRE scene's voiceover — reads as a
#    scripted dramatic beat, not natural speech, when a TTS voice speaks it alone.
LONE_YES_NO_RE = re.compile(r"^(no|nope|yes|yep|wrong|correct)[.!]?$", re.I)
# 3) academic connector words — none of these are how anyone talks out loud.
FORMAL_CONNECTOR_RE = re.compile(
    r"\b(however|nevertheless|furthermore|consequently|notably|essentially|"
    r"arguably|thus|hence|moreover|whereas)\b", re.I)

# Named-but-unexplained jargon that has shipped in real videos despite the prompt's
# own PLAIN-SPOKEN-ENGLISH rule already banning it — self-scored 'clarity' keeps
# missing these because the SENTENCE reads smoothly; it's the specific NOUN a smart
# 15-year-old wouldn't know. Grows as new offenders are caught (was antisolar point/
# rhizomorphs/mycelium/hyphae/transdifferentiation/cnidarian/senescence in the
# prompt; render 181 shipped "mycorrhizal networks", render 182 shipped
# "hemocyanin" — both named outright with no plain-language explanation).
JARGON_TERM_RE = re.compile(
    r"\b(antisolar point|refraction index|angular radius|rhizomorphs?|mycelium|"
    r"myceli\w*|hyphae?|transdifferentiation|cnidarian|senescence|mycorrhizal|"
    r"hemocyanin)\b", re.I)


# ---------- VIBE + HYBRID REAL/AI FOOTAGE (mood-matched pacing, movie-like relevance) ----------
# Every video currently gets the same flat pacing/grade/caption energy regardless
# of subject — a violent-eruption video cuts at the identical rhythm as a
# sleeping-dolphin video. VIBE tags the topic's emotional register so main.py can
# vary pacing/color/caption intensity to actually MATCH it — both this channel's
# own data (concrete/visceral topics outperform abstract/passive ones) and
# published short-form retention research agree the right pace is topic-
# dependent, not a constant ("educational content benefits from a steady pace,
# entertainment thrives on varied pacing with unexpected moments").
VIBES = ["chaotic", "peaceful", "eerie", "awe", "visceral", "tense"]


def _normalize_vibe(m):
    """Coerce m['vibe'] to a valid VIBES entry, defaulting to 'awe' (neutral,
    safe) on anything missing/misspelled/invented. SOFT normalization, never a
    validate()-style reject — a vibe tag is a presentation nicety, not a
    correctness gate, and the writer is already under real pressure some
    nights; one more hard-fail reason would inflate the abort rate for no
    content-quality benefit. Mutates and returns m. Pure/testable."""
    v = str(m.get("vibe", "")).strip().lower()
    m["vibe"] = v if v in VIBES else "awe"
    return m


def _assign_footage_mode(scenes):
    """Mark the HOOK (first scene) and PAYOFF (last scene) for a purpose-built AI
    video instead of a generic stock search — the two beats that matter most (the
    shot that has to stop the scroll, and the shot the whole video was building
    to) get something made FOR this exact line instead of whatever a stock
    library happens to have on file. Positional, not content-pattern-based: by
    the time a manifest reaches here, validate() has already forced every
    search_query to be concrete/filmable (UNSTOCKABLE_Q), so there's no
    'impossible to film' signal left to key off — hook/payoff is a reliable,
    deterministic proxy for 'this shot matters most' that holds on every topic,
    and it lines up exactly with FAL_MAX_CLIPS' existing default of 2/video in
    main.py, so this doesn't schedule more AI spend than was already budgeted.
    A single-scene video (near-miss-trimmed edge case) tags just that one scene.
    Pure/testable, no I/O — main.py's fal budget/key gating decides at render
    time whether an 'ai' tag actually spends anything."""
    if not scenes:
        return scenes
    for s in scenes:
        s["footage_mode"] = "real"
    scenes[0]["footage_mode"] = "ai"
    if len(scenes) > 1:
        scenes[-1]["footage_mode"] = "ai"
    return scenes


# ---------- TOPIC NOVELTY / DEDUP ----------
# Concepts we never want to repeat regardless of what memory currently holds --
# e.g. the starling-murmuration / flocking / emergence video the user flagged
# as "we have used this idea before". Matched as substrings against a
# candidate's metaphor + title (and injected into the prompt's avoid list).
BANNED_CONCEPTS = [
    "murmuration", "starling", "flock", "flocking", "swarm", "swarming",
    "emergence", "emergent", "hive mind", "school of fish", "self-organiz",
]
RECENT_DOMAIN_WINDOW = 4    # don't reuse the domain of any of the last N videos
# Some domains are close enough that two back-to-back videos from them feel like
# "the same kind of video" even though the exact domain string differs — e.g.
# geology "Hawaii is drifting" followed by earth "the inner core is Sun-hot"
# (renders 69 then 70) both read as deep-earth science. Group those into one
# FAMILY so the recent-domain dedup below treats the whole family as used. Any
# domain not listed is its own family (unchanged behaviour).
DOMAIN_FAMILIES = {"geology": "earth", "earth": "earth", "weather": "earth"}
def _domain_family(domain):
    return DOMAIN_FAMILIES.get(domain, domain)
TOPIC_SIM_THRESHOLD = 0.62  # difflib ratio between metaphors above this = dupe
TOPIC_TOKEN_OVERLAP = 0.6   # content-word overlap fraction above this = dupe


def _metaphor_too_similar(metaphor, history):
    """True if `metaphor` is a near-duplicate of any recent video's metaphor:
    substring either way, high difflib ratio, or heavy content-word overlap.
    Catches 'bird flock' vs 'starling murmuration' style repeats that an exact
    or substring-only check would miss."""
    import difflib
    c = (metaphor or "").lower().strip()
    if not c:
        return False
    c_tokens = set(re.findall(r"[a-z]{3,}", c))
    for h in history:
        hm = (h.get("metaphor", "") or "").lower().strip()
        if not hm:
            continue
        if hm in c or c in hm:
            return True
        if difflib.SequenceMatcher(None, c, hm).ratio() >= TOPIC_SIM_THRESHOLD:
            return True
        h_tokens = set(re.findall(r"[a-z]{3,}", hm))
        if c_tokens and h_tokens:
            shared = c_tokens & h_tokens
            if shared and len(shared) / min(len(c_tokens), len(h_tokens)) >= TOPIC_TOKEN_OVERLAP:
                return True
    return False


def _hits_banned_concept(*texts):
    blob = " ".join(t or "" for t in texts).lower()
    return any(b in blob for b in BANNED_CONCEPTS)


def load_memory():
    try:
        with open(MEMORY) as f:
            return json.load(f).get("history", [])
    except Exception:
        return []

def save_memory(history, entry):
    history.append(entry)
    history = history[-14:]
    with open(MEMORY, "w") as f:
        json.dump({"history": history}, f, indent=2)


def _queue_files():
    """Queued manifest filenames, oldest first (FIFO by ms-timestamp prefix)."""
    try:
        return sorted(f for f in os.listdir(QUEUE_DIR) if f.endswith(".json"))
    except FileNotFoundError:
        return []


def enqueue_manifest(manifest, video_id):
    """Persist a finished manifest into the buffer instead of rendering it now.
    Filenames are ms-timestamp-prefixed so the queue drains in the order it was
    filled. The batch still updates memory_<page>.json between generations (see
    main()), so a buffer filled in one run is topic-diverse, not five of the
    same fact."""
    os.makedirs(QUEUE_DIR, exist_ok=True)
    fname = f"{int(time.time() * 1000):013d}_{_slugify(video_id) or 'video'}.json"
    path = os.path.join(QUEUE_DIR, fname)
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[queue] enqueued {manifest.get('title','?')!r} -> {os.path.basename(path)} "
          f"(queue depth {len(_queue_files())})")


def dequeue_to(dest):
    """Pop the oldest queued manifest to `dest` with ZERO LLM calls. Returns 0 on
    success, 3 if the queue is empty (the caller then falls back to live
    generation). A malformed queued file is discarded and the next one tried, so
    one bad entry can't wedge the buffer."""
    for fname in _queue_files():
        src = os.path.join(QUEUE_DIR, fname)
        try:
            with open(src) as f:
                manifest = json.load(f)
            if not isinstance(manifest, dict) or "scenes" not in manifest:
                raise ValueError("queued file is not a manifest")
        except Exception as e:  # noqa: BLE001
            print(f"[queue] discarding unreadable queued file {fname} ({e})")
            try:
                os.remove(src)
            except OSError:
                pass
            continue
        with open(dest, "w") as f:
            json.dump(manifest, f, indent=2)
        os.remove(src)
        print(f"[queue] dequeued {manifest.get('title','?')!r} -> {dest} "
              f"({len(_queue_files())} left in buffer)")
        return 0
    print("[queue] buffer empty — no pre-generated manifest to render; "
          "caller should fall back to live generation")
    return 3

# ---------------------------------------------------------------------------
# PAGE IDENTITY — the thing that turns "a page that posts science facts" (a
# commodity) into a page people FOLLOW and binge. A specific persona + lens +
# tonal range, injected into every script so the channel sounds like a someone,
# not a fact bot. Swappable per page later; this is the science page's identity.
# ---------------------------------------------------------------------------
PAGE_IDENTITY = (
    "CHANNEL IDENTITY — this is who the page IS (bake it into voice and choices, don't state it):\n"
    "You are the narrator of \"Stranger Than It Sounds\": the channel that reveals ordinary reality "
    "is far weirder, bigger, and more unsettling-beautiful than it looks. The vibe is a calm, precise, "
    "quietly eerie documentary narrator — never hype-y, never 'you won't BELIEVE', never an exclamation "
    "salesman. You state astonishing true things plainly and let the strangeness do the work. The "
    "viewer should feel a small chill of awe, like the floor of reality just shifted under them.\n"
    "WHAT MAKES THIS PAGE UNIQUE (lean into it): brutal SPECIFICITY (real names, real numbers, the "
    "actual mechanism — never vague), and finding the UNSETTLING or awe-inducing angle inside a normal "
    "thing. A viewer should think 'I will never see [ordinary thing] the same way again.'\n"
    "EMOTIONAL REGISTER for THIS video (pick the one that fits the fact and commit to it, so the page "
    "has range across videos, not one monotone): AWE (cosmic/scale), UNSETTLING (a quiet dread about "
    "something normal), BEAUTIFUL (something ordinary revealed as gorgeous), or DARKLY FUNNY (absurd "
    "but true). Whichever you pick, keep the calm precise delivery.\n"
)


def build_prompt(job_name, job_desc, avoid, fact=None, avoid_openers=None, cta_style="SAVE_WORTHY",
                 dossier=None, hook_frame=None):
    frame_block = ""
    if hook_frame:
        frame_block = (f"\n\nTHIS VIDEO'S OPENING MOVE ({hook_frame[0]}): {hook_frame[1]}\n"
                       f"Use this SHAPE for the first line so the page doesn't feel formulaic — but "
                       f"still obey every HOOK rule below (concrete, instantly pictured, 8-14 words, "
                       f"no setup needed). The frame changes the opening's structure, not the rules.")
    series_block = ""
    if SERIES:
        part = SERIES_PART or "1"
        series_block = (f"\n\nSERIES MODE: This is PART {part} of an ongoing series titled \"{SERIES}\". "
                        f"Open by referencing it's part {part} of the series (e.g. 'Part {part}: ...'). "
                        f"Cover ONE distinct sub-topic that fits the series theme but does NOT repeat earlier parts. "
                        f"End by teasing the NEXT part to make viewers follow so they don't miss it "
                        f"(e.g. 'Follow so you don't miss part {int(part)+1}.'). "
                        f"Put the series name + part number in the first on_screen_text and first caption.")
    fact_block = ""
    if fact:
        key_terms = fact.get("key_terms", [])
        whatif = fact.get("whatif", "")
        wow = fact.get("wow", "")
        key_terms_block = ""
        if key_terms:
            key_terms_block = (
                f"- NAME THE REAL THING (for credibility, not for stat-dumping): somewhere in the "
                f"voiceover, use the real proper noun(s) from these specifics so the video is concrete "
                f"and checkable, not vague: {key_terms}. Say 'potassium-40', not 'a naturally occurring "
                f"isotope'. BUT you do NOT have to recite the numbers in this list — include a number "
                f"ONLY if it creates wonder or a felt image; skip any number that's just a dry "
                f"measurement. Name the thing; let the IDEA, not the digits, carry the video.\n")
        whatif_block = ""
        if whatif:
            whatif_block = (
                f"- THE CENTRAL QUESTION (curiosity gap) — HARD REQUIREMENT, ENFORCED: one of the "
                f"first FOUR lines (the hook or scenes 1-3) MUST literally end in a question mark "
                f"'?'. A script with no '?' in its first four lines is REJECTED and regenerated, so "
                f"do it on the first try. Pose this question in your own plain words, based on: "
                f"\"{whatif}\"\n"
                f"  It's fine to lead with a punchy STATEMENT hook and make the very next line the "
                f"question (e.g. hook: 'Your phone is being hit by proof that time bends.' then "
                f"scene 2: 'So why doesn't a particle that should die in an instant ever reach you?'). "
                f"Either the hook itself is the question, or an early scene is — but the '?' must be "
                f"there.\n"
                f"  Then ANSWER it for real as the MIDPOINT TWIST payoff (around scene 5-7) — a "
                f"genuine, concrete answer, not a tease or a shrug. But the payoff is the mind-bending "
                f"IDEA — the 'oh, THAT'S why / that's what it means' realization that reframes the whole "
                f"thing — NOT a recited number. The viewer must walk away thinking differently, not just "
                f"having heard a statistic.\n")
        wow_block = ""
        if wow:
            wow_block = (
                f"- ESCALATION FUEL: after the midpoint payoff, use this verified supporting detail "
                f"as a further escalation rung (a 'but here's the even wilder part') instead of "
                f"inventing a new stat: \"{wow}\"\n")
        fact_block = (f"\n\n=== THE VERIFIED FACT FOR THIS VIDEO (this is TRUE — build the whole script around it) ===\n"
                      f"\"{fact['fact']}\"\n"
                      f"Angle: {fact['angle']}.\n"
                      f"ABSOLUTE RULES FOR ACCURACY:\n"
                      f"- Stay entirely on THIS topic — but tell its FULL, rich story (draw on the RESEARCH "
                      f"section below): don't drift to unrelated topics, don't stay shallow.\n"
                      f"- Do NOT FABRICATE. Every number/name must come from the verified fact, key terms, "
                      f"wow detail above, OR the RESEARCH section below. If unsure of a number, describe the "
                      f"mechanism instead of inventing one.\n"
                      f"- Never state two different numbers for the same thing. Accuracy over drama.\n"
                      f"{key_terms_block}{whatif_block}{wow_block}"
                      f"- Include at least ONE moment that makes the viewer physically FEEL the idea — "
                      f"a picture-able comparison or a mind-bending reframe (e.g. not '400 million years' "
                      f"alone but 'before Saturn even had rings'; not 'Everest is tall' but 'its summit is "
                      f"limestone full of sea creatures that died on an ancient ocean floor'). It can be a "
                      f"felt image OR a strange implication — but it must land as wonder, not a raw stat.\n"
                      f"- For the footage search_query fields, prefer these proven matches: "
                      f"{[q for q in fact.get('queries', []) if not UNSTOCKABLE_Q.search(q)]}.\n")
    dossier_block = ""
    if dossier:
        bullets = "\n".join(f"  {i+1}. {d}" for i, d in enumerate(dossier))
        dossier_block = (
            f"\n\n=== RESEARCH: {len(dossier)} DISTINCT TRUE FACETS OF THIS TOPIC (this is your raw material) ===\n"
            f"{bullets}\n"
            f"HOW TO USE THIS RESEARCH (this is the difference between an interesting video and a boring one):\n"
            f"- Each scene must be built on a DIFFERENT item above. Walk the viewer through the topic like a "
            f"curious scientist revealing one new surprise at a time — never restate a point already made.\n"
            f"- The hook, the midpoint twist, and the final payoff must each use a DIFFERENT facet. If two "
            f"scenes would make the same point, DELETE one and pull a fresh facet from the list.\n"
            f"- Pick the 6-8 MOST surprising, most 'wait-WHAT' facets and order them so each raises a new "
            f"question the next one answers (curiosity chain). Skip the boring/obvious ones.\n"
            f"- Keep the specific detail (the number, the name, the mechanism) in the spoken line — that "
            f"specificity is what makes it feel like real knowledge, not filler.")
    opener_block = ""
    if avoid_openers:
        opener_block = (
            f"\n\nHOOK VARIETY: your last several videos' hooks all opened the same way "
            f"({avoid_openers}). Start THIS hook with a different sentence structure or "
            f"opening word — not just a synonym swap of the same structure.")
    return f"""You write scripts for "Stranger Than It Sounds", a faceless science page built to make people FOLLOW and binge — not just watch one video.

{PAGE_IDENTITY}{fact_block}{dossier_block}

THIS VIDEO'S JOB: {job_name}. {job_desc}{frame_block}

ADDICTIVE CRAFT (what separates a bingeable page from the 10,000 identical AI fact pages):
- STRUCTURE IT AS A TINY MYSTERY, not a list: open a real question the brain CANNOT ignore, build
  tension, then reveal. Each scene should make the viewer need the next one. A list of facts is
  boring even when every fact is true; a reveal with tension is not.
- QUESTION HOOK the mind auto-answers: the strongest hooks are a concrete question the viewer starts
  answering in their head ("How much of you isn't technically human?", "What's the oldest thing you'll
  touch today?") — or a flat claim so specific it demands the 'how is that possible?' The brain can't
  scroll past an open loop.
- LEAVE THE PAGE, NOT JUST THE VIDEO, OPEN: the final line should quietly imply there is a whole world
  of this strangeness (this is one of many) — a resonant thought that makes them want the NEXT one.
  NOT a command ('follow me', 'save this') — the pull comes from the feeling that reality is full of
  these and this page finds them.
- THE POINT IS A THOUGHT, NOT A NUMBER (this is the most important rule on the page). Every video must
  leave a smart adult THINKING differently — "huh, I never thought about it that way", "that changes how
  I see this", a genuine mind-bender they'll turn over in their head — NOT just observing facts and
  numbers scroll by. You are writing a little MIND EXERCISE, not a stats readout. Test every script:
  strip out every number — is there still a fascinating IDEA left? If nothing interesting remains once
  the numbers are gone, the script has no soul; rewrite it around the strange idea, or it fails.
  * BIG/SMALL IS NOT INTERESTING BY ITSELF — magnitude alone (how many, how tall/fast/old, how many
    combinations, how many times bigger) is DEAD trivia and will be rejected. A number earns its place
    ONLY if it reframes reality or matters to a real person. WHO-CARES TEST: would someone retell this at
    dinner? Does it overturn an assumption or expose a hidden mechanism? "Everest is 8,849 m" is boring;
    "Everest's summit is seashells from a vanished ocean" makes you wonder — because it REFRAMES, not
    because it's big.
  * Numbers are seasoning, not the meal: at most 1-2, and only when a number becomes a felt image
    ("older than Saturn's rings"). Never a number as the wow by itself. Lead every scene with the IDEA,
    never the statistic. Plain everyday words only — never a term you'd have to look up.
- SAY NUMBERS THE WAY A PERSON WOULD OUT LOUD — never scientific/math notation ("10^27", "ten to the
  twenty-seventh power", "3.5 x 10^8"); say "more of them than stars in the whole sky", "a billion
  billion". If a huge number can't be made graspable in plain speech, drop it and describe how
  staggering it is instead.

PROVEN RULES (every one is backed by 2026 TikTok performance data — follow them all):

HOOK (first 2 seconds decide 70% of retention):
- First spoken line = 8-14 words. A contrarian claim or direct call-out that opens a curiosity gap. NOT a description.
- FRONT-LOAD THE SHOCK (#1 retention lever — most viewers drop at 0:01): the most surprising word lands
  in the FIRST 3-4 words, no wind-up. BANNED first-line openers: "Did you know", "Have you ever",
  "Imagine", "What if I told you", "Here's", "This is", "Ever wonder". BAD: "Have you ever wondered what
  your stomach acid can do?" GOOD: "Your stomach acid could dissolve a razor blade." Open cold on the
  shock. (A curiosity '?' still appears by scene 2, never as the very first line.)
- MAKE LITERAL SENSE (non-negotiable): every line must be TRUE and have clear referents — no vague
  pronoun a listener can't resolve. State the actual fact PLAINLY. BAD: "your great-grandparents saw
  Pluto's start, but it won't finish" (start of WHAT? finish WHAT? — meaningless). GOOD: "Pluto takes
  248 years to circle the Sun — it hasn't finished a single lap since we discovered it in 1930." If a
  smart listener could ask "wait, what does that even mean?", it is BROKEN — rewrite it.
- NEVER a DANGLING comparative: any word like closer/farther/faster/older/bigger/more/less MUST
  complete "...than ___" in the SAME sentence, especially in the hook. BAD: "T. rex is closer to you"
  (closer than what? — meaningless on its own). GOOD: "T. rex is closer to you in time than to
  Stegosaurus." A comparison with no stated other side of the comparison is not a fact, it's a fragment.
- Address the viewer directly ("you"/"your"). Self-relevant beats abstract.
- STAKES BEAT TRIVIA (backed by THIS channel's own analytics — the single strongest signal we have):
  a hook framed as a HIGH-STAKES CONSEQUENCE the viewer would live through ("An airlock bursts and
  you're sucked into space — you have fifteen seconds") held 2.5x the watch time and 4x the
  completion of a passive question ("how many colors can you see?"). So wherever the fact allows,
  frame the hook as something HAPPENING — a danger, a survival scenario, a what-happens-if,
  a consequence to the viewer's own body — not a quiz they can shrug off. A passive "how many /
  how much / how sensitive / can you see" question is the WEAKEST possible opener; only use a plain
  question if it carries real stakes or a will-get-it-wrong dare. Give the viewer something to
  survive, not something to answer.
- CONCRETE, NOT ABSTRACT (critical): the hook must be something a viewer instantly PICTURES, self-
  contained with no setup needed — not a mood, not a musing about perception vs. reality, not a
  sentence that only makes sense once you already know the twist.
  GOOD: "Your body is mostly empty space." (a concrete, physical, immediately graspable claim)
  GOOD: "Sharks are older than trees." (a specific, checkable, instantly pictured comparison)
  BAD: "You're seeing the Sun as it was, not as it is." (abstract — the viewer can't picture
  anything from this alone; it only lands after the explanation, so it reads as confusing, not
  intriguing, as the FIRST line of the video)
  BAD: "Reality isn't what it seems." (vague fortune-cookie phrasing, not a real claim)
  If your hook needs the rest of the script to make sense, rewrite it — name the concrete thing
  (a body part, an animal, an object, a number) up front.
- DON'T PRESUPPOSE A PERCEPTION NOBODY HAS HAD: a "why does X happen" hook only works if the viewer
  has actually NOTICED X as a distinct thing before you named it — otherwise the question reads as
  testing knowledge nobody has, not opening a curiosity gap (user feedback, the petrichor video: "no
  one knows that... asking assumes this is commonly known"). BAD: "Why does your nose pick up a dark
  biological signal every time it rains?" (nobody has ever consciously thought of rain-smell as "a
  dark biological signal" — there is nothing to wonder about yet). GOOD: "Ever wonder why you can
  smell rain coming?" (starts from something almost everyone has actually experienced and can
  instantly say "yes, that's real," THEN the script reveals the surprising specific mechanism).
  Ground the hook in a universal, lived sensation/experience/memory the viewer immediately recognizes
  as true of themselves — never in a technical framing of the phenomenon that IS the video's reveal.
- OPEN COLD ON THE SHOCK — no scene-setting preamble (backed by THIS channel's own analytics:
  videos that opened calm or scenic — "a peaceful lake…", a slow establishing shot — bled the viewer
  by ~4 seconds; average watch time was stuck at 4.5s of a 40s video). The single most surprising
  thing must be the VERY FIRST words, never the second sentence. Do not warm up, do not set a scene,
  do not narrate the footage — hit them with the claim instantly.
- OPENING SHOT MUST STOP THE SCROLL: scene 1's search_query must name a visually DYNAMIC, high-
  contrast subject (motion, a bold close-up, a striking creature or object) — never a dark, static,
  ambient, or "establishing" landscape. The first frame is also the thumbnail; a dim or calm frame
  reads as skippable in the feed. Prefer a bright, punchy, in-motion image on the very first scene.

STORY ENGINE (the #1 ranking signal is completion — earn every second):
- {LENGTH_HINT}
- HOLD SECONDS 3-8 (THIS channel's analytics: average watch is ~8 seconds — most viewers leave during
  scene 2 or 3, right after the hook). So scene 2 must ESCALATE the hook, never slow down to explain,
  define, or give background. Plant the payoff question early and keep it OPEN, and give a concrete
  reason to stay in EVERY scene. Scene 2 is make-or-break: make it your SECOND-most-surprising line,
  not setup — the video is lost in the first 8 seconds or not at all.
- {SCENE_MIN}-{SCENE_MAX} SHORT scenes. Each scene's voiceover is ONE punchy sentence (fast pacing = +34% retention).
- Total narration MUST be {WORD_LO}-{WORD_HI} words — this is the HARDEST constraint; under {WORD_HARD_LO} or over
  {WORD_HARD_HI} words is REJECTED outright, so budget it deliberately. Do the math as you write. If you're past
  {WORD_HI}, TIGHTEN wording (never DELETE a whole scene — every scene is a distinct escalation beat and losing
  one flattens the payoff); if under {WORD_LO}, you're too thin — add one more real fact from the research,
  never filler. A tighter video beats a padded one: competitors win on COMPLETION, so cut every non-essential
  line and keep only the strongest "wait, what?" beats. Density of surprise over quantity of words.
- PER-SCENE LENGTH: aim {WORDS_PER_SCENE}. NEVER exceed {SCENE_WORD_CAP} words
  in a single scene — a long
  run-on scene wedged between short punchy ones is jarring and reads as choppy, not varied. Vary
  scene length a little for rhythm, but no scene should be dramatically longer than its neighbors.
- BREATHING ROOM: this is spoken narration, not a wall of text — each scene is its own sentence with
  a natural beat before the next one starts. The video should feel PACED, not like it never stops
  talking. If you can't say a scene's line out loud in one comfortable breath, it's too long or too
  packed with clauses — split the idea or cut it.
- ONE IDEA PER SENTENCE, ESPECIALLY WITH NUMBERS: never comma-splice two separate claims/comparisons
  into one breath — the TTS voice reads a stacked sentence in a flat, hurried monotone with no natural
  rhythm (user feedback, the petrichor video: "at five parts per trillion, hundreds of times more
  sensitive than a shark tracking blood" — "is not spoken in a methodic way or rhythm"). BAD (two ideas
  crammed into one comma-spliced sentence): "You detect geosmin at five parts per trillion, hundreds
  of times more sensitive than a shark tracking blood." GOOD (split into two beats, each with its own
  landing): "You detect geosmin at five parts per trillion. That is hundreds of times more sensitive
  than a shark tracking blood in water." If a sentence has two numbers or two comparisons, it is
  almost always two scenes' worth of content wearing one scene's punctuation — split it.
- SPEAK IN FLOWING SENTENCES, NOT FRAGMENTS (this is read aloud by a voice — write for the EAR):
  every scene must be a COMPLETE, natural-sounding sentence that a narrator can say smoothly in one
  breath, with a real subject and verb. Do NOT write clipped telegram fragments or stacked noun
  phrases — they make the narrator sound choppy and robotic, like he's punching out words instead of
  talking. BAD (fragments): "Muons. Born miles up. Racing down. Impossible speed." GOOD (flows):
  "These particles are born miles up in the sky and race toward the ground at nearly the speed of
  light." Read every line aloud in your head; if it sounds like a list instead of a sentence, rewrite
  it so it flows.
- ESCALATION LADDER (critical, ZERO exceptions): the core reveal — the specific number or comparison
  from the verified fact — may appear in EXACTLY ONE scene, ONE time, as the payoff moment. This is
  a hard rule, not a suggestion: if you catch yourself writing that same number, comparison, or its
  paraphrase in a second scene, DELETE that scene's line entirely and write a genuinely different
  fact or angle instead. Every other scene must teach something the payoff scene did NOT — the setup
  question, the mechanism/why it's true, a second independent consequence, what it means for YOU —
  never a rephrasing of the reveal in new words. A script that circles back to the same reveal even
  twice is an automatic FAIL: each scene is a NEW fact about the topic, not an echo of the last one:
  what -> how -> why it's stranger than it sounds -> what it means for YOU. CONCRETE EXAMPLE OF THE
  FAIL: hook says "X can survive losing 60% of its body mass" — a LATER scene must NOT also say
  "even after losing more than half its mass, it survives" — same fact, new words, still a FAIL.
  Before writing each scene, check every EARLIER scene: does this one repeat a number, name, or
  claim already made, even paraphrased? If yes, replace it with something that hasn't been said yet.
- MIDPOINT TURN: around scene 5-7, pivot to a genuinely NEW dimension of the topic — a second,
  independent surprise the viewer has not heard yet. The turn is carried by the NEW FACT itself,
  not by a stock transition phrase. BANNED opener phrases (overused, and they force the script into
  a vague "even weirder" register instead of just telling the next real thing): "that's not even
  the strange/strangest part", "but here's where it gets weird", "and here's where it stops making
  sense", "but that's not all". Just STATE the new fact plainly and let it surprise on its own
  ("The same physics is why a rainbow has no bottom." lands harder than "and that's not even the
  strangest part"). The turn must NOT restate, rephrase, or circle back to the hook or anything
  already said. If you don't have a real second surprise, don't force a turn — keep teaching new facts.
- EVERY FELT COMPARISON MUST BE LITERALLY TRUE, not just grand-sounding: a technique, never a copied
  example, and each must mean something concrete. Do NOT manufacture meaningless phrases ("we are
  witness to 80,000 fleeting civilizations" pictures/verifies nothing). If a comparison isn't both
  accurate and instantly graspable, state the plain fact instead.
- PLAIN SPOKEN ENGLISH (a smart 15-year-old must get every line on first listen): this is narration,
  not an essay. Use everyday words. If a precise scientific term is the actual subject, EXPLAIN it in
  plain words instead of just naming it — say "the point in the sky opposite the sun" rather than
  "the antisolar point"; say "spreads out" or "opens up" rather than "unfurls". BANNED: literary/purple
  verbs (unfurls, cascades, dances, whispers, beckons) and unexplained jargon (antisolar point,
  refraction index, angular radius, rhizomorphs, mycelium, hyphae, transdifferentiation, cnidarian,
  senescence, mycorrhizal (say "underground fungus threads connecting the trees" instead of naming
  the mycorrhizal network), hemocyanin (say "a copper-based molecule" or just "why the blood runs
  blue" instead of naming it) — say "underground root-like threads" / "reverses back into a baby" /
  "aging" instead. This check is MECHANICAL now (validate() rejects these outright), not a suggestion.
  HARD RULE: no single word may be longer than 13 letters — if the real term is longer (e.g.
  "transdifferentiation", "photosynthesis"), you MUST replace it with a plain phrase, because a long
  word ALSO overflows the on-screen caption and gets cut off at the edges. One unfamiliar word is
  enough to make a viewer feel dumb and swipe. Clear and concrete beats clever and ornate every time.
- TALK, DON'T WRITE (user feedback on 'Continents in Motion'): even with zero jargon words, a sentence
  can still sound like a textbook exam question, not a person talking. BAD (a real shipped line):
  "But is the distance between New York and London fixed?" — a long, formal subject crammed between
  "is" and the adjective reads stiff and academic, and the flat "No." that follows sounds like a scripted
  dramatic beat, not speech. GOOD: "You'd think that distance stays the same. It doesn't." or "That gap
  isn't fixed — it's growing." Read every line OUT LOUD before finalizing: if it sounds like something
  a textbook would print rather than something a friend would say across a table, rewrite it as a short,
  plain STATEMENT. Avoid the inverted "is/are/does/do/was/were/has/have + [long noun phrase] + [adjective]?"
  question shape entirely — ask short, direct questions ("Why?" "How?" "What changed?") or just state the
  fact. NEVER a lone "No." / "Yes." / "Wrong." as an entire scene by itself — fold the answer into the
  next sentence instead. BANNED formal connector words: however, nevertheless, furthermore, consequently,
  notably, essentially, arguably, thus, hence, moreover, whereas — none of these are how people talk.
- TTS-SAFE WORDING: this is read aloud by a text-to-speech voice that mis-says some homographs. Do NOT
  use the VERB "lives" (the voice reads it like the noun "lives") — write "survives", "exists", "still
  grows", or "is alive" instead. Also avoid other noun/verb homographs where the wrong reading would
  confuse: "tears", "wound", "bass", "lead", "close" (as a verb). Pick an unambiguous synonym.
- STRONGEST PAYOFF WINS: prefer a concrete, surprising, everyday consequence over an abstract musing.
  For a rainbow, "this is why a rainbow has no bottom — and why you can never reach the end of one"
  beats "everyone sees their own private rainbow". Ask: does the payoff give the viewer a crisp new
  thing they can repeat to a friend? If it's a vague feeling, replace it with the concrete fact behind it.
- PAYOFF IS AN IDEA, NOT A NUMBER (the #1 reason scripts get rejected — most rejected drafts fail HERE,
  not on hook or clarity): a raw statistic is NOT a payoff, even an impressive one. WEAK payoff: "Mount
  Everest is 8,849 meters tall." / "That's 37 trillion cells." / "It happens 100,000 times a day." Those
  are facts, and a smart viewer just shrugs at a number. The payoff must be the REFRAME — what that fact
  changes about how the viewer sees the thing. STRONG payoff (same topic): "the rock at Everest's summit
  is limestone packed with fossil seashells — the highest point on Earth used to be the floor of an
  ocean." Before writing the final scene, run this test: strip out every number — is there still a
  mind-bending IDEA left standing on its own? If the answer is no, you don't have a payoff yet; find the
  mechanism or implication behind the number and end on THAT instead. This applies with extra force in a
  SHORT ~30s video — do not let a tight word budget push you toward closing on a stat because it's the
  fastest way to end the scene.
- The ending must LAND on this video's assigned ending style (see ENDING section below). Do NOT
  trail off, restate the premise, or stack two different endings together. A real shipped failure:
  "Could our communication systems become as resilient as a forest's? What would you choose, a world
  with tree-like networks or without?" -- two separate questions back to back (a musing rhetorical one,
  then a second, different binary one) reads as indecisive, not a clean landing. Pick ONE final line
  that does the ending style's job and stop there.

SEARCH DISCOVERY (now as important as hashtags):
- Pick ONE core keyword phrase (what someone would type to find this). It must be PLAIN, everyday
  words a normal person would actually search — 1-3 common words, NOT a technical/jargon term and
  NOT a scientist's name for the concept. This word also pops on-screen in gold, so it has to read
  as instantly meaningful, not like a textbook heading.
  GOOD: "bending time", "living fossil", "frozen light", "the oldest tree".
  BAD: "einstein time dilation", "muon flux", "quantum tunneling", "antisolar point" (jargon —
  nobody types these and they read as cold on screen).
- Put it in the hook, in at least 2 on_screen_text labels, and in the first caption.

SHARES (THE #1 weighted signal — 10x a like). Engineer the video to be SENT to a friend:
- The fact must be "send-worthy": so surprising or identity-relevant the viewer thinks "I have to show ___ this."
- Somewhere in the script (not necessarily the ending), include a beat that hands the viewer a
  reason to share it with someone specific.

SAVES (5x a like) — THIS COMES FROM THE CONTENT, NOT A COMMAND:
- Telling someone to save a video does not make them save it. A save happens because the video
  contains something genuinely worth referencing again. So: somewhere in the script, land at least
  ONE concrete "screenshot-this" moment — a specific number, a counterintuitive rule of thumb, or a
  vivid comparison the viewer would actually want to remember or reuse later (prove someone wrong
  with it, cite it, look it up again). This is mandatory REGARDLESS of this video's ending style
  below. Do not just assert the fact is surprising — make the actual detail specific enough that a
  person could repeat it verbatim.

{CTA_ENDING_RULES.get(cta_style, CTA_ENDING_RULES["SAVE_WORTHY"])}

COMMENTS (binary questions outperform — easiest to answer, drive depth):
- Independent of the ending style above, plant ONE line somewhere in the script that provokes a
  reply: either a BINARY question ("Team A or Team B?", "Did you know this — yes or no?") OR a claim
  people will argue with ("no way", "that's not true"). (If this video's ending style is COMMENT,
  the ending line itself can serve as this beat — don't force a second one.)
- Put a binary/question version in the FIRST caption too (comments often come from the caption).

CONTENT (CRITICAL):
- The video MUST teach ONE concrete, TRUE, verifiable science fact or mechanism — a real number, a real process, a real cause.
- The fact must be GENUINELY SURPRISING — something most adults do NOT know. Aim for "wait, WHAT?" not "yeah I knew that."
- BANNED TOPICS (too obvious/overdone): static electricity, the water cycle, why the sky is blue, photosynthesis basics, "we only use 10% of our brain", basic volcano/rainbow facts.
- BANNED STYLE: vague philosophy, mysticism, fortune-cookie lines, metaphors-as-substance, motivational fluff.
- Prefer the strange and specific: deep-sea biology, quantum weirdness made real, the body's hidden systems, cosmic scale, time dilation, animal superpowers, numbers that sound fake but are true.
- If a 12-year-old couldn't learn a NEW fact from it, it's wrong. Substance + surprise over mood.
- Visually deliverable with real stock footage (nature, space, ocean, animals, cities, body, weather, hands, household).
- No "imagine", no "did you know", no filler.

AVOID these recent topics entirely: {avoid}{series_block}{opener_block}

FOOTAGE QUERIES (the #1 visual-quality lever — a wrong clip breaks trust instantly):
- Each scene needs a 2-5 word query for something a videographer ACTUALLY FILMS: a concrete subject +
  action/setting (animals, nature, weather, oceans, space, cities, machines, food, hands, reactions).
- NEVER copy words out of the scene's spoken sentence into the query. The query is a NOUN PHRASE for a
  filmable object/scene, not a fragment of the narration. A stock library has nothing for grammar
  fragments — they return junk that gets rejected and the scene falls back to a worse image.
  BAD (voiceover fragments — every one returned garbage): "satellites farther gravity", "differences
  silently adjusts", "microseconds gaining causes", "staggering million seconds".
  GOOD (real filmable subjects for those same lines): "gps satellite orbiting earth", "atomic clock
  laboratory", "car dashboard navigation map", "stopwatch close up". Name the THING on screen.
- BANNED query words (free libraries have nothing real — they degrade to random flesh/lab/texture):
  anatomy, organ, cell/cells, microscope, diagram, xray, molecular, atom, quantum, abstract, concept, system.
- If the concept is invisible (acid, time, gravity, DNA, nerve speed), use a VISUAL METAPHOR libraries
  DO have: "bubbling green liquid" (acid), "hourglass sand falling" (time), "dominoes falling" (reactions).
- REAL FOOTAGE ONLY, never cartoons/3D-emoji/clip-art. BANNED metaphor queries (pull cheesy CGI that
  makes the video look broken — a 3D money-emoji once landed in a starlight video): money, coins, dollar,
  cash, emoji, icon, cartoon, 3d render, animation, infographic, clock. Pick a real photographable subject
  (for space: "night sky stars", "telescope observatory", "galaxy nebula") — never an abstract stand-in.
- MATCH THE MOMENT: the query depicts the exact thing THAT sentence is about, tracking the narration
  second-by-second — "a dying tree feeds its neighbours" -> "dead fallen tree forest", not a bare "forest".
- DON'T REACH FOR "NIGHT SKY STARS"/COSMIC IMAGERY AS A DEFAULT FILLER (render 209): that query is only
  right when the SENTENCE is actually about space/astronomy. A payoff line about, say, human ancestry
  or biology has NOTHING to do with a starfield — querying one anyway ships an off-topic clip that
  breaks trust in the final seconds. If a scene feels hard to picture, describe ITS OWN concrete subject
  instead of defaulting to a pretty, unrelated cosmic shot.
- PREFER MOVING FOOTAGE: subjects real stock VIDEO exists for (flowing lava, a swimming animal, crashing
  waves, a hand touching something), not static objects that only return stills. Motion beats slideshow.
- Every scene's query must be VISUALLY DISTINCT from the others — the same three shots on loop reads as spam.
- NAME THE ACTUAL SUBJECT by name when the video is about a specific thing ("naked mole rat", not "rodent
  close up"; "Saturn rings", not "planet space") — a generic groundhog in a naked-mole-rat video is a miss
  viewers catch instantly. The hook scene and payoff scene MUST name the specific subject; only fall back to
  a generic category/metaphor when it genuinely can't be filmed.
- LEAD WITH THE FILMABLE NOUN, not a modifier (render 181/184 bugs): "mother tree" and "sea cucumber"
  put the modifier BEFORE the subject, and a search on just the leading word ("mother", "sea") pulled a
  human mother-and-child clip and a literal kitchen VEGETABLE instead of the tree/animal. Reorder so the
  concrete filmable subject comes FIRST: "tree, old growth" not "mother tree"; "sea cucumber animal
  seafloor" not "sea cucumber" alone (the extra word "animal" breaks the tie with the vegetable). Same
  fix for any name that doubles as an unrelated common word or object (a "crane" bird vs. a crane; a
  "ram" the animal vs. to ram) — add a disambiguating word.
- ONE EXCEPTION — a MANUFACTURED MODEL used only as a COMPARISON PROP (a specific plane, car, ship, phone
  that is NOT the video's real subject): stock can't match an exact model, so a "Boeing 747" line playing
  over a generic Airbus clip breaks trust. For such incidental props, say the GENERIC type in BOTH the
  voiceover AND the query — "a jumbo jet", "a passenger plane", "a cargo ship" — so the words always match
  whatever clip appears. (Still name the video's actual subject; this is only for throwaway comparison props.)

For each scene give: one-sentence voiceover, a 2-4 word on_screen_text label (punchy, include the keyword where natural),
and the search query as specified above.

VIBE: pick the ONE word from [chaotic, peaceful, eerie, awe, visceral, tense] that matches how this topic actually
FEELS, not a default. A volcano/explosion/attack story is chaotic or tense, not awe; a deep-ocean/space/sleep fact
is peaceful or eerie; a body-horror/gross/visceral fact (stomach acid, parasites, decay) is visceral; a scale/wonder
fact (size of the universe, deep time) is awe. This drives the video's pacing, color grade, and music — get it
right and the video FEELS like its topic instead of every video feeling the same.

Return ONLY valid JSON, no markdown, exactly:
{{
  "title": "...",
  "viewer_job": "{job_name}",
  "keyword": "the core search phrase",
  "metaphor": "3-5 word topic tag",
  "vibe": "one of: chaotic, peaceful, eerie, awe, visceral, tense",
  "hook": "first spoken line, 8-14 words",
  "hook_headline": "2-5 word ALL-CAPS scroll-stopper for the top of the screen — the curiosity gap in a few words, e.g. 'THIS ANIMAL CAN'T DIE' or 'YOU'D HAVE 15 SECONDS'. NOT the same words as the spoken hook; punchier and shorter. Max ~22 characters so it fits on screen.",
  "script": "full narration as one string",
  "scenes": [
    {{"id": 1, "duration": 4, "voiceover": "one sentence", "on_screen_text": "2-4 words", "search_query": "2-5 words", "motion": "zoom_in"}}
  ],
  "captions": ["caption with keyword + a question (drives comments)", "caption 2", "caption 3"],
  "hashtags": ["#science", "#space", "#facts"],  // 4-6 REAL one-word tags people search. No underscores, no sentences, no made-up phrases.
  "render": {{"voice": "en-US-GuyNeural", "rate": "-5%", "resolution": "1080x1920"}}
}}"""

def _call_openai_compat(url, key, model, prompt):
    """One call to any OpenAI-compatible chat endpoint (Groq, Cerebras, ...).
    Both serve Llama models with the same request/response shape, so the only
    per-provider difference is the base URL and bearer key."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"}
    }).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": "content-render/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        msg = json.loads(r.read().decode())["choices"][0]["message"]
    # some reasoning models (Cerebras gpt-oss-*) return content=null with the
    # payload under "reasoning" — fall back rather than KeyError.
    out = msg.get("content") or msg.get("reasoning") or ""
    if not out.strip():
        raise ValueError("empty content from model")
    return out


def _call_model(model, prompt):
    return _call_openai_compat("https://api.groq.com/openai/v1/chat/completions",
                               GROQ_KEY, model, prompt)


def _call_openrouter(model, prompt):
    return _call_openai_compat("https://openrouter.ai/api/v1/chat/completions",
                               OPENROUTER_KEY, model, prompt)


def _call_together(model, prompt):
    return _call_openai_compat("https://api.together.xyz/v1/chat/completions",
                               TOGETHER_KEY, model, prompt)


def _call_fireworks(model, prompt):
    return _call_openai_compat("https://api.fireworks.ai/inference/v1/chat/completions",
                               FIREWORKS_KEY, model, prompt)


def _call_mistral(model, prompt):
    return _call_openai_compat("https://api.mistral.ai/v1/chat/completions",
                               MISTRAL_KEY, model, prompt)


def _call_github_models(model, prompt):
    return _call_openai_compat(GHM_URL, GHM_KEY, model, prompt)


def _call_cerebras(model, prompt):
    """Cerebras call with a per-minute-limit self-heal. Cerebras' free tier caps
    requests-per-minute, and one render's burst of generation calls trips it
    ('Requests per minute limit exceeded', code request_quota_exceeded) — which
    otherwise falls straight through to Groq's spent daily budget and fails the
    whole attempt. When we hit the RPM cap, sleep briefly and retry the SAME
    model once so generation stays on Cerebras (often the only live provider on a
    day Gemini+Groq are exhausted). A real daily/other 429 (no 'minute'/quota
    signal) is re-raised immediately to fall through."""
    url = "https://api.cerebras.ai/v1/chat/completions"
    for attempt in range(2):
        try:
            return _call_openai_compat(url, CEREBRAS_KEY, model, prompt)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                try:
                    detail = e.read().decode("utf-8", "replace").lower()
                except Exception:  # noqa: BLE001
                    detail = ""
                if "minute" in detail or "request_quota_exceeded" in detail:
                    print(f"  [model] cerebras:{model} hit RPM cap — waiting 15s and retrying once")
                    time.sleep(15)
                    continue
            raise

def _extract_json(text):
    """Return the bare JSON object from a model reply. Gemini (without forced
    JSON mode) may wrap the JSON in ```json fences or add a line of prose; the
    callers json.loads() the result, so strip fences and, if needed, slice from
    the first '{' to the last '}'."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i != -1 and j != -1 and j > i:
            t = t[i:j + 1]
    return t


GEMINI_RPM_MAX_WAIT = 20   # seconds; a 429 asking to wait longer than this is a
                           # DAILY-quota exhaustion, not a per-minute burst —
                           # don't stall the render, fall through to the next model.


def _gemini_retry_delay(err):
    """Pull the retryDelay Gemini attaches to a 429 (e.g. '"retryDelay": "6s"').
    Returns the seconds as a float, or None if absent/unparseable. A small delay
    means we merely hit the free-tier per-minute (RPM) cap and a short sleep lets
    the very next call succeed; a large one means the daily quota is gone."""
    try:
        body = err.read().decode("utf-8", "replace")
        m = re.search(r'"retryDelay"\s*:\s*"?(\d+(?:\.\d+)?)s"?', body)
        return float(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def _call_gemini(model, prompt, ground=False):
    """Google Gemini generateContent. Same contract as _call_model: returns the
    model's text (a JSON string). Raises HTTPError on failure so the provider
    chain can fall through. NOTE: no responseMimeType — an earlier version set
    responseMimeType='application/json' and Gemini returned HTTP 400 on every
    call; a plain generateContent works on every model, and _extract_json handles
    any markdown fences the reply might carry.

    ground=True attaches the google_search tool so the model answers from REAL,
    current web results instead of only its training memory — used for the
    research dossier so scripts are built on sourced, accurate specifics. The
    text part is still parsed as JSON (grounding metadata rides separately in the
    response and is ignored here). Caller falls back to an ungrounded call on any
    failure, so grounding can never brick generation.

    RPM SELF-HEAL: one render fires ~25-40 LLM calls in a burst, which trips the
    free tier's per-minute cap (~15 RPM) even with a full daily quota. On a 429
    whose retryDelay is short, sleep it out and retry the SAME model ONCE — that
    turns a fall-through-to-Groq into a Gemini success and keeps generation on the
    high-quota provider. A long retryDelay (daily quota gone) is re-raised so the
    chain falls through immediately instead of stalling."""
    # Gemini 2.5+/3.x are "thinking" models and BILL their reasoning tokens.
    # thinkingBudget=0 (no reasoning) tanked quality (run 104 = 3.5/10); leaving
    # thinking UNBOUNDED (the old 24k output, no budget) let a single generation
    # burn ~15-20k reasoning tokens and run ~7 min — ~$1/render on the paid key.
    # A BOUNDED budget is the fix: 4096 reasoning tokens is plenty to plan a
    # ~90-word script, caps the billed cost hard, and keeps the quality that a
    # little reasoning buys. maxOutputTokens (8k) sits well above the JSON so the
    # 'Unterminated string' truncation never returns. Override per-need with
    # GEMINI_THINKING_BUDGET / GEMINI_MAX_OUTPUT_TOKENS.
    _think = int(os.getenv("GEMINI_THINKING_BUDGET", "4096"))
    _maxout = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8192"))
    _payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": _maxout,
                             "thinkingConfig": {"thinkingBudget": _think}},
    }
    if ground:
        _payload["tools"] = [{"google_search": {}}]
    body = json.dumps(_payload).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": GEMINI_KEY,
                 "User-Agent": "content-render/1.0"})
    for _attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            return _extract_json(data["candidates"][0]["content"]["parts"][0]["text"])
        except urllib.error.HTTPError as e:
            if e.code == 429 and _attempt == 0:
                delay = _gemini_retry_delay(e)
                if delay is not None and 0 < delay <= GEMINI_RPM_MAX_WAIT:
                    print(f"  [model] gemini:{model} hit RPM cap — waiting {delay:.0f}s and retrying once")
                    time.sleep(delay + 0.5)
                    continue
            raise


_CONSEC_EXHAUSTIONS = 0   # times the WHOLE provider chain 429'd back-to-back
_CIRCUIT_OPEN = False     # once open, calls fail fast instead of hammering dead quota


def _is_weak_model(prov, model):
    """The last-resort backstops whose drafts routinely trip the quality floor:
    Groq's 8B-instant and Cerebras' gemma. Everything else (Gemini, OpenRouter,
    Groq-70b, GitHub, Together/Fireworks/Mistral) is a 'primary' writer we would
    rather WAIT a per-minute throttle out for than fall past to a weak draft that
    the quality gate then aborts on."""
    m = (model or "").lower()
    if prov == "cerebras":
        return True
    if prov == "groq" and ("8b" in m or "instant" in m):
        return True
    return False


def _parse_retry_secs(detail):
    """Seconds a 429 body asks us to wait, or None. Handles Groq 'try again in
    11.83s', GitHub 'wait 55 seconds', Gemini '"retryDelay": "6s"', and
    '...in 2 minutes'. None => not a parseable per-minute limit (treat as a hard
    failure, do not wait-and-retry)."""
    if not detail:
        return None
    for pat, mult in ((r'try again in ([\d.]+)\s*s(?:ec|\b)', 1.0),
                      (r'wait ([\d.]+)\s*second', 1.0),
                      (r'retryDelay"?\s*:\s*"?([\d.]+)s', 1.0),
                      (r'try again in ([\d.]+)\s*minute', 60.0),
                      (r'in ([\d.]+)\s*minute', 60.0)):
        mo = re.search(pat, detail, re.I)
        if mo:
            try:
                return float(mo.group(1)) * mult
            except ValueError:
                return None
    return None


def call_groq(prompt):
    """Call the LLM for a JSON response. Prefers Gemini (much higher free quota)
    when GEMINI_API_KEY is set, then falls back to Groq automatically. Name kept
    as call_groq so every existing call site is unchanged.

    CIRCUIT BREAKER: if every provider rate-limits 3 calls in a row, the circuit
    opens and further calls fail instantly for the rest of this run. Without it,
    an exhausted-quota render burned ~4 minutes retrying doomed calls (5 attempts
    x escalating sleeps x every pipeline stage) AND wasted whatever little quota
    remained. Fail-fast = the render aborts in seconds and stops hammering the
    limit. When the LLM is healthy the circuit never opens (behaviour identical)."""
    global _WORKING_MODEL, _CONSEC_EXHAUSTIONS, _CIRCUIT_OPEN, _FORCE_GEMINI_GEN
    if _CIRCUIT_OPEN:
        raise RuntimeError("LLM circuit open — provider(s) rate-limited this run; failing fast")
    # Order = quality-per-free-call: Gemini (fast, ~450 RPD) → OpenRouter
    # (llama-3.3-70b:free, strongest free model, separate daily bucket) →
    # Cerebras (gemma-4-31b, RPM-limited) → Groq (100k tokens/day, last resort).
    # Generation quality order: Gemini → OpenRouter → GROQ → Cerebras. Groq now
    # sits ABOVE Cerebras: Groq's llama-3.3-70b-versatile is a STRONG model with a
    # generous 100k-tokens/day free budget, whereas Cerebras only serves the weak
    # gemma-4-31b (which produces the escalation-4 near-misses that abort). So on a
    # day when Gemini + OpenRouter are spent, generation still gets a strong model
    # (Groq) instead of dropping to weak gemma — far fewer weak/aborted runs. The
    # footage JUDGE (main.py) prefers Groq too but its prompts are tiny, so the
    # 100k/day budget comfortably covers both.
    # COST MODEL: the render itself is free (GitHub Actions + free footage + TTS);
    # only the LLM writing the script costs money, and only because GEMINI is a
    # PAID key now. But the free providers (OpenRouter/Groq llama-3.3-70b, GitHub
    # gpt-4o-mini) write strong scripts — ESPECIALLY when handed the Gemini-grounded
    # research dossier (research_dossier still grounds on Gemini directly). So for
    # the generic text calls we go FREE-FIRST and keep paid Gemini only as a
    # last-resort quality backstop. That turns the common 4-7-renders/day case into
    # ~$0 of generation, while grounding (cached per fact) + the vision judge stay
    # the only small Gemini spend. Set GEMINI_GENERATION=1 to restore Gemini-first.
    _gemini_chain = [("gemini", m) for m in gemini_models()] if GEMINI_KEY else []
    _free_chain = (([("openrouter", m) for m in OPENROUTER_MODELS] if OPENROUTER_KEY else []) +
                   ([("github", m) for m in GHM_MODELS] if GHM_KEY else []) +
                   ([("groq", m) for m in MODEL_CHAIN] if GROQ_KEY else []) +
                   ([("together", m) for m in TOGETHER_MODELS] if TOGETHER_KEY else []) +
                   ([("fireworks", m) for m in FIREWORKS_MODELS] if FIREWORKS_KEY else []) +
                   ([("mistral", m) for m in MISTRAL_MODELS] if MISTRAL_KEY else []) +
                   [("cerebras", m) for m in cerebras_models()])
    if _FORCE_GEMINI_GEN or os.getenv("GEMINI_GENERATION", "0") == "1":
        # _FORCE_GEMINI_GEN = the one-shot quality-rescue; GEMINI_GENERATION=1 =
        # the permanent legacy override. Either one puts paid Gemini first.
        chain = _gemini_chain + _free_chain
    else:
        chain = _free_chain + _gemini_chain      # default: free-first, Gemini backstop
    # try the cached working provider first (also re-walks the chain if it now
    # fails, fixing the old bug where a cached model that started 429ing raised
    # without ever falling back to the other provider).
    if _WORKING_MODEL and _WORKING_MODEL in chain:
        chain = [_WORKING_MODEL] + [c for c in chain if c != _WORKING_MODEL]
    last_err = None
    # Split the chain into PRIMARY (strong writers) and WEAK last-resorts. The
    # failure mode that produced "no video tonight" (run 30178275833): every
    # strong writer returned a *per-minute* 429 ("try again in 12s" / "wait 55
    # seconds"), so the chain immediately dropped to Groq's weak 8B model, which
    # wrote a 6.17 draft the quality gate then aborted on — the good writer was 60
    # seconds away, not gone. Now we WAIT that per-minute throttle out and retry
    # the strong writers before ever falling to a weak backstop. Keeps the bar AND
    # ships a video. On genuine daily exhaustion (no wait hint) we fall straight
    # through to the weak backstop exactly as before, so SOMETHING renders.
    primary_chain = [(p, m) for (p, m) in chain if not _is_weak_model(p, m)]
    weak_chain    = [(p, m) for (p, m) in chain if _is_weak_model(p, m)]
    max_passes = int(os.getenv("GEN_429_RETRY_PASSES", "2"))
    max_wait   = float(os.getenv("GEN_429_MAX_WAIT", "70"))

    def _walk(sub_chain, collect_waits=False):
        """Try each (prov, model) in order. Returns (out, prov, model) on the
        first success, else (None, None, None). Appends parsed per-minute 429
        wait hints to `waits` (a list captured via closure) when collect_waits."""
        nonlocal last_err
        for prov, model in sub_chain:
            try:
                if prov == "gemini":
                    out = _call_gemini(model, prompt)
                elif prov == "openrouter":
                    out = _call_openrouter(model, prompt)
                elif prov == "github":
                    out = _call_github_models(model, prompt)
                elif prov == "together":
                    out = _call_together(model, prompt)
                elif prov == "fireworks":
                    out = _call_fireworks(model, prompt)
                elif prov == "mistral":
                    out = _call_mistral(model, prompt)
                elif prov == "cerebras":
                    out = _call_cerebras(model, prompt)
                else:
                    out = _call_model(model, prompt)
                return out, prov, model
            except urllib.error.HTTPError as e:
                if e.code in (400, 401, 402, 403, 404, 413, 429):
                    # THIS-provider-specific, so fall through to the next entry
                    # instead of aborting the whole run:
                    #   400 bad request  401 unauthorized (bad/rotated key)
                    #   402 payment required (free credit out)  403/404 unavailable
                    #   413 payload too large (GitHub Models' ~8k-token input cap —
                    #       MUST fall through to Groq/Cerebras' big context, not abort;
                    #       this was aborting whole renders when Gemini was down)
                    #   429 rate-limited. Log the server body (truncated) so a
                    #   silently-failing provider isn't mistaken for a healthy one.
                    try:
                        detail = e.read().decode("utf-8", "replace")[:300]
                    except Exception:  # noqa: BLE001
                        detail = ""
                    print(f"  [model] {prov}:{model} failed HTTP {e.code} — falling through"
                          + (f" :: {detail}" if detail else ""))
                    last_err = e
                    if collect_waits and e.code == 429:
                        w = _parse_retry_secs(detail)
                        if w is not None:
                            waits.append(w)
                    continue
                raise   # 5xx etc — let the outer retry loop handle it
            except Exception as e:  # noqa: BLE001 - network/parse hiccup, try next
                # e.g. Gemini returned 200 but the reply was truncated/safety-
                # blocked so ["candidates"][0]... KeyError'd. Log it so this
                # failure mode is visible instead of silently dropping through.
                print(f"  [model] {prov}:{model} failed ({type(e).__name__}: {str(e)[:160]}) — falling through")
                last_err = e; continue
        return None, None, None

    def _accept(out, prov, model):
        global _WORKING_MODEL, _CONSEC_EXHAUSTIONS
        if _WORKING_MODEL != (prov, model):
            print(f"  [model] using {prov}:{model}")
        _WORKING_MODEL = (prov, model)
        _CONSEC_EXHAUSTIONS = 0   # a success closes/keeps-closed the circuit
        return out

    # Phase 1: strong writers, waiting out per-minute 429s before giving up.
    for _pass in range(max_passes + 1):
        waits = []
        out, prov, model = _walk(primary_chain, collect_waits=True)
        if out is not None:
            return _accept(out, prov, model)
        # Every strong writer failed this pass. If at least one told us it was a
        # per-minute throttle (a parseable wait hint), sleep the SHORTEST such
        # wait and retry the strong writers — the good one is ~a minute away.
        if _pass < max_passes and waits:
            wait = min(min(waits) + 1.0, max_wait)
            print(f"  [model] strong writers are per-minute throttled — waiting "
                  f"{wait:.0f}s and retrying them (pass {_pass+2}/{max_passes+1}) "
                  f"rather than dropping to a weak model")
            time.sleep(wait)
            continue
        break   # daily exhaustion / hard errors — no point waiting

    # Phase 2: strong writers genuinely unavailable — fall to the weak backstops
    # so SOMETHING renders (the quality gate still guards what ships).
    out, prov, model = _walk(weak_chain)
    if out is not None:
        return _accept(out, prov, model)

    # every provider failed this call
    _CONSEC_EXHAUSTIONS += 1
    if _CONSEC_EXHAUSTIONS >= 3 and not _CIRCUIT_OPEN:
        _CIRCUIT_OPEN = True
        print("  [model] circuit OPEN — all LLM providers rate-limited 3x in a row; "
              "failing fast for the rest of this run (add GEMINI_API_KEY for a much larger free quota)")
    raise last_err if last_err else RuntimeError("no LLM provider available")

# basic safety net for HOW_TO output
UNSAFE = re.compile(r"\b(fire|flame|burn|burning|lit|light a|matches?|lighter|candle|stove|boil|boiling|"
                    r"microwave|oven|heat|hot water|electric|outlet|socket|battery acid|bleach|ammonia|"
                    r"swallow|drink|eat|ingest|knife|blade|razor|shatter|explode|explosion)\b", re.I)

# terms free stock libraries can't actually satisfy — searches for them degrade
# into random flesh/lab/texture close-ups (see the belly-button incident)
UNSTOCKABLE_Q = re.compile(r"\b(anatom\w*|organs?|cells?|microscop\w*|diagrams?|x-?ray|molecul\w*|"
                           r"atoms?|quantum|abstracts?|concept\w*|systems?|"
                           # jargon that returns nothing filmable (or a random
                           # texture the judge then rates a false match — the
                           # "rhizomorphs -> orange brick wall" miss). Say the
                           # plain subject instead: "fungus threads underground".
                           r"rhizomorph\w*|myceli\w*|hyphae?|antisolar)\b", re.I)

# render-209: the payoff scene was a human-ancestry line, but its search_query
# was "night sky stars" -- generic cosmic imagery the writer defaults to when
# it can't think of anything concrete, landing a totally off-topic clip. Only
# fires when BOTH hold: the query is cosmic/space filler AND this specific
# scene's own voiceover never mentions anything space-related either (so it's
# clearly not an intentional space metaphor/comparison) AND the fact's domain
# isn't actually space/astronomy (where cosmic imagery is exactly right).
COSMIC_FILLER_Q_RE = re.compile(r"\b(night sky|starry|star field|starfield|milky way|deep space|"
                                r"outer space|nebula|galaxy|galaxies|constellation|solar system|"
                                r"cosmos|cosmic|planets? orbit\w*)\b", re.I)
SPACE_CONTEXT_RE = re.compile(r"\b(stars?|sky|galaxy|galaxies|nebula|cosmic|cosmos|universe|orbit\w*|"
                              r"planets?|moon|sun|space|asteroids?|comets?|constellation|milky way|"
                              r"black hole)\b", re.I)
SPACE_DOMAINS = {"space", "astronomy"}

# visually-rich neutral B-roll for query dedup / repair — always available on stock sites
VARIETY_QUERIES = ["ocean waves aerial", "night sky timelapse", "city street timelapse",
                   "lightning storm clouds", "forest sunlight drone", "hourglass sand falling",
                   "hands typing closeup", "waterfall slow motion", "desert dunes aerial",
                   "northern lights sky", "rain window closeup", "eagle flying mountains"]


def punch_up(m, fact, cta_style="SAVE_WORTHY"):
    """Second-pass rewrite of the voiceovers only. Structure rules in the main
    prompt get a script that follows the letter of the format but still writes
    flat lines (e.g. following the midpoint twist with 'the difference is
    almost negligible' — an anti-climax — or stacking two different endings).
    A focused critique-and-rewrite pass fixes delivery; validate() re-guards
    the result and we keep the original whenever the rewrite doesn't survive
    it. cta_style pins the final-line rule to the ending style chosen for
    this video (see CTA_PUNCHUP_RULES) instead of a fixed save-command."""
    fact_line = fact["fact"] if fact else "the fact stated in the script"
    key_terms = fact.get("key_terms", []) if fact else []
    key_terms_rule = ""
    if key_terms:
        key_terms_rule = (
            f"- MUST preserve every one of these exact terms verbatim, spelled exactly as given, "
            f"somewhere across the rewritten lines: {key_terms}. Do not paraphrase them away or "
            f"swap a real name/number for a vaguer description — if the original said "
            f"'potassium-40', the rewrite must still say 'potassium-40', not 'a radioactive isotope'.\n")
    ending_rule = CTA_PUNCHUP_RULES.get(cta_style, CTA_PUNCHUP_RULES["SAVE_WORTHY"])
    scenes_json = json.dumps([{"id": s["id"], "voiceover": s["voiceover"]} for s in m["scenes"]])
    prompt = f"""You are a short-form script doctor. Rewrite ONLY the voiceover lines below for maximum retention.

THE VERIFIED FACT (do not alter it, do not add new numbers): "{fact_line}"

RULES:
- Same number of scenes, same ids, same order, same underlying meaning per scene.
- Each line stays ONE punchy spoken sentence, 6-18 words, natural to read aloud.
- ESCALATE: every line must feel like a step deeper than the last. No line may deflate
  ("it's tiny", "almost negligible", "basically nothing") right after a tension-raiser.
  If a smallness caveat is needed, fuse it INTO an impressive frame ("so small only an
  atomic clock can see it — but it never stops").
- The line right after any "that's not the strange part"-style interrupt must deliver the
  single most surprising concrete detail of the whole script.
- {ending_rule}
- Only the FINAL line may carry any ending/CTA language at all — every other line stays pure
  content, no stray "save"/"share"/"comment" language anywhere else.
- Keep any real numbers exactly as they are. Add NO new facts or numbers.
{key_terms_rule}- Every line ends with proper punctuation (. ? or !) — these are spoken sentences,
  and the TTS engine uses end punctuation to pace pauses between scenes.

Scenes: {scenes_json}

Return ONLY valid JSON, exactly: {{"scenes": [{{"id": 1, "voiceover": "..."}}]}}"""
    try:
        raw = call_groq(prompt)
        new_scenes = {}
        for s in json.loads(raw)["scenes"]:
            if not s.get("voiceover"):
                continue
            line = _clean(s["voiceover"])
            if line and line[-1] not in ".?!":  # model drops terminal punctuation
                line += "."                     # under real-world load; don't rely on the prompt alone
            new_scenes[s["id"]] = line
    except Exception as e:  # noqa: BLE001 - punch-up is best-effort
        print(f"  punch-up failed ({e}), keeping original")
        return m
    trial = _apply_scene_rewrite(m, fact, new_scenes, "punch-up")
    if trial is None:
        return m
    print("  punch-up applied")
    return trial

def _clean(t):
    # strip code fences / markdown / stray quotes the model sometimes adds
    t = str(t).strip().strip("`").strip()
    return re.sub(r"\s+", " ", t)

def _key_term_present(term, text):
    """Is a dossier key_term actually named in text? Case-insensitive substring
    match for proper nouns/phrases ("potassium-40", "Mariana Trench"). For terms
    that lead with a number ("0.1 microsieverts", "5,000 times a second") also
    match on the bare digit sequence, comma-insensitive, so rounding/formatting
    differences ("5000" vs "5,000" vs "roughly 5000") don't cause a false
    negative — the actual proper-noun substring match stays the primary path so
    a stray shared number elsewhere in the script can't cause a false positive."""
    term = term.strip()
    if not term:
        return False
    if term.lower() in text.lower():
        return True
    if term[0].isdigit():
        digits = re.findall(r"\d[\d,\.]*", term)
        norm_text = text.replace(",", "")
        for d in digits:
            d_norm = d.rstrip(".").replace(",", "")
            if d_norm and d_norm in norm_text:
                return True
    return False

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
    "thousand": 1000, "million": 1000000, "billion": 1000000000,
}


def _salient_number_phrases(text):
    """Find 'number + unit' phrases (e.g. 'eight minutes', '8 minutes',
    'eight-minute delay') and normalize them so a word-number and a digit,
    or a hyphenated adjective form and a plain phrase, all collapse to the
    SAME token ('8 minute'). This is what catches "the same reveal re-said
    in different words" — the Sun video said "eight minutes ago", "an
    eight-minute delay", and "eight minutes and twenty seconds" across four
    different scenes; three different sentences, the same core number every
    time. Restricted to number+unit pairs (not bare digits) so two scenes
    that legitimately cite two DIFFERENT numbers (100 miles vs. 15 seconds)
    never collide."""
    def numval(tok):
        if tok.isdigit():
            return int(tok)
        return _NUM_WORDS.get(tok)

    tokens = re.findall(r"[a-z]+(?:-[a-z]+)*|\d[\d,\.]*", text.lower())
    phrases = set()
    for i, tok in enumerate(tokens):
        if "-" in tok:
            parts = tok.split("-")
            v = numval(parts[0])
            if v is not None and len(parts) > 1 and parts[1].isalpha() and len(parts[1]) > 2:
                phrases.add(f"{v} {parts[1].rstrip('s')}")
            continue
        v = numval(tok)
        if v is not None and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            if nxt.isalpha() and len(nxt) > 2 and "-" not in nxt:
                phrases.add(f"{v} {nxt.rstrip('s')}")
    return phrases


def _salient_proper_nouns(text):
    """Multi-word capitalized phrases only ("Mariana Trench", "Turritopsis
    Dohrnii") — deliberately excludes single capitalized words so a video's
    own recurring subject noun ("Sun", "Earth") legitimately appearing in
    most scenes never trips this check; only a specific multi-word proper
    noun repeated as the crux of several scenes counts."""
    return {m.group(0).lower()
            for m in re.finditer(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+\b", text)}


def check_information_gain(m):
    """One extra Groq call, run only after structural validate() has already
    passed: hand the model the numbered voiceover list and ask which scenes (if
    any) add NO new information beyond an earlier scene. This catches semantic
    redundancy — the same idea said in different words — that the structural
    pairwise-similarity and fact-restatement checks in validate() can miss
    because they only compare surface phrasing.

    MUST fail-open: this is a nice-to-have quality gate, not a correctness gate,
    and it must never be able to brick generation. Any network error, timeout,
    malformed JSON, or unexpected shape from the model is treated as a pass.
    """
    try:
        scenes = m.get("scenes", [])
        if len(scenes) < 2:
            return None
        numbered = "\n".join(f"{s['id']}. {s['voiceover']}" for s in scenes)
        prompt = (
            "Here is the numbered voiceover script of a short video, in scene order:\n\n"
            f"{numbered}\n\n"
            "A scene 'adds no new information' only if everything it says was already "
            "conveyed — even in different words — by an EARLIER scene in this list. Scene "
            "1 never counts (there is no earlier scene). A scene that reveals a new number, "
            "a new mechanism, a new consequence, or a new comparison is NOT redundant even "
            "if it's on the same topic.\n\n"
            'Return ONLY valid JSON, exactly: {"no_new_info_scene_ids": [2, 5]} '
            "-- an empty array if every scene adds something new. No explanation, JSON only."
        )
        raw = call_groq(prompt)
        data = json.loads(raw)
        ids = data.get("no_new_info_scene_ids", [])
        if not isinstance(ids, list):
            return None
        # Robust coercion: accept ints and numeric strings ("2") alike so a
        # model that answers under JSON mode but still writes id numbers as
        # strings doesn't silently make this whole check inert (the exact
        # class of bug fixed in score_script's _coerce_score — see the
        # comment there). Bools are rejected explicitly since JSON true/false
        # would otherwise smuggle in as 1/0 under a bare isinstance(int) check.
        clean_ids = []
        for i in ids:
            if isinstance(i, bool):
                continue
            if isinstance(i, int):
                clean_ids.append(i)
            elif isinstance(i, str) and i.strip().lstrip("-").isdigit():
                clean_ids.append(int(i.strip()))
        ids = clean_ids
        # HARDER GATE: was ">= 2" (two or more redundant scenes needed to
        # reject). One redundant scene is already a scene that earns its
        # runtime for free — reject on the first one flagged, same as any
        # other structural validation failure.
        if len(ids) >= 1:
            print(f"  [info-gain] flagged {len(ids)} redundant scene(s) {ids} "
                  f"— no new information beyond an earlier scene")
            return (f"information-gain check flagged {len(ids)} redundant scene(s) {ids} "
                    f"(no new information beyond an earlier scene) — cut or replace them")
        return None
    except Exception as e:  # noqa: BLE001 - must fail open, never blocks a run
        print(f"  info-gain check failed open ({e}), passing")
        return None

def validate(m, job_name, fact=None):
    for k in ["title", "hook", "script", "scenes", "captions", "hashtags"]:
        if k not in m:
            return f"missing {k}"
    # Scene-count ceiling tightened 14 -> 11 -> 10 (target is 8-10, see
    # build_prompt): the Sun video ran 12 scenes at 166 words and read as
    # "does not stop talking" -- fewer, better-paced scenes beat cramming in
    # more reveals, and a tight ~30-40s video wins on completion.
    # Floor raised 6 -> 7 to match the prompt's "7-9 scenes" and, crucially, to
    # kill the single-clip LINGER problem: a 6-scene ~40s video runs ~6.7s per
    # scene, and each scene loops ONE clip, so a 7.9s scene sat on one Roman-ruins
    # aerial for 8s (run 105). 7-9 scenes = ~4.5-5.5s each = more distinct clips,
    # less lingering, more visual variety — "use more videos" for free. Ceiling
    # stays 10 (a 12-scene/166-word Sun video read as "never stops talking").
    if not isinstance(m["scenes"], list) or not (SCENE_MIN <= len(m["scenes"]) <= SCENE_MAX):
        return f"scene count {len(m.get('scenes', []))} out of range ({SCENE_MIN}-{SCENE_MAX}, mode {LENGTH_MODE})"

    # clean top-level text
    m["title"] = _clean(m["title"])[:90]
    m["hook"] = _clean(m["hook"])
    if not (4 <= len(m["hook"].split()) <= 16):
        return f"hook length {len(m['hook'].split())} words out of range"
    # Concrete-hook guard: catches the exact abstraction failure the Sun video
    # shipped with ("You're seeing the Sun as it was, not as it is" -- reads
    # as confusing, not intriguing, as a viewer's very first line because it
    # only makes sense once you already know the twist). Narrow phrase match
    # by design -- it targets this specific "as it was/is, not as it is/was"
    # perception-vs-reality construction, not hooks in general, so it can't
    # false-positive on a normal concrete hook.
    if ABSTRACT_HOOK_RE.search(m["hook"]):
        return (f"hook '{m['hook']}' is too abstract/vague — a viewer can't picture anything "
                f"concrete from it alone; open with a self-contained, concrete image or claim "
                f"instead (see the good/bad hook examples in the prompt)")
    dc = DANGLING_COMPARATIVE_RE.search(m["hook"])
    if dc:
        return (f"hook '{m['hook']}' has a DANGLING comparative ({dc.group(0)!r}) with no "
                f"'than ___' completion — meaningless as an opener (the render-173 bug: "
                f"'T. rex is closer to you' — closer than WHAT?); either finish the comparison "
                f"in the same line or rewrite without one")

    # scenes: clean and validate
    for i, s in enumerate(m["scenes"], 1):
        for k in ("voiceover", "on_screen_text", "search_query"):
            if not s.get(k):
                return f"scene {i} missing {k}"
            s[k] = _clean(s[k])
        s["on_screen_text"] = " ".join(s["on_screen_text"].split()[:4])  # cap label to 4 words
        # Hard per-scene cap tightened 28 -> 22, then loosened to 25 words
        # (SCENE_WORD_CAP, shared with the writer prompt and the near-miss
        # per-scene trim below). The Sun video's scene 11 ran 34 words -- a
        # run-on jammed between 6-9 word scenes is exactly the "choppy /
        # doesn't stop talking" complaint: one scene breathless while its
        # neighbors are punchy reads as uneven, not varied. Prompt targets
        # 6-16 words/scene; 25 is the hard ceiling (still far under 34).
        if len(s["voiceover"].split()) > SCENE_WORD_CAP:
            return (f"scene {i} voiceover too long ({len(s['voiceover'].split())} words, "
                     f"cap is {SCENE_WORD_CAP})")
        # TOO-FORMAL / "sounds like a textbook" — user feedback on 'Continents in
        # Motion': "But is the distance between New York and London fixed?" then a
        # flat "No." Every word was plain, but the SENTENCE SHAPE was stiff, not
        # how a person talks. Three mechanical checks (see the regexes' own
        # docstring-comments above for the exact bad lines they were built from).
        fi = FORMAL_INVERSION_RE.search(s["voiceover"])
        if fi:
            return (f"scene {i} voiceover '{s['voiceover']}' is a stiff, textbook-style inverted "
                     f"question ({fi.group(0)!r}) — nobody talks like this out loud; rewrite as a "
                     f"short plain statement or a short direct question (see the TALK-DONT-WRITE rule)")
        if LONE_YES_NO_RE.match(s["voiceover"].strip()):
            return (f"scene {i} voiceover is a lone {s['voiceover'].strip()!r} — reads as a scripted "
                     f"dramatic beat, not natural speech; fold the answer into the next sentence")
        fc = FORMAL_CONNECTOR_RE.search(s["voiceover"])
        if fc:
            return (f"scene {i} voiceover uses the formal connector {fc.group(0)!r} — nobody talks "
                     f"like this out loud; rewrite in plain conversational language")
        jt = JARGON_TERM_RE.search(s["voiceover"])
        if jt:
            return (f"scene {i} voiceover names unexplained jargon {jt.group(0)!r} — a smart "
                     f"15-year-old wouldn't know this word; either explain it in plain words in the "
                     f"same breath or replace it entirely (see the PLAIN SPOKEN ENGLISH rule)")
        # stock libraries return junk (flesh closeups, random labs) for these:
        # the belly-button-as-stomach incident came from 'human stomach anatomy'
        if UNSTOCKABLE_Q.search(s["search_query"]):
            return f"scene {i} query '{s['search_query']}' uses un-filmable terms"
        if (fact and fact.get("domain") not in SPACE_DOMAINS
                and COSMIC_FILLER_Q_RE.search(s["search_query"])
                and not SPACE_CONTEXT_RE.search(s["voiceover"])):
            return (f"scene {i} query '{s['search_query']}' is generic cosmic/space imagery, but "
                    f"this fact's domain is {fact.get('domain')!r} and the scene's own voiceover "
                    f"never mentions anything space-related — pick a search_query that actually "
                    f"shows this scene's real subject instead of defaulting to space filler "
                    f"(render-209 bug: 'night sky stars' on a human-ancestry payoff line)")
        # NOTE: a duplicate search_query used to get force-swapped to an
        # unrelated VARIETY_QUERIES term here. That's how a scene whose
        # voiceover was "humanity fits in a sugar cube" ended up querying
        # "ocean waves aerial" -- pure noise, zero relevance, and the judge
        # in main.py could only rate what it was given. It also solved a
        # problem main.py already handles: fetch_clip's candidate sources
        # exclude every previously-used clip id (_used_video_ids), so two
        # scenes sharing a query get different clips automatically. No
        # swap needed -- leave the query tied to its own scene's content.
        # numeric, sane duration
        try:
            s["duration"] = max(2, min(8, int(float(s.get("duration", 4)))))
        except Exception:
            s["duration"] = 4
        if s.get("motion") not in ("zoom_in", "zoom_out", "pan", "static"):
            s["motion"] = random.choice(["zoom_in", "zoom_out", "pan", "static"])

    # script length sanity. FLOOR raised 60 -> 80: the ElevenLabs voice speaks
    # noticeably faster than the old edge-tts pacing the 60-word floor was tuned
    # for. But the previous 80-100 window was ALSO wrong — too TIGHT: the free
    # models naturally write ~110-140-word science scripts, so nearly every draft
    # blew the 100 cap, got scene-trimmed to fit, and lost an escalation rung each
    # time it dropped a scene → escalation floor violations → aborted runs (branch
    # render 2026-07-22: 139/141/148-word drafts, all trimmed, escalation 4-5).
    # 85-115 matches what the models actually produce, so a clean draft passes with
    # ALL its scenes (escalation) intact, AND Gemini's ~105-word rescue drafts pass
    # instead of being trimmed to mush. 95-110 renders ~40-46s on the neural voices
    # (edge-tts/Piper), the completion sweet spot; 115 is the hard ceiling.
    wc = len(_clean(m["script"]).split())
    if not (WORD_HARD_LO <= wc <= WORD_HARD_HI):
        return (f"script word count {wc} out of range "
                f"(target {WORD_LO}-{WORD_HI}, hard {WORD_HARD_LO}-{WORD_HARD_HI}, mode {LENGTH_MODE})")
    m["script"] = _clean(m["script"])

    # CTA overhaul guard 1: the exact production failure this whole rework
    # targets was every video ending on the same hard-coded command ("Save
    # this so you remember it."). Reject any script that still contains that
    # command or a close paraphrase of it, regardless of which CTA style was
    # assigned — a command is not a substitute for save-worthy content and is
    # banned outright now, not just discouraged.
    full_blob = m["script"] + " " + " ".join(s["voiceover"] for s in m["scenes"])
    if GENERIC_SAVE_CMD.search(full_blob):
        return ("script contains the banned generic save-command phrasing "
                "('save this so you...') — the ending must earn a save through "
                "content, not a command; see this video's assigned CTA style")

    # CTA overhaul guard 2: save-worthiness must be engineered into the
    # CONTENT, not just claimed by the ending. Require at least one concrete,
    # specific, reference-worthy detail somewhere in the script (a real
    # number, or a stated comparison/rule-of-thumb) — the kind of thing a
    # viewer could actually repeat or look up again. Bank-fact videos already
    # clear this via mandatory key_terms; this catches jobs/scripts with no
    # bank fact behind them (e.g. HOW_TO, or a MYTH_BUSTER with no fact_id).
    if not REFERENCE_WORTHY_RE.search(full_blob):
        return ("no reference-worthy / 'screenshot-this' detail found anywhere in the "
                "script — include a specific number, rule of thumb, or vivid comparison "
                "a viewer would actually want to remember or reuse")

    # Path B: numeric-contradiction guard — catch fabricated/contradictory numbers (e.g. "7 colors" then "16.5 colors")
    full = (m["script"] + " " + " ".join(c for c in m.get("captions", []))).lower()
    # map each "number + following noun". A scale/planet qualifier immediately
    # after the number ("243 EARTH days", "4.6 BILLION years") is skipped so the
    # pair keys on the REAL head noun ("days"/"years"), not the qualifier — else
    # "243 Earth days" and "225 Earth days" (two legitimate, different Venus
    # periods) would collide on the word "earth" and be wrongly flagged.
    _NUM_QUALIFIERS = r"(?:earth|light|solar|lunar|billion|million|thousand|hundred|trillion)"
    pairs = re.findall(rf"(\d[\d,\.]*)\s+(?:{_NUM_QUALIFIERS}\s+)?([a-z]{{3,}})", full)
    # This guard targets contradictory COUNTS of a discrete named thing ("7
    # colors" vs "16 colors"). Two different MEASUREMENTS that share a unit
    # ("243 days" for a spin, "225 days" for an orbit; "5000 km" vs "9000 km"
    # for two different depths) are normal, not contradictions — so units of
    # measure are excluded. Without this, ordinary astronomy/geology scripts
    # (which routinely quote several distances/durations in the same unit) got
    # aborted before ever rendering. Discrete-count contradictions still fire.
    _MEASURE_UNITS = {
        "times", "ways", "kinds", "types", "of", "the", "and",
        "days", "day", "years", "year", "hours", "hour", "minutes", "minute",
        "seconds", "second", "weeks", "week", "months", "month", "decades",
        "centuries", "millennia",
        "kilometres", "kilometers", "kilometre", "kilometer", "metres",
        "meters", "metre", "meter", "miles", "mile", "feet", "foot", "inches",
        "inch", "centimetres", "centimeters", "millimetres", "millimeters",
        "degrees", "degree", "celsius", "fahrenheit", "kelvin",
        "kilograms", "kilogram", "grams", "gram", "pounds", "pound", "tonnes",
        "tons", "ton", "litres", "liters", "millilitres", "gallons",
        "percent", "kilometres-per-hour", "watts", "volts", "joules",
    }
    by_noun = {}
    for num, noun in pairs:
        n = num.rstrip(".").replace(",", "")
        by_noun.setdefault(noun, set()).add(n)
    for noun, nums in by_noun.items():
        if len(nums) > 1 and noun not in _MEASURE_UNITS:
            return f"contradictory numbers for '{noun}': {sorted(nums)}"
    # reject absurd fractional counts of discrete things (16.5 colors, 3.5 hearts)
    for num, noun in pairs:
        if "." in num and noun in ("colors", "colours", "hearts", "planets", "stars", "people",
                                   "cells", "bones", "legs", "eyes", "moons", "times", "animals"):
            return f"impossible fractional count: {num} {noun}"

    # anti-repetition: reject if scene voiceovers are too similar to each other.
    # Lowered 0.70 -> 0.62 after the Sun video: scenes 8 and 11 ("...you are
    # always seeing the Sun as it was eight minutes ago, never as it is right
    # now" vs. "...you are seeing it as it was eight minutes and twenty
    # seconds in the past, never as it is right now") scored under 0.70 on
    # pure sequence similarity despite being obviously the same line restated.
    # 0.62 still leaves room for legitimate parallel sentence structure (short
    # scenes built the same way but about different facts) — tested against
    # both the bad Sun manifest (must reject) and a known-good non-repetitive
    # manifest (must pass) below.
    #
    # Exception: scene 1 vs. the final scene. The LOOP CTA style (and, before
    # the CTA-style split, the general "loop back to the hook" ending rule)
    # deliberately wants the closing line to echo the hook's exact phrasing so
    # a replay feels seamless — that is the mechanic, not accidental
    # repetition. The anti-restatement check below already carves out this
    # same exception for the verified-fact comparison; mirror it here so a
    # well-executed loop ending can't get rejected for doing exactly what it
    # was asked to do.
    import difflib
    vos = [s["voiceover"].lower() for s in m["scenes"]]
    for i in range(len(vos)):
        for j in range(i + 1, len(vos)):
            if i == 0 and j == len(vos) - 1:
                continue
            ratio = difflib.SequenceMatcher(None, vos[i], vos[j]).ratio()
            if ratio > 0.62:
                return f"scenes {i+1} and {j+1} too similar (repetition)"

    # anti-repetition (salient-token variant): catches "re-says the same
    # thing" even when each restatement uses a DIFFERENT sentence structure,
    # which the pairwise phrasing check above can miss. The Sun video's core
    # reveal ("eight minutes") showed up as the crux of scene 7 ("left the Sun
    # about eight minutes ago"), scene 8 ("...eight minutes ago, never as it
    # is right now"), scene 9 ("an eight-minute delay"), and scene 11
    # ("...eight minutes and twenty seconds...") — four different sentences,
    # one number, said over and over. If the same salient number-phrase (a
    # normalized "8 minute" style token) or the same multi-word proper noun
    # is the crux of 3+ scenes, that is the reveal being re-said instead of
    # the script escalating to something new each time.
    #
    # Excludes the final scene, same rationale as the pairwise exception
    # above: a LOOP-style ending is SUPPOSED to echo the hook/central image.
    token_scenes = collections.defaultdict(list)
    for i, vo in enumerate(vos[:-1] if len(vos) > 1 else vos):
        for tok in _salient_number_phrases(vo) | _salient_proper_nouns(vo):
            token_scenes[tok].append(i + 1)
    repeated_core = {tok: ids for tok, ids in token_scenes.items() if len(ids) >= 3}
    if repeated_core:
        return (f"the same core detail is re-said as the crux of 3+ scenes {repeated_core} — "
                f"state it once as the payoff and make every other scene a genuinely different "
                f"fact or angle, not a reworded repeat")

    # mandatory key-term naming: the real production failure that motivated this
    # (the potassium-40 banana video) was that topic_bank facts used to be bare
    # one-liners, so the model never had a specific isotope name or a real dose
    # figure to reach for and just said "a naturally occurring isotope" instead.
    # Dossiers now carry key_terms (proper nouns / real numbers the script MUST
    # say) plus a whatif hypothetical the script must pose early and pay off.
    key_terms = fact.get("key_terms", []) if fact else []
    if key_terms:
        full_text = m["script"] + " " + " ".join(s["voiceover"] for s in m["scenes"])
        named = [kt for kt in key_terms if _key_term_present(kt, full_text)]
        if len(named) < 2:
            return (f"only {len(named)}/{len(key_terms)} mandatory key terms named "
                     f"({named or 'none'}) — the script must explicitly say at least 2 of "
                     f"{key_terms}; a script that says 'a naturally occurring isotope' instead "
                     f"of 'potassium-40' is a failed script")
        whatif = fact.get("whatif", "")
        if whatif:
            q_part, sep, a_part = whatif.partition("?")
            answer_text = a_part if sep else whatif
            early_count = min(4, len(m["scenes"]))
            early_text = m["hook"] + " " + " ".join(s["voiceover"] for s in m["scenes"][:early_count])
            if "?" not in early_text:
                return ("whatif curiosity gap never opened — the hook or one of the first few "
                        "scenes must pose a real question, not just state facts")
            payoff_terms = [kt for kt in key_terms if _key_term_present(kt, answer_text)] or key_terms
            if not any(_key_term_present(kt, full_text) for kt in payoff_terms):
                return (f"whatif payoff never answered — the script must state the real answer "
                        f"using one of {payoff_terms}, not just pose the question and move on")

    # anti-restatement: the pairwise check above only catches near-identical
    # PHRASING between two scenes. It missed a real production failure: scene
    # 1 said "your body is nearly all empty space", scene 3 said "humanity
    # fits in a sugar cube", and scene 6 then restated BOTH combined almost
    # verbatim as one line -- the same reveal delivered three times with
    # different words, which is exactly what the escalation-ladder rule is
    # supposed to prevent. Catch it by checking how many scenes closely
    # mirror the verified fact itself: one scene doing so is the expected
    # payoff moment; two or more means the core reveal got restated instead
    # of the script escalating to something new each time.
    if fact and fact.get("fact") and len(vos) > 1:
        fact_text = fact["fact"].lower()
        # exclude the final scene: the prompt explicitly wants the closing line
        # to loop back to the hook/central image, which legitimately re-touches
        # the fact's vocabulary -- that's a deliberate design choice, not a bug.
        restated = [i + 1 for i, vo in enumerate(vos[:-1])
                    if difflib.SequenceMatcher(None, vo, fact_text).ratio() > 0.40]
        if len(restated) > 1:
            return (f"the verified fact is restated in {len(restated)} scenes {restated} "
                    f"instead of being revealed once and escalated from")
    # reject if the title's key noun appears in nearly every scene (circling one idea)
    # (collections is imported at module level above)
    words = collections.Counter(re.sub(r"[^a-z ]", "", " ".join(vos)).split())
    common = [w for w, c in words.items() if len(w) > 4 and c >= max(4, len(vos) - 1)]
    if common:
        return f"word(s) {common} repeated in nearly every scene (not progressing)"

    # captions / hashtags hygiene
    m["captions"] = [_clean(c) for c in m["captions"] if _clean(c)][:3] or [m["title"]]
    tags = []
    for h in m["hashtags"]:
        h = _clean(h).lstrip("#")
        # reject phrase/sentence tags: drop anything with underscores or that's too long
        if "_" in h or len(h) > 20 or " " in h.strip():
            # try to salvage the first word only
            h = re.sub(r"[_\s].*$", "", h)
        h = re.sub(r"[^A-Za-z0-9]", "", h)  # letters/numbers only
        if not h or len(h) < 2:
            continue
        tag = "#" + h.lower()
        if tag not in tags:
            tags.append(tag)
    # guarantee core tags
    for core in ["#science", "#learnontiktok"]:
        if core not in tags:
            tags.append(core)
    m["hashtags"] = tags[:6]

    if job_name == "HOW_TO":
        blob = m["script"] + " " + " ".join(s["voiceover"] for s in m["scenes"])
        if UNSAFE.search(blob):
            return "HOW_TO tripped safety filter"

    m.setdefault("render", {"voice": "en-US-GuyNeural", "rate": "-5%", "resolution": "1080x1920"})
    return None

def _coerce_score(v):
    """Pull a 0-10 number out of whatever the model returned for a rubric
    criterion — int, float, "8", "8/10", "8.5 - strong". Returns None only
    when there's genuinely no number to read (or a bool, which JSON true/false
    would otherwise smuggle in as 1/0)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return max(0.0, min(10.0, float(v)))
    if isinstance(v, str):
        mm = re.search(r"-?\d+(?:\.\d+)?", v)
        if mm:
            return max(0.0, min(10.0, float(mm.group())))
    return None


# The exact rubric definition for each scored criterion, shared between
# score_script's prompt (which scores ALL of them) and revise_for_floors
# below (which quotes back ONLY the criteria that actually failed) -- ONE
# source of truth so a judge and a targeted-repair pass can never describe
# the same rubric two different ways. 'rewatch' is deliberately excluded:
# its wording depends on cta_style (see CTA_RUBRIC_HINTS) and it carries no
# floor, so it never drives a targeted repair.
RUBRIC_CRITERION_TEXT = {
    "hook": ("does the first line open a REAL curiosity gap (a specific question the "
             "viewer NEEDS answered), not just a description or a mild tease?"),
    "surprise": ("would most adults genuinely react \"wait, WHAT?\" and be left "
                 "THINKING/seeing something differently — not just hearing facts and numbers "
                 "scroll by? A script that mostly recites measurements (how tall/old/fast/many) "
                 "with no mind-bending IDEA behind them scores 3 or below. CRUCIAL: a pure scale "
                 "or counting fact — how many ways to shuffle a deck, how many atoms/combinations "
                 "exist, how many times bigger X is than Y — is NOT surprise. \"That number is "
                 "unimaginably big/small\" makes a smart viewer shrug. Unless the scale exposes a "
                 "hidden mechanism or a consequence a real person would feel, score magnitude-only "
                 "scripts 3 or below."),
    "escalation": ("does EVERY scene reveal something new, with zero scenes just restating an "
                   "earlier scene in different words?"),
    "payoff": ("does the central question resolve into a genuine mind-bending IDEA — a "
               "realization that reframes how the viewer sees the thing — rather than a recited "
               "number or a shrug? A number as the payoff (a dry \"it's 8,849 metres\") is WEAK. "
               "If the payoff is essentially \"the number is astronomically large/small\" or "
               "\"this has never existed before because there are so many combinations,\" score "
               "3 or below — that is magnitude, not a thought. The payoff must pass the "
               "who-cares test: it changes how the viewer sees something, or it fails."),
    "clarity": ("is the LANGUAGE plain and jargon-free — each sentence easy to parse on one "
                "listen? (Wording only; whether the MEANING holds together is judged by "
                "'coherence'.)"),
    "coherence": ("does EVERY sentence make literal sense and state something TRUE, with clear "
                  "referents? A vague pronoun the listener CANNOT resolve — e.g. a hook like "
                  "\"your great-grandparents saw its start, but it won't finish\" (start of WHAT? "
                  "finish WHAT?) — OR a DANGLING comparative with no completion — e.g. \"T. rex is "
                  "closer to you\" (closer than WHAT? — needs \"...than Stegosaurus\") — OR a "
                  "non-sequitur, OR any line that makes a smart listener think \"wait, that "
                  "doesn't even make sense\" scores 3 or below. Simple-SOUNDING but muddled is a "
                  "FAILURE here even if 'clarity' is high. This is the most important criterion: "
                  "a confusing script must not pass."),
}


def _apply_scene_rewrite(m, fact, new_scenes, label):
    """Shared by punch_up/revise_for_floors: build a trial manifest from a
    {scene_id: new_voiceover} rewrite and check it survives every guard a
    rewrite must clear — matching scene ids, no dropped mandatory key term,
    passes validate(). Returns the trial manifest on success, None if the
    rewrite must be discarded (each caller decides what "discard" means for
    it -- punch_up keeps the pre-rewrite original, revise_for_floors falls
    through to a full from-scratch regeneration)."""
    if set(new_scenes) != {s["id"] for s in m["scenes"]}:
        print(f"  {label} returned mismatched scenes, discarding")
        return None
    import copy
    trial = copy.deepcopy(m)
    for s in trial["scenes"]:
        s["voiceover"] = new_scenes[s["id"]]
    trial["script"] = " ".join(s["voiceover"] for s in trial["scenes"])
    key_terms = fact.get("key_terms", []) if fact else []
    if key_terms:
        orig_text = " ".join(s["voiceover"] for s in m["scenes"])
        new_text = " ".join(s["voiceover"] for s in trial["scenes"])
        dropped = [kt for kt in key_terms
                   if _key_term_present(kt, orig_text) and not _key_term_present(kt, new_text)]
        if dropped:
            print(f"  {label} dropped key term(s) {dropped}, discarding")
            return None
    err = validate(trial, m.get("viewer_job", ""), fact=fact)
    if err:
        print(f"  {label} rejected by validation ({err}), discarding")
        return None
    return trial


def revise_for_floors(m, fact, violations, cta_style="SAVE_WORTHY"):
    """Targeted repair for a script that failed specific rubric floors (see
    QUALITY_CRITERION_FLOORS) — the direct answer to "one weak part shouldn't
    mean scrap the whole video": instead of a blind from-scratch regeneration
    (a brand-new draft with no memory of what was wrong) this quotes the
    EXACT rubric definition for ONLY the criteria that actually failed, and
    asks for the smallest rewrite that fixes them. The caller re-scores the
    result and only keeps it if the targeted criteria demonstrably improved
    (see main()); on any failure here it returns None and the caller falls
    back to its existing regenerate-from-scratch path unchanged."""
    fact_line = fact["fact"] if fact else "the fact stated in the script"
    key_terms = fact.get("key_terms", []) if fact else []
    key_terms_rule = ""
    if key_terms:
        key_terms_rule = (
            f"- MUST preserve every one of these exact terms verbatim, spelled exactly as given, "
            f"somewhere across the rewritten lines: {key_terms}. Do not paraphrase them away or "
            f"swap a real name/number for a vaguer description.\n")
    problems = "\n".join(
        f"- {crit.upper()} scored too low (needs {QUALITY_CRITERION_FLOORS[crit]}+/10): "
        f"{RUBRIC_CRITERION_TEXT.get(crit, '')}"
        for crit in violations)
    scenes_json = json.dumps([{"id": s["id"], "voiceover": s["voiceover"]} for s in m["scenes"]])
    prompt = f"""You are a short-form script doctor. An editor just scored this FINISHED script and it failed specific checks below. Fix ONLY those problems — leave every line that isn't implicated alone.

THE VERIFIED FACT (do not alter it, do not add new numbers): "{fact_line}"

WHAT FAILED AND WHY (fix these, nothing else):
{problems}

RULES:
- Same number of scenes, same ids, same order, same underlying facts per scene.
- Each line stays ONE punchy spoken sentence, 6-18 words, natural to read aloud.
- Only touch the line(s) actually responsible for the failure(s) above; a line that
  wasn't part of the problem should come back unchanged.
- Keep any real numbers exactly as they are. Add NO new facts or numbers.
{key_terms_rule}- Every line ends with proper punctuation (. ? or !).

Scenes: {scenes_json}

Return ONLY valid JSON, exactly: {{"scenes": [{{"id": 1, "voiceover": "..."}}]}}"""
    try:
        raw = call_groq(prompt)
        new_scenes = {}
        for s in json.loads(raw)["scenes"]:
            if not s.get("voiceover"):
                continue
            line = _clean(s["voiceover"])
            if line and line[-1] not in ".?!":
                line += "."
            new_scenes[s["id"]] = line
    except Exception as e:  # noqa: BLE001 - targeted repair is best-effort
        print(f"  [targeted-repair] failed ({e})")
        return None
    return _apply_scene_rewrite(m, fact, new_scenes, "[targeted-repair]")


def inject_missing_key_terms(m, fact):
    """Targeted repair for validate()'s "only N/M mandatory key terms named"
    rejection — the single most common near-miss abandon reason seen live
    (renders 188/198/199/201). Asks for the smallest rewrite that works the
    specific MISSING term(s) in verbatim, rather than discarding an
    otherwise-clean script over one or two missing proper nouns/numbers the
    model explained around instead of naming. Self-verifying: the shared
    _apply_scene_rewrite() guard re-runs validate() at the end, so this can
    only return a manifest that actually now names the term(s) — never a
    rewrite that merely claims to. Returns None on any failure (LLM error,
    dropped a DIFFERENT term, still doesn't validate) so the caller's
    existing abandon path is unchanged."""
    key_terms = fact.get("key_terms", []) if fact else []
    if not key_terms:
        return None
    full_text = m.get("script", "") + " " + " ".join(s.get("voiceover", "") for s in m.get("scenes", []))
    missing = [kt for kt in key_terms if not _key_term_present(kt, full_text)]
    if not missing:
        return None
    scenes_json = json.dumps([{"id": s["id"], "voiceover": s["voiceover"]} for s in m["scenes"]])
    prompt = f"""You are a short-form script doctor. This script never explicitly says specific required term(s) — work them in NATURALLY, verbatim, changing as few lines as possible.

MUST explicitly say, verbatim and spelled exactly as given, somewhere across the rewritten lines: {missing}

RULES:
- Same number of scenes, same ids, same order, same underlying facts per scene.
- Each line stays ONE punchy spoken sentence, 6-18 words, natural to read aloud.
- Only touch as many lines as needed to fit the missing term(s) in naturally — a line
  that doesn't need to change should come back unchanged.
- Do not remove or paraphrase away any term that's already correctly named elsewhere.
- Every line ends with proper punctuation (. ? or !).

Scenes: {scenes_json}

Return ONLY valid JSON, exactly: {{"scenes": [{{"id": 1, "voiceover": "..."}}]}}"""
    try:
        raw = call_groq(prompt)
        new_scenes = {}
        for s in json.loads(raw)["scenes"]:
            if not s.get("voiceover"):
                continue
            line = _clean(s["voiceover"])
            if line and line[-1] not in ".?!":
                line += "."
            new_scenes[s["id"]] = line
    except Exception as e:  # noqa: BLE001 - targeted repair is best-effort
        print(f"  [key-term-repair] failed ({e})")
        return None
    return _apply_scene_rewrite(m, fact, new_scenes, "[key-term-repair]")


def score_script(m, fact=None, cta_style="SAVE_WORTHY"):
    """Self-critique pass: one Groq call scores the finished, punched-up
    script against an explicit rubric so a weak script can be caught and
    regenerated before it ever reaches main.py's render pipeline. See
    QUALITY_THRESHOLD / QUALITY_MAX_REGENERATIONS above for how the result
    is used. cta_style adjusts the "rewatch" criterion's wording to match
    this video's assigned ending style (CTA_RUBRIC_HINTS) instead of always
    asking whether it "invited a save."

    MUST fail OPEN — this pipeline runs unattended once a day. Any Groq
    error, timeout, or unparseable/out-of-range response returns None, and
    the caller treats None as "ship this attempt," never as "reject it." A
    scoring hiccup must never brick the autonomous run.
    """
    try:
        fact_line = fact["fact"] if fact else "(no verified fact; general topic)"
        whatif = fact.get("whatif", "") if fact else ""
        scenes_text = "\n".join(f"{s['id']}. {s['voiceover']}" for s in m.get("scenes", []))
        rewatch_hint = CTA_RUBRIC_HINTS.get(cta_style, CTA_RUBRIC_HINTS["SAVE_WORTHY"])
        prompt = f"""You are a brutally honest short-form video editor scoring a finished script BEFORE it is rendered and posted. Be strict — most scripts should NOT score 9 or 10.

TITLE: {m.get('title', '')}
HOOK (first spoken line): {m.get('hook', '')}
VERIFIED FACT THIS VIDEO IS BUILT ON: {fact_line}
CENTRAL QUESTION (if any): {whatif or '(none)'}
THIS VIDEO'S ASSIGNED ENDING STYLE: {cta_style}

FULL SCENE-BY-SCENE SCRIPT:
{scenes_text}

Score each criterion 0-10 (integers, be strict):
- hook: {RUBRIC_CRITERION_TEXT['hook']}
- surprise: {RUBRIC_CRITERION_TEXT['surprise']}
- escalation: {RUBRIC_CRITERION_TEXT['escalation']}
- payoff: {RUBRIC_CRITERION_TEXT['payoff']}
- rewatch: {rewatch_hint}
- clarity: {RUBRIC_CRITERION_TEXT['clarity']}
- coherence: {RUBRIC_CRITERION_TEXT['coherence']}

Return ONLY valid JSON, exactly:
{{"hook": 0, "surprise": 0, "escalation": 0, "payoff": 0, "rewatch": 0, "clarity": 0, "coherence": 0}}"""
        raw = call_groq(prompt)
        data = json.loads(raw)
        # Robust coercion: the model frequently returns a score as a STRING
        # ("8") or with a suffix ("8/10") even under JSON mode. The old code
        # required a raw int/float for EVERY criterion and returned None (=
        # ship unscored, fail-open) if even one was a string — which made the
        # whole quality ratchet silently inert whenever that happened. Coerce
        # numbers out of strings, tolerate a minority of unparseable/missing
        # criteria, and only truly fail open when we can't read a majority.
        scores, missing = {}, 0
        for k in QUALITY_RUBRIC_CRITERIA:
            sv = _coerce_score(data.get(k))
            if sv is None:
                missing += 1
            else:
                scores[k] = sv
        if len(scores) < 4:  # couldn't read a majority of 6 — genuinely unusable
            return None
        if missing:  # fill the few unreadable ones with the mean of the rest
            mean = sum(scores.values()) / len(scores)
            for k in QUALITY_RUBRIC_CRITERIA:
                scores.setdefault(k, round(mean, 2))
        # Compute overall ourselves from the per-criterion scores rather than
        # trusting the model's own arithmetic — a model that returns six 9s
        # and a self-reported "overall: 3" (or vice versa) can't silently
        # cause a good script to be rejected or a bad one to ship.
        scores["overall"] = round(sum(scores[k] for k in QUALITY_RUBRIC_CRITERIA) / len(QUALITY_RUBRIC_CRITERIA), 2)
        return scores
    except Exception as e:  # noqa: BLE001 - must fail open, never blocks a run
        print(f"  [quality] scoring failed open ({e}), treating as pass")
        return None


def critique_script(m, fact=None, cta_style="SAVE_WORTHY"):
    """ONE Groq call that does BOTH quality jobs which used to cost two calls:
    (a) flags scenes that add no new information (the semantic-redundancy gate
    that was check_information_gain), and (b) scores the script against the
    rubric (what score_script did). They analysed the identical numbered
    voiceover list, so merging them removes one LLM call per render on the
    common path (a strong clean draft skips punch-up, so the script the gate
    sees is exactly the one that ships — see generate_candidate).

    Returns (redundant_err, scores):
      redundant_err -- human string if >=1 scene is redundant, else None
      scores        -- rubric dict with 'overall', or None if unscorable
    Each half fails OPEN independently: a broken/blank half returns None for
    that half and never bricks a run. A caller that only needs one half
    ignores the other."""
    scenes = m.get("scenes", [])
    if len(scenes) < 2:
        return None, None
    try:
        numbered = "\n".join(f"{s['id']}. {s['voiceover']}" for s in scenes)
        fact_line = fact["fact"] if fact else "(no verified fact; general topic)"
        whatif = fact.get("whatif", "") if fact else ""
        rewatch_hint = CTA_RUBRIC_HINTS.get(cta_style, CTA_RUBRIC_HINTS["SAVE_WORTHY"])
        prompt = f"""You are a brutally honest short-form video editor reviewing a finished script BEFORE it is rendered and posted. Be strict — most scripts should NOT score 9 or 10.

TITLE: {m.get('title', '')}
HOOK (first spoken line): {m.get('hook', '')}
VERIFIED FACT THIS VIDEO IS BUILT ON: {fact_line}
CENTRAL QUESTION (if any): {whatif or '(none)'}
THIS VIDEO'S ASSIGNED ENDING STYLE: {cta_style}

NUMBERED SCENE-BY-SCENE VOICEOVER (in scene order):
{numbered}

Do TWO things:
1) REDUNDANCY: list the ids of any scenes that add NO new information — everything the scene says was already conveyed, even in different words, by an EARLIER scene. Scene 1 never counts (there is no earlier scene). A scene revealing a new number, mechanism, consequence, or comparison is NOT redundant even if it's on the same topic.
2) SCORE each criterion 0-10 (integers, be strict):
- hook: does the first line open a REAL curiosity gap (a specific question the viewer NEEDS answered), not just a description or a mild tease?
- surprise: would most adults genuinely react "wait, WHAT?" and be left THINKING/seeing something differently — not just hearing facts and numbers scroll by? A script that mostly recites measurements (how tall/old/fast/many) with no mind-bending IDEA behind them scores 3 or below. CRUCIAL: a pure scale or counting fact — how many ways to shuffle a deck, how many atoms/combinations exist, how many times bigger X is than Y — is NOT surprise. "That number is unimaginably big/small" makes a smart viewer shrug. Unless the scale exposes a hidden mechanism or a consequence a real person would feel, score magnitude-only scripts 3 or below.
- escalation: does EVERY scene reveal something new, with zero scenes just restating an earlier scene in different words?
- payoff: does the central question resolve into a genuine mind-bending IDEA — a realization that reframes how the viewer sees the thing — rather than a recited number or a shrug? A number as the payoff (a dry "it's 8,849 metres") is WEAK. If the payoff is essentially "the number is astronomically large/small" or "this has never existed before because there are so many combinations," score 3 or below — that is magnitude, not a thought. The payoff must pass the who-cares test: it changes how the viewer sees something, or it fails.
- rewatch: {rewatch_hint}
- clarity: is the LANGUAGE plain and jargon-free — each sentence easy to parse on one listen? (Wording only; whether the MEANING holds together is judged by 'coherence'.)
- coherence: does EVERY sentence make literal sense and state something TRUE, with clear referents? A vague pronoun the listener CANNOT resolve — e.g. a hook like "your great-grandparents saw its start, but it won't finish" (start of WHAT? finish WHAT?) — OR a DANGLING comparative with no completion — e.g. "T. rex is closer to you" (closer than WHAT? — needs "...than Stegosaurus") — OR a non-sequitur, OR any line that makes a smart listener think "wait, that doesn't even make sense" scores 3 or below. Simple-SOUNDING but muddled is a FAILURE here even if 'clarity' is high. This is the most important criterion: a confusing script must not pass.

Return ONLY valid JSON, exactly:
{{"no_new_info_scene_ids": [], "hook": 0, "surprise": 0, "escalation": 0, "payoff": 0, "rewatch": 0, "clarity": 0, "coherence": 0}}"""
        raw = call_groq(prompt)
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001 - both halves fail open together
        print(f"  [critique] failed open ({e}) — no redundancy gate this attempt, unscored")
        return None, None

    # --- redundancy half (same coercion as the old check_information_gain) ---
    redundant_err = None
    try:
        ids = data.get("no_new_info_scene_ids", [])
        clean_ids = []
        if isinstance(ids, list):
            for i in ids:
                if isinstance(i, bool):
                    continue
                if isinstance(i, int):
                    clean_ids.append(i)
                elif isinstance(i, str) and i.strip().lstrip("-").isdigit():
                    clean_ids.append(int(i.strip()))
        if len(clean_ids) >= 1:
            print(f"  [info-gain] flagged {len(clean_ids)} redundant scene(s) {clean_ids} "
                  f"— no new information beyond an earlier scene")
            redundant_err = (f"information-gain check flagged {len(clean_ids)} redundant scene(s) "
                             f"{clean_ids} (no new information beyond an earlier scene) — cut or replace them")
    except Exception:  # noqa: BLE001
        redundant_err = None

    # --- score half (same coercion as the old score_script) ---
    scores = None
    try:
        s, missing = {}, 0
        for k in QUALITY_RUBRIC_CRITERIA:
            sv = _coerce_score(data.get(k))
            if sv is None:
                missing += 1
            else:
                s[k] = sv
        if len(s) >= 4:  # readable majority of the 6 criteria
            if missing:
                mean = sum(s.values()) / len(s)
                for k in QUALITY_RUBRIC_CRITERIA:
                    s.setdefault(k, round(mean, 2))
            s["overall"] = round(sum(s[k] for k in QUALITY_RUBRIC_CRITERIA) / len(QUALITY_RUBRIC_CRITERIA), 2)
            scores = s
    except Exception:  # noqa: BLE001
        scores = None

    return redundant_err, scores


def _slugify(text, maxlen=40):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:maxlen] or "video"


def load_perf():
    """Load perf_<page>.json if present (see the format doc near PERF_PATH
    above). Never raises — a missing file, invalid JSON, or non-dict payload
    is treated as "no performance data yet," so callers always degrade
    safely to plain random selection."""
    try:
        with open(PERF_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _perf_score(entry):
    """Collapse one video's raw engagement metrics into a single 0..1-ish
    score used to weight future selection. watch_through_pct is the primary
    quality signal; follows/saves/shares/comments are rarer, higher-value actions
    scaled up relative to views so one viral outlier can't own the whole score.

    SAVES and COMMENTS added 2026-07-26: live TikTok analytics showed they're this
    page's real differentiators (jellyfish earned 6 saves; turtle drew 3 comments)
    yet were invisible to generation. A save = "I want to keep this"; a comment
    drives reach. Old entries lacking these keys simply score them 0 (safe)."""
    if not isinstance(entry, dict):
        return 0.0
    views = max(0.0, float(entry.get("views", 0) or 0))
    watch = max(0.0, min(1.0, float(entry.get("watch_through_pct", 0) or 0)))
    follows = max(0.0, float(entry.get("follows", 0) or 0))
    saves = max(0.0, float(entry.get("saves", 0) or 0))
    shares = max(0.0, float(entry.get("shares", 0) or 0))
    comments = max(0.0, float(entry.get("comments", 0) or 0))
    denom = max(views, 1.0)
    follow_rate = min(1.0, (follows / denom) * 20)
    save_rate = min(1.0, (saves / denom) * 12)
    share_rate = min(1.0, (shares / denom) * 10)
    comment_rate = min(1.0, (comments / denom) * 15)
    return (0.45 * watch + 0.22 * follow_rate + 0.15 * save_rate
            + 0.10 * share_rate + 0.08 * comment_rate)


def score_by_key(history, perf, key_field):
    """Mean _perf_score() per distinct value of key_field (e.g. "fact_id" or
    "viewer_job"), over memory history entries whose video_id has a matching
    perf_<page>.json entry. Keys with no perf data are simply absent from
    the result — callers apply PERF_UNSEEN_FLOOR themselves."""
    buckets = {}
    for h in history:
        vid, key = h.get("video_id"), h.get(key_field)
        if not vid or not key or vid not in perf:
            continue
        buckets.setdefault(key, []).append(_perf_score(perf[vid]))
    return {k: sum(v) / len(v) for k, v in buckets.items() if v}


def _weighted_choice(options, weights, epsilon):
    """Explore/exploit selection. epsilon fraction of calls (and any call
    where every weight is <= 0) pick uniformly at random across ALL options
    (explore); otherwise sample proportional to weight (exploit) — so
    better-performing options get picked more often without unseen/losing
    options ever dropping to zero chance."""
    if not options:
        return None
    if random.random() < epsilon or sum(weights) <= 0:
        return random.choice(options)
    total = sum(weights)
    r = random.uniform(0, total)
    upto = 0.0
    for opt, w in zip(options, weights):
        upto += max(0.0, w)
        if upto >= r:
            return opt
    return options[-1]


def _hook_opener(hook):
    words = re.sub(r"[^A-Za-z' ]", "", hook or "").split()
    return " ".join(w.lower() for w in words[:2])


def overused_hook_openers(history, min_count=3):
    """Light freshness guard (improvement loop, part 3): if the last several
    videos' hooks keep starting with the same 2 words, surface that opener
    so build_prompt() can nudge the next hook toward a different structure.
    Advisory only — never blocks generation. With < min_count repeats
    (including on totally fresh history) this returns [] and behavior is
    unchanged."""
    counts = collections.Counter(
        _hook_opener(h.get("hook", "")) for h in history if h.get("hook"))
    return [op for op, c in counts.items() if op and c >= min_count]


def _dossier_key(fact):
    """Stable cache key for a fact's dossier: a hash of the verified fact text
    (falling back to angle). Independent of dict ordering or the mutable
    memory window, so the same fact maps to the same key every run."""
    basis = (fact.get("fact") or fact.get("angle") or "").strip().lower()
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16] if basis else ""


def _load_dossier_cache():
    try:
        with open(DOSSIER_CACHE) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_dossier_cache(cache):
    """Best-effort persist; a cache write must never break a run. Keep only the
    most recent ~200 entries so the file can't grow unbounded across months."""
    try:
        if len(cache) > 200:
            cache = dict(list(cache.items())[-200:])
        with open(DOSSIER_CACHE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:  # noqa: BLE001
        print(f"  [research] dossier cache write skipped ({e})")


def research_dossier(fact):
    """SCIENTIST BRAIN — stage 1 (research before writing).

    The repetition problem is structural: a script locked to ONE verified fact +
    2-3 key terms has only ~4 real points but needs ~8 scenes, so it MUST pad
    with restatements. This stage first enumerates a RICH, DIVERSE set of
    specific, surprising, TRUE details about the same topic, so stage 2 can build
    each scene from a DIFFERENT real point instead of rephrasing the premise.

    Returns a list of concrete fact strings (or [] on failure — the caller then
    generates the old way, so this can never break a render). Best with the
    Gemini free tier (reliable, high quota); degrades under Groq rate limits."""
    if not fact:
        return []
    topic = fact.get("fact") or fact.get("angle") or ""
    if not topic:
        return []
    # Cache hit: this fact was already researched on a prior run — reuse those
    # angles and spend zero LLM quota. The dossier is a set of TRUE facts about
    # a fixed topic, so it doesn't go stale between runs.
    key = _dossier_key(fact)
    cache = _load_dossier_cache() if key else {}
    cached = cache.get(key)
    if isinstance(cached, list) and len([f for f in cached if str(f).strip()]) >= 5:
        print(f"  [research] dossier cache HIT ({len(cached)} angles) — no LLM call")
        return [str(f).strip() for f in cached if str(f).strip()][:10]
    kt = ", ".join(fact.get("key_terms", []) or [])
    prompt = (
        "You are the researcher behind the most fascinating science videos on the internet "
        "(think Veritasium, Kurzgesagt, Radiolab) — relentlessly curious, obsessed with the "
        "specific and the counterintuitive.\n\n"
        f'TOPIC: "{topic}"\n'
        f"Known specifics you may build on (keep these accurate): {kt}\n\n"
        "List 9 DISTINCT, genuinely surprising, CONCRETE facts about this topic — the kind that "
        "make a smart adult go 'wait, WHAT?'. Deliberately span DIFFERENT KINDS of point so none "
        "overlap: (1) a hard number or almost-unbelievable scale, (2) the hidden mechanism — HOW/WHY "
        "it actually works, (3) an extreme case or record, (4) a counterintuitive twist that "
        "contradicts what people assume, (5) a vivid physical comparison that makes a number "
        "graspable, (6) a real consequence that touches the viewer's own life, (7) a little-known "
        "discovery/historical detail, (8) an open mystery scientists still can't explain, (9) one "
        "more genuinely weird specific.\n"
        "HARD RULES: every item must contain a specific, checkable detail (a real number, name, or "
        "mechanism) — never a vague adjective. Only include things you are confident are TRUE and "
        "well-established; if unsure of a number, describe the mechanism instead of inventing one. "
        "No two items may be the same point reworded. Prefer strange-but-true over obvious.\n"
        'Return ONLY JSON: {"facts": ["...", "...", "...", "...", "...", "...", "...", "...", "..."]}'
    )
    try:
        # GROUNDED RESEARCH: pull the facts from REAL Google Search results via
        # Gemini's grounding tool so the dossier is sourced and accurate, not just
        # the model's memory. Falls back to the ordinary (ungrounded) provider
        # chain on any failure, so this never blocks a run.
        raw = None
        # Grounding is the one Gemini call that runs even on the free-first chain
        # (it's Gemini-unique). It's cached per fact, so it's a ONE-TIME cost per
        # topic — but GROUND_DOSSIER=0 skips it entirely for max frugality, falling
        # back to the free provider chain (the topic_bank facts are already curated,
        # so an ungrounded dossier is still solid).
        if GEMINI_KEY and os.getenv("GROUND_DOSSIER", "1") != "0":
            try:
                raw = _call_gemini(gemini_models()[0], prompt, ground=True)
                print("  [research] grounded on live Google Search")
            except Exception as e:  # noqa: BLE001
                print(f"  [research] grounded search unavailable ({e}); using model knowledge")
        if raw is None:
            raw = call_groq(prompt)
        data = json.loads(raw)
        facts = [str(x).strip() for x in (data.get("facts") or []) if str(x).strip()]
        facts = [f for f in facts if len(f) > 12][:10]
        if facts:
            print(f"  [research] scientist-brain dossier: {len(facts)} distinct angles gathered")
            if key and len(facts) >= 5:  # only cache a genuinely full dossier
                cache[key] = facts
                _save_dossier_cache(cache)
        return facts
    except Exception as e:
        print(f"  [research] dossier unavailable ({e}); writing from the base fact only")
        return []


def _trim_scene_to_cap(vo, cap):
    """Shorten an over-cap voiceover to <=cap words, preferring a sentence
    boundary (keep only as many whole leading sentences as fit) over a
    mid-sentence word chop; falls back to a hard word-count truncation +
    re-terminating period if even the first sentence alone exceeds the cap
    (or there's no sentence punctuation at all). Pure/testable."""
    sentences = re.split(r"(?<=[.!?])\s+", vo.strip())
    kept, count = [], 0
    for sent in sentences:
        n = len(sent.split())
        if kept and count + n > cap:
            break
        kept.append(sent); count += n
    if kept and count <= cap:
        return " ".join(kept)
    return " ".join(vo.split()[:cap]).rstrip(",;:") + "."


def generate_candidate(job_name, job_desc, avoid, chosen_fact, history, avoid_openers=None,
                        cta_style="SAVE_WORTHY", dossier=None, hook_frame=None):
    """Run the full generate -> validate -> info-gain -> punch-up pipeline
    once and return a finished manifest, or None if nothing usable came out
    of it. Called once per quality-ratchet attempt (see
    QUALITY_MAX_REGENERATIONS in main()) — every call is an independent
    round of Groq attempts with its own near-miss fallback, so a
    low-quality-score regeneration gets a genuinely fresh script, not a
    retry of the exact same one. cta_style pins which of the four rotated
    endings (CTA_ENDING_RULES) this attempt is built and punched up toward.

    dossier: the scientist-brain research facts. Passed in from main() so it's
    computed ONCE per run and reused across every regeneration attempt — the
    topic doesn't change between attempts, so re-researching it each time just
    burned a free-tier LLM call per attempt (a real contributor to the quota
    exhaustion). Falls back to computing it here if called standalone."""
    manifest = None
    near_miss = None  # a parsed script that only failed soft checks — better than murmuration fallback
    if dossier is None:
        dossier = research_dossier(chosen_fact)
    # 3 attempts, not 5. Each attempt is a full ~5k-token generation call, and
    # main() already wraps this in QUALITY_MAX_REGENERATIONS regenerations AND the
    # workflow retries the whole step once — so 5 here meant up to ~20 generation
    # calls per render, ~100k tokens, i.e. Groq's ENTIRE 100k/day budget burned by
    # a single render (the "two videos and the quota's gone" report). 3 attempts +
    # the near-miss repair path keeps the yield while cutting worst-case burn ~40%,
    # which is what lets the morning buffer bank several scripts instead of ~2.
    for attempt in range(int(os.getenv("GEN_MAX_ATTEMPTS", "2"))):
        try:
            # If the circuit has already opened (every provider rate-limited 3x
            # in a row this run), the escalating backoff below cannot outlast a
            # dead daily quota — each remaining attempt would just sleep, then
            # fail-fast. Stop here so a fully-throttled render aborts in seconds
            # instead of grinding through 8+16+24+32s of sleeps per regeneration.
            # When the LLM is healthy the circuit never opens, so this is a no-op.
            if _CIRCUIT_OPEN:
                print(f"  attempt {attempt+1} skipped: LLM circuit open (all providers "
                      f"rate-limited) — abandoning further attempts to fail fast")
                break
            if attempt > 0:
                time.sleep(8 * attempt)  # escalating cushion — a flat 8s wasn't enough to outlast a 429
            _bp = build_prompt(job_name, job_desc, avoid, fact=chosen_fact,
                               avoid_openers=avoid_openers, cta_style=cta_style,
                               dossier=dossier, hook_frame=hook_frame)
            raw = call_groq(_bp)
            if not (raw or "").strip():
                # a strong writer occasionally returns an EMPTY body (OpenRouter
                # hiccup — twice in render 163: "Expecting value: line 1 column 1").
                # One immediate re-call recovers it instead of spending the whole
                # (of only 2) attempt on a blank response.
                print(f"  attempt {attempt+1}: empty model response — one immediate retry")
                raw = call_groq(_bp)
            m = json.loads(raw)
            if not isinstance(m, dict):
                # some models (esp. gemma) occasionally return a bare JSON array
                # or string; validate()/m.get() would then raise
                # "'list' object has no attribute 'get'". Treat as an invalid
                # attempt and retry rather than erroring out.
                print(f"  attempt {attempt+1} invalid: model returned a {type(m).__name__}, not a JSON object")
                continue
            err = validate(m, job_name, fact=chosen_fact)
            if err:
                print(f"  attempt {attempt+1} invalid: {err}")
                # keep it as a backup if it at least has the core pieces
                if all(k in m for k in ("title", "hook", "script", "scenes", "captions")) and near_miss is None:
                    near_miss = m
                continue
            if _hits_banned_concept(m.get("metaphor", ""), m.get("title", "")):
                print(f"  attempt {attempt+1} hits a banned concept "
                      f"(flocking/emergence/etc), retrying"); continue
            if _metaphor_too_similar(m.get("metaphor", ""), history):
                print(f"  attempt {attempt+1} too similar to a recent topic, retrying"); continue
            # ONE call does the redundancy gate AND the rubric score (was two
            # separate Groq calls over the same voiceover list). The score is
            # stashed on the manifest so main()'s quality ratchet can reuse it
            # without a second call — valid because a strong clean draft skips
            # punch-up below, so this is the script that ships. Any path that
            # rewrites the script (punch-up, near-miss repair) clears/omits the
            # stash and main() re-scores.
            ig_err, _stashed_quality = critique_script(m, fact=chosen_fact, cta_style=cta_style)
            if ig_err:
                print(f"  attempt {attempt+1} invalid: {ig_err}")
                if near_miss is None:
                    near_miss = m
                continue
            if _stashed_quality:
                m["_quality"] = _stashed_quality
            manifest = m; break
        except Exception as e:
            print(f"  attempt {attempt+1} error: {e}")

    if not manifest and near_miss is not None:
        # repair the near-miss minimally so it can render, rather than fall back to murmuration
        print("  using best near-miss (repaired)")
        nm = near_miss
        nm.setdefault("render", {"voice": "en-US-GuyNeural", "rate": "-5%", "resolution": "1080x1920"})
        nm["hashtags"] = nm.get("hashtags", ["#science"])
        nm["captions"] = nm.get("captions") or [nm.get("title", "Watch this")]
        # ENFORCE PACING + LENGTH on the near-miss too. A script usually lands
        # here precisely BECAUSE the stricter validate() rejected it (too many
        # scenes / a run-on / repetition / too long), and the old repair shipped
        # it uncapped — that's how the 147-word "DNA Stretched Out" stat-dump got
        # out (run 79). Iteratively drop the single most-REDUNDANT middle scene
        # (always keeping the hook and the ending) until BOTH the scene count and
        # the word count are in range — this cuts choppy over-cutting AND the
        # restatement in one pass. If it's STILL over the hard word cap once we
        # hit the minimum scene count, this near-miss is irredeemable (a weak
        # model dumped a long, repetitive script) — abandon it so the run aborts
        # rather than shipping a weak video (consistency over cadence).
        import difflib as _dl
        NEARMISS_MAX_SCENES = SCENE_MAX
        NEARMISS_MAX_WORDS = WORD_HARD_HI    # tracks validate()'s hard cap (length-mode aware)
        NEARMISS_MIN_SCENES = SCENE_MIN      # validate()'s floor — never trim below it
        _scenes = nm.get("scenes", [])
        def _wc(scs):
            return sum(len(s.get("voiceover", "").split()) for s in scs)
        def _most_redundant_middle(scs):
            best_i, best_r = None, -1.0
            for i in range(1, len(scs) - 1):
                vo = scs[i].get("voiceover", "").lower()
                r = max((_dl.SequenceMatcher(None, vo, scs[j].get("voiceover", "").lower()).ratio()
                         for j in range(len(scs)) if j != i), default=0.0)
                if r > best_r:
                    best_i, best_r = i, r
            return best_i
        _dropped = 0
        while len(_scenes) > NEARMISS_MIN_SCENES and (
                len(_scenes) > NEARMISS_MAX_SCENES or _wc(_scenes) > NEARMISS_MAX_WORDS):
            _i = _most_redundant_middle(_scenes)
            if _i is None:
                break
            _scenes.pop(_i); _dropped += 1
        if _dropped:
            for _new_id, s in enumerate(_scenes, 1):
                s["id"] = _new_id
            nm["scenes"] = _scenes
            print(f"  near-miss trimmed {_dropped} most-redundant middle scene(s) -> "
                  f"{len(_scenes)} scenes / {_wc(_scenes)} words (pacing/length/repetition)")
        # SHORTEN (don't drop) any single scene over the per-scene cap. Scene-
        # dropping above only fixes TOTAL word/scene count -- it can't touch a
        # near-miss whose sole problem is one over-cap sentence, and dropping
        # that scene outright would also delete whatever key term/escalation
        # beat it was carrying. Renders 189/194/198/199 all abandoned an
        # otherwise-clean near-miss over exactly this (one 24-30 word scene
        # against the 25-word cap) -- prefer a sentence-boundary trim (keep
        # only as many whole leading sentences as fit) over losing the scene.
        # (_trim_scene_to_cap is module-level, above generate_candidate, so
        # it's directly unit-tested without mocking the whole repair path.)
        _trimmed = 0
        for s in _scenes:
            vo = s.get("voiceover", "")
            if len(vo.split()) > SCENE_WORD_CAP:
                s["voiceover"] = _trim_scene_to_cap(vo, SCENE_WORD_CAP)
                _trimmed += 1
        if _trimmed:
            nm["scenes"] = _scenes
            print(f"  near-miss shortened {_trimmed} over-cap scene(s) to fit the "
                  f"{SCENE_WORD_CAP}-word ceiling (trimmed, not dropped -- keeps the "
                  f"scene's content/key term intact)")
        # CURIOSITY-GAP INJECTION: "whatif curiosity gap never opened" is a
        # 100% MECHANICAL check (a literal '?' somewhere in the hook + first
        # few scenes) and the exact fix text already exists verbatim on the
        # fact (whatif) -- no LLM call needed, just place it. Renders 196/197
        # each abandoned an otherwise-clean near-miss over exactly this (the
        # model forgot to literally ask its own question early). Only fires
        # when the near-miss doesn't already open one and there's a scene 2
        # to carry it.
        if chosen_fact and chosen_fact.get("whatif") and len(_scenes) > 1:
            _early_n = min(4, len(_scenes))
            _early_text = (nm.get("hook", "") + " " +
                           " ".join(s.get("voiceover", "") for s in _scenes[:_early_n]))
            if "?" not in _early_text:
                _q = chosen_fact["whatif"].strip()
                if _q and _q[-1] != "?":
                    _q += "?"
                if _q:
                    _target = _scenes[1]
                    _merged = f"{_q} {_target.get('voiceover', '')}".strip()
                    _target["voiceover"] = _trim_scene_to_cap(_merged, SCENE_WORD_CAP)
                    nm["scenes"] = _scenes
                    print("  near-miss injected the missing curiosity-gap question "
                          "into scene 2 (mechanical fix, no LLM call)")
        if _wc(_scenes) > NEARMISS_MAX_WORDS:
            print(f"  near-miss still {_wc(_scenes)} words after trimming to {len(_scenes)} scenes "
                  f"(cap {NEARMISS_MAX_WORDS}) — abandoning this weak/long draft (consistency over cadence)")
            return None
        # fill in queries the model left out or made un-filmable. Duplicate
        # queries are deliberately NOT swapped here (they used to be, via a
        # "seen" set) -- that was the same bug fixed in validate(): main.py's
        # fetch_clip already excludes previously-used clip ids per scene, so
        # two scenes sharing a query get different clips automatically, and
        # swapping to an unrelated pool term (e.g. "night sky timelapse" for
        # an ocean/plankton scene) was actively making footage LESS relevant,
        # not preventing repeated footage.
        pool = (chosen_fact.get("queries", []) if chosen_fact else []) + VARIETY_QUERIES
        for i, s in enumerate(nm.get("scenes", [])):
            s.setdefault("motion", "zoom_in"); s.setdefault("duration", 5)
            s.setdefault("on_screen_text", "")
            if not s.get("search_query") or UNSTOCKABLE_Q.search(s.get("search_query", "")):
                s["search_query"] = pool[i % len(pool)]
        # strip any lingering banned generic save-command phrasing -- even the
        # last-resort near-miss path must not ship the old hard-coded line.
        for s in nm.get("scenes", []):
            vo = s.get("voiceover", "")
            if GENERIC_SAVE_CMD.search(vo):
                s["voiceover"] = GENERIC_SAVE_CMD.sub("", vo).strip(" .") or "Now you know."
        nm["script"] = " ".join(s.get("voiceover", "") for s in nm.get("scenes", []))
        # Log-only info-gain pass on the repaired near-miss: this is the
        # last-resort path that exists specifically so the unattended run can
        # never come up empty, so it is not rejected here even if flagged --
        # but the run log should still show a redundant near-miss was shipped
        # rather than silently hiding it.
        nm_ig_err = check_information_gain(nm)
        if nm_ig_err:
            print(f"  [info-gain] near-miss fallback still redundant ({nm_ig_err}) — "
                  f"shipping anyway (last-resort fallback, never blocks the run)")
        # RE-VALIDATE THE REPAIR (render-186 bug): everything above only fixes
        # PACING (scene/word count) and a couple of hardcoded patterns — it does
        # NOT address whatever ORIGINAL reason put this draft in near_miss in the
        # first place. near_miss is only ever set when validate() rejected the
        # attempt, so if that rejection was e.g. a mechanical jargon/register/
        # coherence violation (DANGLING_COMPARATIVE_RE, FORMAL_INVERSION_RE,
        # JARGON_TERM_RE, the whatif/contradiction guards, ...), the repaired
        # draft still has that exact problem — a length-only repair cannot fix
        # it. Render 186 shipped "the antisolar point" this way: validate()
        # correctly rejected it on EVERY attempt ("names unexplained jargon
        # 'antisolar point'"), yet the near-miss repair only trimmed scene
        # count/word count and shipped the untouched jargon anyway. Re-running
        # the SAME validate() used to gate fresh attempts closes that loophole:
        # a near-miss that still fails ANY validate() rule is exactly the junk
        # video this pipeline exists to never publish, not a shippable fallback.
        _repair_err = validate(nm, job_name, fact=chosen_fact)
        # TARGETED REPAIR for the single most common near-miss abandon reason
        # seen live (renders 188/198/199/201): the script never explicitly
        # NAMED a required term. One extra call that works the missing
        # term(s) in, rather than discarding an otherwise-clean script over
        # one or two missing proper nouns/numbers. Only attempted for this
        # exact error (see inject_missing_key_terms's docstring for why it's
        # safe to try) — every other rejection reason still aborts as before.
        if _repair_err and chosen_fact and "mandatory key terms" in _repair_err:
            _fixed = inject_missing_key_terms(nm, chosen_fact)
            if _fixed is not None:
                nm = _fixed
                _repair_err = None
                print("  near-miss repaired the missing key term(s) with a targeted rewrite")
        if _repair_err:
            print(f"  near-miss still fails validation after repair ({_repair_err}) — "
                  f"abandoning this weak draft (consistency over cadence)")
            return None
        # Mark this as a DEGRADED candidate: it reached the repair path because
        # strict validate() rejected every real attempt (usually because the LLM
        # was rate-limited/exhausted and never produced a clean script). main()
        # uses this together with whether quality scoring was available to decide
        # whether to ship or ABORT — a degraded near-miss that also can't be
        # scored is exactly the junk video we must never publish. Stripped before
        # the manifest is written to disk.
        nm["_degraded"] = True
        manifest = nm

    if not manifest:
        return None

    # CALL-BUDGET SAVER: punch_up + its follow-up info-gain check are 2 extra LLM
    # calls that sharpen the voiceovers. A CLEAN (non-degraded) draft from a
    # STRONG model is already written to the full addictive-craft spec and is
    # punchy on its own, so skip punch_up for it — saving ~2 calls per render on
    # the common path (which is where quota is spent). Weak-model drafts and
    # repaired near-misses still get punched up, where it actually helps. Set
    # PUNCHUP_ALWAYS=1 to force the old always-punch-up behaviour.
    _strong_write = (_WORKING_MODEL or ("", ""))[0] in (
        "gemini", "openrouter", "together", "fireworks", "groq")
    if (not manifest.get("_degraded")) and _strong_write and os.getenv("PUNCHUP_ALWAYS") != "1":
        print("  [budget] clean draft from a strong model — skipping punch-up (saves 2 LLM calls)")
        return manifest

    # Past this point the script gets rewritten (punch-up) or was a repaired
    # near-miss, so the score stashed at the gate no longer describes what will
    # ship. Drop it (punch_up deepcopies the manifest, so it would otherwise
    # ride a stale score onto the rewrite) — main() re-scores this path fresh.
    manifest.pop("_quality", None)
    result = punch_up(manifest, chosen_fact, cta_style=cta_style)
    # Ensure information-gain is checked on the SCRIPT THAT ACTUALLY SHIPS,
    # not just the pre-punch-up draft: punch_up rewrites every voiceover line,
    # so it's the one place after validate() that could reintroduce semantic
    # redundancy the earlier check already cleared. If punch_up's rewrite is
    # now flagged, fall back to the pre-punch-up manifest, which already
    # passed this same check (or was explicitly logged as the last-resort
    # near-miss exception above).
    if result is not manifest:
        post_ig_err = check_information_gain(result)
        if post_ig_err:
            print(f"  post-punch-up info-gain check failed ({post_ig_err}), "
                  f"reverting to pre-punch-up script")
            return manifest
    return result


def main():
    if not GROQ_KEY:
        print("ERROR: GROQ_API_KEY not set"); sys.exit(1)

    history = load_memory()
    # avoid list = recent metaphors PLUS the always-banned concepts, so the
    # model is steered off both recent topics and the flagged flocking/
    # emergence idea from the very first attempt.
    _recent_metaphors = [h.get("metaphor", "") for h in history if h.get("metaphor")]
    avoid = ", ".join(_recent_metaphors + BANNED_CONCEPTS) or "none yet"
    avoid_openers = overused_hook_openers(history)

    # Performance-memory scaffold (improvement loop, part 2): fully optional,
    # fully fail-safe. With no perf_<page>.json (today's reality for every
    # page), fact_scores/job_scores stay {} and selection below falls
    # straight through to the exact same random.choice() calls as before.
    perf = load_perf()
    fact_scores = score_by_key(history, perf, "fact_id") if perf else {}
    job_scores = score_by_key(history, perf, "viewer_job") if perf else {}
    cta_scores = score_by_key(history, perf, "cta_style") if perf else {}
    hook_scores = score_by_key(history, perf, "hook_frame") if perf else {}

    # Path C: pick a verified fact from the bank not used recently. Dedup is
    # now two-layered: exclude the exact fact_id used before AND exclude the
    # DOMAIN of the last RECENT_DOMAIN_WINDOW videos, so a different exact fact
    # that is still "the same kind of video" (two space facts, two animal
    # facts) doesn't ship back to back. Domain comes from the new memory field
    # with a bank lookup fallback for older entries that predate it. Filters
    # widen gracefully if they would empty the pool.
    bank = load_bank()
    used_ids = {h.get("fact_id") for h in history if h.get("fact_id")}
    _id_to_domain = {f["id"]: f.get("domain") for f in bank}
    recent_families = set()
    for h in history[-RECENT_DOMAIN_WINDOW:]:
        d = h.get("domain") or _id_to_domain.get(h.get("fact_id"))
        if d:
            recent_families.add(_domain_family(d))
    fresh = [f for f in bank
             if f["id"] not in used_ids and _domain_family(f.get("domain")) not in recent_families]
    available = fresh or [f for f in bank if f["id"] not in used_ids] or bank
    if recent_families:
        print(f"  [bank] avoiding recent domain families {sorted(recent_families)} "
              f"({len(fresh)} of {len(bank)} facts fresh)")
    if available and fact_scores:
        weights = [fact_scores.get(f["id"], 0.0) + PERF_UNSEEN_FLOOR for f in available]
        chosen_fact = _weighted_choice(available, weights, EXPLORE_EPSILON)
    else:
        chosen_fact = random.choice(available) if available else None
    if chosen_fact:
        print(f"  [bank] fact: {chosen_fact['id']}")
    last_job = history[-1].get("viewer_job") if history else None
    jobs = [j for j in VIEWER_JOBS if j[0] != last_job] or VIEWER_JOBS
    # HOW_TO asks for a household demo the viewer can try. That is incompatible
    # with a fixed verified fact from the bank: pairing "immortal jellyfish"
    # with HOW_TO once produced a jellyfish script that bolted an unrelated
    # dish-soap experiment onto the final scene. When a bank fact is driving
    # the video, exclude HOW_TO — it only makes sense as a standalone demo job.
    if chosen_fact:
        jobs = [j for j in jobs if j[0] != "HOW_TO"] or jobs
    if job_scores:
        weights = [job_scores.get(j[0], 0.0) + PERF_UNSEEN_FLOOR for j in jobs]
        job_name, job_desc = _weighted_choice(jobs, weights, EXPLORE_EPSILON)
    else:
        job_name, job_desc = random.choice(jobs)
    print(f"[generate] job={job_name} avoiding={avoid[:80]}")

    # CTA style selection (save-worthiness overhaul, part 2): rotate the
    # ending mechanic per video instead of always closing on the same save
    # command. Excludes whatever style the last video used so back-to-back
    # videos don't repeat an ending, same pattern as last_job above. Once
    # perf_<page>.json has real engagement data, weights lean toward
    # styles that actually earn saves/shares/comments/rewatches for THIS
    # page; until then this is a plain rotation (PERF_UNSEEN_FLOOR keeps
    # every style in the running).
    last_cta = history[-1].get("cta_style") if history else None
    cta_options = [c for c in CTA_STYLES if c != last_cta] or CTA_STYLES
    if cta_scores:
        weights = [cta_scores.get(c, 0.0) + PERF_UNSEEN_FLOOR for c in cta_options]
        cta_style = _weighted_choice(cta_options, weights, EXPLORE_EPSILON)
    else:
        cta_style = random.choice(cta_options)
    print(f"[generate] cta_style={cta_style}")

    # Rotate the OPENING-LINE shape too (see HOOK_FRAMES) so consecutive videos
    # don't all open the same way — avoid the frame the last video used.
    last_frame = history[-1].get("hook_frame") if history else None
    frame_options = [f for f in HOOK_FRAMES if f[0] != last_frame] or HOOK_FRAMES
    # The hook drives retention more than anything, so once perf data exists lean
    # toward the opening shapes that actually held viewers on THIS page (same
    # explore/exploit + unseen-floor mechanic as fact/job/cta above). No data =
    # plain rotation, unchanged.
    if hook_scores:
        weights = [hook_scores.get(f[0], 0.0) + PERF_UNSEEN_FLOOR for f in frame_options]
        hook_frame = _weighted_choice(frame_options, weights, EXPLORE_EPSILON)
    else:
        hook_frame = random.choice(frame_options)
    print(f"[generate] hook_frame={hook_frame[0]}")

    # Quality ratchet (improvement loop, part 1): generate, self-critique,
    # and — if the score is below QUALITY_THRESHOLD — regenerate from
    # scratch, bounded to QUALITY_MAX_REGENERATIONS extra attempts. Keeps
    # the best-scoring attempt across all rounds and ships it even if none
    # cleared the bar, so this can never block the daily run.
    # Research the topic ONCE up front and reuse it for every regeneration
    # attempt — the topic is identical across attempts, so re-researching per
    # attempt just burned a free-tier LLM call each time (part of why the daily
    # quota ran out). Each attempt still writes a genuinely fresh script from
    # this shared research base.
    shared_dossier = research_dossier(chosen_fact)
    best_manifest, best_overall, best_quality, best_rank = None, None, None, None
    _gen_deadline = time.time() + GEN_WALL_BUDGET_S
    for regen_i in range(QUALITY_MAX_REGENERATIONS + 1):
        # Wall-clock backstop: if the generation loop has already spent its whole
        # budget (see GEN_WALL_BUDGET_S) — which only happens when every provider
        # is throttled and attempts are stuck in stacked backoffs — stop trying.
        # Whatever we have (best_manifest, possibly None) then flows into the
        # abort/hard-floor logic below, so a fully-throttled run fails fast rather
        # than grinding ~10 min. A healthy run clears all attempts far under budget.
        if time.time() > _gen_deadline:
            print(f"  [quality] generation wall-clock budget ({GEN_WALL_BUDGET_S}s) exhausted "
                  f"after {regen_i} attempt(s) — providers throttled; stopping so the run "
                  f"fails fast instead of grinding on doomed retries")
            break
        candidate = generate_candidate(job_name, job_desc, avoid, chosen_fact, history, avoid_openers,
                                        cta_style=cta_style, dossier=shared_dossier, hook_frame=hook_frame)
        if candidate is None:
            print(f"  [quality] attempt {regen_i+1}: generation produced nothing usable")
            continue
        # Reuse the score computed alongside the redundancy gate (critique_script)
        # when the candidate carried it through unchanged — the common strong-clean
        # path — so we don't spend a second LLM call re-scoring the identical
        # script. Any rewritten/near-miss path has no stash and is scored here.
        quality = candidate.pop("_quality", None)
        if quality is None:
            quality = score_script(candidate, chosen_fact, cta_style=cta_style)
        if quality is None:
            # Scoring itself broke (usually the LLM is rate-limited/exhausted).
            # Fail OPEN only for a CLEAN candidate — one that passed strict
            # validate() — because that script is structurally sound and just
            # couldn't be graded. A DEGRADED near-miss with no score is the
            # worst case: no research, no punch-up, no grading, shipped anyway.
            # That is precisely how quota-exhausted runs 52/53 published thin,
            # repetitive videos. Refuse it — try another attempt, and if every
            # attempt is degraded+unscored, main() aborts the run (no bad video
            # published) instead of polluting the profile.
            if candidate.get("_degraded"):
                print(f"  [quality] attempt {regen_i+1}: degraded near-miss AND scoring "
                      f"unavailable (LLM exhausted) — refusing to ship, trying another attempt")
                continue
            print(f"  [quality] attempt {regen_i+1}: scoring failed open on a clean script — shipping this attempt")
            best_manifest, best_quality, best_overall = candidate, None, None
            break
        overall = quality["overall"]
        # A REAL score (as opposed to the fail-open None above) that breaks a
        # per-criterion floor must trigger regeneration NO MATTER how high the
        # average is -- this is what catches a script like the Sun video
        # (overall 7.17, payoff 5).
        violations = {k: quality[k] for k, floor in QUALITY_CRITERION_FLOORS.items()
                      if quality.get(k, 10) < floor}
        flag = f" — FLOOR VIOLATION {violations} (floors: {QUALITY_CRITERION_FLOORS})" if violations else ""
        print(f"  [quality] attempt {regen_i+1}: overall {overall}/10 {quality}{flag}")
        # Rank best-so-far by (no floor violation, overall) so that, if the
        # regen budget runs out, we ship the best NON-violating attempt we
        # saw rather than whichever had the highest average regardless of a
        # broken payoff/hook/escalation.
        rank = (0 if violations else 1, overall)
        if best_rank is None or rank > best_rank:
            best_manifest, best_overall, best_quality, best_rank = candidate, overall, quality, rank
        if violations:
            print(f"  [quality] attempt {regen_i+1} rejected: per-criterion floor broken "
                  f"regardless of overall {overall} — regenerating")
            # TARGETED REPAIR before burning a whole new blind regeneration:
            # most floor violations are a property of a FEW specific lines
            # (a flat hook, a restated scene, a muddled sentence), not the
            # entire script -- throwing the whole draft away and hoping a
            # brand-new attempt does better (with no memory of what was
            # actually wrong) is the expensive, unreliable way to fix it.
            # One extra call, spent only when there's a concrete, named
            # problem to fix; only kept if it demonstrably clears the SAME
            # floors it was asked to fix (re-scored, not assumed).
            revised = revise_for_floors(candidate, chosen_fact, violations, cta_style=cta_style)
            if revised is not None:
                r_quality = score_script(revised, chosen_fact, cta_style=cta_style)
                if r_quality is not None:
                    r_overall = r_quality["overall"]
                    r_violations = {k: r_quality[k] for k, floor in QUALITY_CRITERION_FLOORS.items()
                                     if r_quality.get(k, 10) < floor}
                    print(f"  [targeted-repair] re-scored: overall {r_overall}/10 {r_quality}"
                          + (f" — still violates {r_violations}" if r_violations
                             else " — CLEARED the floor(s) that failed"))
                    r_rank = (0 if r_violations else 1, r_overall)
                    if best_rank is None or r_rank > best_rank:
                        best_manifest, best_overall, best_quality, best_rank = (
                            revised, r_overall, r_quality, r_rank)
                    if not r_violations and r_overall >= QUALITY_THRESHOLD:
                        print(f"  [targeted-repair] cleared threshold ({r_overall} >= "
                              f"{QUALITY_THRESHOLD}) with no floor violations — shipping")
                        break
            continue
        if overall >= QUALITY_THRESHOLD:
            print(f"  [quality] cleared threshold ({overall} >= {QUALITY_THRESHOLD}) with no "
                  f"floor violations — shipping")
            break
    else:
        if best_manifest is not None:
            print(f"  [quality] no attempt cleared {QUALITY_THRESHOLD} with all floors intact — "
                  f"shipping best-scoring attempt (overall {best_overall})")

    # --- Gemini quality-rescue (frugal escalation) ---------------------------
    # The free providers (github:gpt-4o-mini / groq:llama) carry the COMMON case
    # at ~$0. But when the strongest free models are unavailable — e.g. after
    # OpenRouter dropped its free llama-3.3-70b and render 130 could only manage
    # overall 6.83 / surprise 4 on gpt-4o-mini — the free chain returns a
    # syntactically-valid but genuinely WEAK script, and the Gemini backstop in
    # call_groq never fires (it only triggers when a provider FAILS to return, not
    # when it returns something weak). Rather than ship that weak video OR abort
    # the whole run, spend exactly ONE grounded Gemini attempt here, gated so it
    # fires ONLY on weak nights: a paid Gemini key must exist AND the best free
    # draft must be genuinely weak (below the clean threshold OR breaking a
    # per-criterion floor). On the many nights the free chain writes a clean 7.5+,
    # the loop already `break`s above and this block is skipped → $0. This is the
    # "use some Gemini credits but be frugal" trade: pennies only when they buy
    # back the "consistently GOOD" the channel depends on.
    if GEMINI_KEY and best_manifest is not None and draft_is_weak(best_overall, best_quality):
        global _FORCE_GEMINI_GEN
        print(f"  [rescue] best free draft is weak (overall {best_overall}) — spending ONE "
              f"grounded Gemini attempt before shipping-weak/aborting (frugal escalation; "
              f"consistency over cadence)")
        _FORCE_GEMINI_GEN = True
        try:
            cand = generate_candidate(job_name, job_desc, avoid, chosen_fact, history,
                                      avoid_openers, cta_style=cta_style,
                                      dossier=shared_dossier, hook_frame=hook_frame)
        except Exception as e:  # noqa: BLE001 — a failed rescue must never crash the run
            print(f"  [rescue] gemini attempt errored ({e}); keeping the free draft")
            cand = None
        finally:
            _FORCE_GEMINI_GEN = False
        if cand is not None:
            q = cand.pop("_quality", None)
            if q is None:
                q = score_script(cand, chosen_fact, cta_style=cta_style)
            if q is not None:
                ov = q["overall"]
                viol = {k: q[k] for k, fl in QUALITY_CRITERION_FLOORS.items() if q.get(k, 10) < fl}
                rank = (0 if viol else 1, ov)
                print(f"  [rescue] gemini attempt: overall {ov}/10 {q}"
                      + (f" — FLOOR VIOLATION {viol}" if viol else ""))
                if best_rank is None or rank > best_rank:
                    best_manifest, best_overall, best_quality, best_rank = cand, ov, q, rank
                    print(f"  [rescue] gemini draft adopted (rank {rank}) — stronger than the free draft")
                else:
                    print("  [rescue] gemini draft was no better than the free draft — keeping the free one")
            else:
                print("  [rescue] gemini attempt could not be scored — keeping the free draft")

    manifest = best_manifest
    if not manifest:
        # Reaching here means no attempt produced a clean, shippable script —
        # typically every attempt was a degraded near-miss that also couldn't be
        # quality-scored because the LLM providers were rate-limited/exhausted.
        # Aborting (exit 1) is deliberate: the workflow's generate step turns a
        # non-zero exit into "no render, no release", so a quota-starved run
        # publishes NOTHING rather than a thin, repetitive fallback video. The
        # daily cron simply tries again once the free quotas reset.
        print("ERROR: could not generate a valid manifest — no clean script this run "
              "(likely LLM quota exhausted). Aborting so no degraded video is published.")
        sys.exit(1)

    # HARD QUALITY FLOOR (see QUALITY_HARD_FLOOR): we have a manifest, but if the
    # best the loop could produce is still genuinely weak — a broken core
    # dimension (floor violation) or an overall below the hard floor — publish
    # NOTHING instead. This is what stops the run-54 case (overall 6.0, hook
    # 4/10, 2 redundant scenes) from ever shipping. best_quality is None only for
    # a clean, structurally-valid script we couldn't grade (fail-open); that one
    # is allowed through.
    if best_quality is not None:
        floor_viol = {k: best_quality[k] for k, fl in QUALITY_CRITERION_FLOORS.items()
                      if best_quality.get(k, 10) < fl}
        if floor_viol or (best_overall is not None and best_overall < QUALITY_HARD_FLOOR):
            print(f"ERROR: best script is below the hard quality floor "
                  f"(overall {best_overall}, floor violations {floor_viol or 'none'}). "
                  f"Aborting so no weak video is published — consistency over cadence; "
                  f"the daily cron retries next run.")
            sys.exit(1)

    # Stable video id for the performance-memory loop: PAGE + date + a title
    # slug. Written into the manifest so main.py can carry it through to
    # out/post.json, and into memory_<page>.json so a later perf_<page>.json
    # can be matched back to this run (see PERF_PATH doc above).
    video_id = f"{PAGE}_{datetime.date.today().isoformat()}_{_slugify(manifest.get('title', ''))}"
    manifest["video_id"] = video_id
    # cta_style is engine-assigned (main() above), not model-authored, but it's
    # part of the manifest so main.py can carry it through to out/post.json
    # and so a publisher/scheduler downstream can see which ending shipped.
    manifest["cta_style"] = cta_style
    # Carry the topic domain through to the manifest (and thus out/post.json)
    # so funnel.py can pick the topic-matched affiliate angle per video.
    manifest["domain"] = chosen_fact.get("domain") if chosen_fact else None
    # VIBE + hybrid real/AI footage mode — see the definitions above. Applied
    # HERE (the single point every generation path converges on: live attempts,
    # the near-miss/punch-up fallback, and the Gemini rescue) so it's baked into
    # manifest.json before enqueue/dequeue ever sees it, rather than duplicated
    # at each of those call sites.
    _normalize_vibe(manifest)
    _assign_footage_mode(manifest.get("scenes", []))
    # internal-only gate flag (see generate_candidate / the quality loop) — never
    # belongs in the manifest main.py renders from.
    manifest.pop("_degraded", None)
    manifest.pop("_quality", None)  # internal score stash — never ships to render

    # SPLIT WRITE FROM RENDER: in --enqueue mode the finished manifest goes into
    # the buffer for a later render instead of manifest.json; memory is still
    # updated below either way, so the next generation in a batch avoids this
    # topic (keeping a buffered batch diverse).
    if GEN_MODE == "enqueue":
        enqueue_manifest(manifest, video_id)
    else:
        with open(OUT_MANIFEST, "w") as f:
            json.dump(manifest, f, indent=2)
    save_memory(history, {
        "video_id": video_id,
        "metaphor": manifest.get("metaphor", manifest["title"]),
        "viewer_job": job_name,
        "cta_style": cta_style,
        "hook_frame": hook_frame[0] if hook_frame else None,
        "title": manifest["title"],
        "fact_id": chosen_fact["id"] if chosen_fact else None,
        "domain": chosen_fact.get("domain") if chosen_fact else None,
        "hook": manifest.get("hook", ""),
        "vibe": manifest.get("vibe", ""),
        "structure": {
            "scene_count": len(manifest.get("scenes", [])),
            "used_whatif": bool(chosen_fact and chosen_fact.get("whatif")),
        },
        "quality": best_quality,
    })
    _dest = f"buffer ({QUEUE_DIR})" if GEN_MODE == "enqueue" else OUT_MANIFEST
    print(f"[generate] wrote {manifest['title']!r} ({job_name}, cta={cta_style}) -> "
          f"{_dest} [video_id={video_id}]")

def record_perf(argv):
    """Write/merge one video's engagement metrics into perf_<page>.json so future
    generation leans toward what performs (see PERF_PATH doc). argv is
    [video_id, key=value, ...] with keys views/watch/follows/shares. Idempotent
    merge: re-recording a video updates only the keys you pass. Returns exit code."""
    if not argv:
        print("usage: generate.py --record <video_id> views=.. watch=0..1 follows=.. shares=..")
        return 2
    vid = argv[0]
    alias = {"watch": "watch_through_pct", "watch_pct": "watch_through_pct",
             "wtp": "watch_through_pct", "view": "views", "follow": "follows",
             "share": "shares", "save": "saves", "bookmark": "saves",
             "bookmarks": "saves", "comment": "comments", "like": "likes",
             "likes": "likes"}
    metrics = {}
    for tok in argv[1:]:
        if "=" not in tok:
            print(f"  skipping '{tok}' (expected key=value)"); continue
        k, v = tok.split("=", 1)
        k = alias.get(k.strip().lower(), k.strip().lower())
        try:
            metrics[k] = float(v) if ("." in v or k == "watch_through_pct") else int(v)
        except ValueError:
            print(f"  skipping '{tok}' (value not a number)")
    try:
        data = load_perf()
    except Exception:
        data = {}
    entry = data.get(vid, {}) if isinstance(data.get(vid), dict) else {}
    entry.update(metrics)
    data[vid] = entry
    with open(PERF_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[perf] recorded {vid}: {entry}  (score {_perf_score(entry):.3f}) -> {PERF_PATH}")
    print(f"[perf] {len(data)} video(s) now have analytics; generation will weight toward winners.")
    return 0


if __name__ == "__main__":
    # --dequeue renders from the pre-generated buffer with no LLM call; exit 3
    # (empty buffer) tells the workflow to fall back to live generation.
    if GEN_MODE == "dequeue":
        sys.exit(dequeue_to(OUT_MANIFEST))
    if GEN_MODE == "record":
        sys.exit(record_perf(_ARGV))
    main()
