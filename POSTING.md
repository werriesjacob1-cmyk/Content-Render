# POSTING.md — from rendered video to a live post

This repo renders and packages video only. It does **not** post anything, and
no publishing credentials live in this repo. This document is the factual
handoff: what the pipeline hands you each run, and the two supported ways to
turn that into a scheduled post, so you can wire up whichever one you prefer.

## What each run produces (in `out/`, uploaded as a GitHub Actions artifact)

| File | Platform(s) |
|---|---|
| `tiktok_reels_shorts.mp4` | TikTok, Instagram Reels (usually — see `platforms.json`) |
| `instagram_reels.mp4` | Instagram Reels, only if it ever needed a different fix than the TikTok cut |
| `youtube_shorts.mp4` | YouTube Shorts |
| `facebook_reels.mp4` | Facebook Reels |
| `square.mp4` | X / Facebook feed / Instagram feed (1:1) |
| `landscape.mp4` | X / YouTube landscape (16:9) |
| `final.mp4` | the 1080x1920 master (all cuts derive from this) |
| `post.json` | title, captions, hashtags, `video_id`, `cta_style` |
| `platforms.json` | file map **+ ffprobe compliance report** per platform (resolution/duration/codec/size checked against `PLATFORM_SPECS` in `repackage.py`, with any auto-fixes applied logged) |
| `platform_text.json` | per-platform caption/title text, AI-content disclosure guidance, and a posting-time heuristic — see below |

`platform_text.json` is the field you want for a publisher/scheduler: each
platform key (`tiktok`, `instagram_reels`, `instagram_feed`, `facebook_reels`,
`youtube_shorts`, `x_twitter`) carries its own `caption` (or `title`+
`description` for YouTube), the `file` to upload, an `ai_disclosure` object,
and an `optimal_post_time` object. Captions are deliberately varied per
platform (not copy-pasted) to avoid cross-platform duplicate-content
penalties, and are truncated to each platform's real character limit
(X's 280-char cap is enforced in code, not just assumed).

## AI-content disclosure — read this before publishing

`platform_text.json`'s `ai_disclosure` block documents, per platform:
`likely_required` (with reasoning), the platform's native disclosure toggle
and where to find it, and a `suggested_disclosure_line` you can drop into a
caption on platforms with no native toggle.

Researched against each platform's 2026 policy: this channel's format — an
AI-written script, an AI (ElevenLabs/edge-tts) voice reading it, over **real**
stock footage, with no synthetic human likeness and no voice clone of a real
identifiable person — currently falls in the *exempt* bucket under TikTok's
and YouTube's own published exceptions (AI voiceover over stock footage,
faceless AI-scripted content, and AI-written scripts/captions are explicitly
excluded from their mandatory-label requirements), and Meta's mandatory
AI-disclosure checkbox is scoped to *advertisers* in Ads Manager, not organic
posts. **`recommended` is still `true` on every platform** — these policies
move fast, a mislabel risks a channel strike, and disclosure costs nothing.
Where a platform offers a voluntary "AI info" / disclosure toggle, turn it on.
This is a heuristic to revisit each time a platform updates its synthetic-
media policy, not legal advice.

## Optimal posting time — also a heuristic

`optimal_post_time` in each platform's metadata is a generic, well-documented
best-practice window (e.g. TikTok Tue-Thu 7-9pm), **not personalized** to
this channel's real audience — there is no analytics history yet.
`generate.py` already has a `perf_<page>.json` scaffold (see the comment
block near the top of that file) for feeding real per-video engagement data
back into generation once you have some; the same file should eventually
replace these generic windows with account-specific ones. Until then, treat
them as a reasonable starting default, not a guarantee.

## Two supported paths to an actual post

Pick ONE. Both start from the same GitHub Actions artifact; neither requires
storing publishing credentials in this repo.

### Path A — Buffer via GitHub Releases + Zapier (RECOMMENDED, and wired)

Every successful render now also publishes a **GitHub Release** (the
"Publish video as a GitHub Release" step in `render.yml`), tagged with the
run's `video_id`, with all the platform cuts + `post.json` /
`platforms.json` / `platform_text.json` attached as assets. That gives each
video a **stable public URL** with no extra storage account and no new
secret. Buffer can pull a video from a link, so the fully-automatic path is:

**GitHub Release → Zapier → Buffer → your channels.** One-time setup:

1. **Connect your channels in Buffer** — TikTok, Instagram, Facebook,
   YouTube, X (see account-type requirements below). This is where you log
   into each platform; no credentials ever touch this repo.
2. **Create a free Zapier account** and build one Zap:
   - **Trigger:** GitHub → *New Release* → repo `werriesjacob1-cmyk/content-render`.
   - **Action:** Buffer → *Add to Queue* (a.k.a. Create Post). Map the release's
     video asset URL to the media field, and the per-channel caption/title from
     the attached `platform_text.json` to each channel's text. Add each Buffer
     channel you want this to fan out to.
3. **Enable AI-content disclosure** per channel in Buffer / the platform (see
   the AI-disclosure section above; a `suggested_disclosure_line` ships in the
   metadata as a fallback).
4. **Set the schedule** in Buffer using `optimal_post_time` as a starting point,
   then refine once real analytics exist.

After this one-time setup, every daily render auto-publishes a Release, Zapier
catches it, and Buffer queues it to all connected channels — hands-off.

#### Per-platform captions + cuts (recommended — do NOT cross-post identically)

Posting the identical video + caption everywhere suppresses reach. Each render
already produces a DIFFERENT caption and the correct video cut per platform, and
every Release now carries them in a Zapier-friendly form. To route each channel
its own content, build the Zap with **one Buffer action per channel** instead of
one action fanning out:

1. **Trigger:** GitHub → *New Release* (repo `content-render`).
2. For each platform's caption, add a **Formatter by Zapier → Text → Extract
   Pattern** step (Formatter is free, no premium plan needed). Input = the
   release **Body** from the trigger. Pattern (regex):
   - TikTok: `===TIKTOK_START===([\s\S]*?)===TIKTOK_END===`
   - Instagram: `===INSTAGRAM_START===([\s\S]*?)===INSTAGRAM_END===`
   - Facebook: `===FACEBOOK_START===([\s\S]*?)===FACEBOOK_END===`
   - (YouTube title/desc and X use their own `===YOUTUBE_TITLE_…===`, `===X_…===` markers if you add those channels.)
3. **One Buffer *Add to Queue* action per channel**, each mapping:
   - **TikTok** → media URL `…/releases/download/{{tag}}/tiktok_reels_shorts.mp4`, text = TikTok Formatter output.
   - **Instagram** → media URL `…/releases/download/{{tag}}/tiktok_reels_shorts.mp4` (IG Reels uses the same 9:16 cut), text = Instagram Formatter output.
   - **Facebook** → media URL `…/releases/download/{{tag}}/facebook_reels.mp4` (captions raised out of FB's UI), text = Facebook Formatter output.
   `{{tag}}` is the release tag from the trigger (the video_id). The exact filename→channel mapping is also listed in plain text at the bottom of every release body.

This gives each platform its own optimized caption and correctly-formatted cut
from a single render, fully automatically. (`platform_text.json` is still
attached to every release too, if you'd rather pull structured JSON via a
premium Webhooks/Code step instead of the free Formatter approach.)

> Note: if you'd rather not use Zapier, Buffer also has native Google
> Drive/Dropbox folder integrations — you'd instead add a workflow step that
> drops the cuts into that cloud folder. The Release+Zapier path above is
> recommended because it needs no extra storage account.

### Path B — the existing n8n webhook

`render.yml` already POSTs a `{"status", "run_url"}` payload to
`secrets.N8N_WEBHOOK_URL` at the end of every run (the "Notify n8n" step).
Today that payload is just a status ping — extending it to carry the actual
`post.json`/`platform_text.json` content (or a link to the run's artifact) is
the next step if you want n8n itself to drive publishing via its native
TikTok/Meta/YouTube/X nodes. That extension is not implemented here (it
requires you to design the n8n flow and connect n8n's own OAuth
integrations for each platform) — this doc just confirms the webhook hook
point already exists and where in `render.yml` to extend the payload.

## What you must supply per platform (either path)

- **TikTok**: a TikTok **Business or Creator** account (personal accounts
  can't be scheduled by third-party tools). Direct-API posting instead of a
  scheduler requires a TikTok developer app that has passed **content
  posting API audit**.
- **Instagram**: an Instagram **Professional (Business or Creator)** account,
  linked to a Facebook Page. Direct-API posting requires a Meta developer app
  with the `instagram_content_publish` permission, which requires **Meta App
  Review**.
- **Facebook**: a Facebook **Page** (not a personal profile). Direct-API
  posting requires a Meta developer app with page-publish permission (same
  App Review track as Instagram).
- **YouTube**: a YouTube channel + (for direct API only) a Google Cloud
  project with the **YouTube Data API v3** enabled and an OAuth consent
  screen — verified if you exceed Google's unverified-app quota.
- **X/Twitter**: an X account; direct-API posting requires an X **developer
  app** on a paid tier (Basic or higher) for media upload via the v2 API.
- **Every platform**: enable that platform's AI-content disclosure wherever
  it's offered (see the AI-disclosure section above) — whichever path you
  use, the toggle lives in the destination app or the scheduler's per-post
  settings, not in this repo.

No credentials of any kind are stored in this repository. Whichever path you
choose, its credentials belong in that tool's own secure storage (the
scheduler's connected-accounts vault, or n8n's credential store) — not as
GitHub Actions secrets for this repo unless you're driving direct API calls
from a new workflow step you add yourself.
