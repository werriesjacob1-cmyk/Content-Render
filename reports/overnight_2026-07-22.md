# Overnight work — 2026-07-22 (while you slept)

Worked the render → watch → improve loop autonomously. Everything below is
**merged to `main`** (live for the daily crons) and passes the 102-check
zero-quota suite. Frugal on Gemini — a handful of cheap free-first renders.

## Your #1 complaint: choppy narrator / "behind the subtitles"
Diagnosed the audio pipeline. The voice is a single continuous ElevenLabs read
sliced at word boundaries and re-joined sample-accurately — so it's NOT clipped.
The choppy feel came from two things, both fixed:
- **Captions ran ahead of the voice.** They were placed at ElevenLabs' raw word
  onset, which lands a hair before the ear hears the word. Added a **110ms
  caption lead-in delay** (`CAPTION_DELAY_MS`) so words appear *with* the voice.
  → **This one needs your ears to confirm** — tell me if it's better, worse, or
  needs more/less than 110ms.
- **Scripts read as clipped fragments.** Added a hard "flowing sentences, not
  fragments" prompt rule with examples, so the narrator talks in real sentences.

## Fixed: videos were rendering too SHORT (~28–32s)
Root cause: the 74–88 word target + 60-word floor were tuned for the old free
voice; **ElevenLabs speaks faster**, so low-word scripts came out a stubby
~28s. Raised the floor: **word range now 80–100 (target 84–96)** → ~38–44s, the
watch-time sweet spot. This was hurting every short render.

## Built: the analytics feedback loop you asked about
Honest limitation first: I can't silently scrape TikTok/YouTube analytics — that
needs their APIs wired with your OAuth, which only you can authorize. But the
learning machine is now real and waiting for data:
- The generator already biases topic/ending selection by `perf_<page>.json`.
  I extended it to **also weight hook openings** (the biggest retention lever).
- Added **`python generate.py --record <video_id> views=.. watch=0.63 follows=..
  shares=..`** — paste in a video's numbers and generation starts favoring the
  topics/hooks/endings that actually held viewers on YOUR page. No dashboard
  needed to start; it's the same mechanism a future auto-pull would feed.
- **To go fully automatic later:** the cleanest path is the YouTube Data API
  (public view/like counts by video id, no OAuth) → a small script that maps your
  posted Shorts back to their `video_id` and calls `--record`. TikTok has no open
  analytics API, so it'd stay manual or need a paid provider. Say the word and I'll
  build the YouTube puller.

## Still open (need you / a render to confirm)
- **Caption-delay by ear** — the one subjective call I can't make from frames.
- **Occasional cartoon clip** — a craft-paper "Earth" illustration slipped into
  one render; the vision judge usually catches these but not always. On my list.
- **Zapier/Publer** — you'll finish the media-id mapping; the video-upload path is
  proven (Publer Upload Media → Create Post, Save as Draft).

## BIG finding (part 2 of the night): two FREE resources ran dry at once
I rendered again to verify the length fix and watched render 130 ("Pineapple:
The Fruit That Digests You"). Footage was great (A−: clean, on-topic, varied),
but it came out **31s, robotic-voiced, and the script was weak** (scored 6.83/10,
surprise 4 — it explained the bromelain enzyme as "it contains protein," which is
muddled). Digging into the run log, this was NOT a code bug — **two free
resources hit their limits on the same night:**

1. **ElevenLabs is out of credits.** `HTTP 401 quota_exceeded — "You have 102
   credits remaining, 228 required."` The free plan is 10k credits/month and
   they're spent (the test posts + all the renders ate them). So **every render
   now falls back to Piper**, the local robotic voice — which is exactly the
   "choppy narrator" you flagged. ElevenLabs won't come back until the monthly
   reset.
2. **OpenRouter killed its free Llama-70b.** `HTTP 404 — "This model is
   unavailable for free."` That was our strongest free script model. Generation
   now falls to `github:gpt-4o-mini`, which is too weak — it overshoots the word
   count then trims to mush, and shipped the 6.83 near-miss.

### What I changed tonight (both free/cheap, both shipped + tested, 109 checks)
- **Voice: edge-tts now comes BEFORE Piper.** edge-tts uses Microsoft's Azure
  *neural* voices — free, unlimited, and clearly smoother/less robotic than
  Piper. Piper stays as the offline safety net so a render never breaks. edge's
  slightly slower cadence should also push the 31s stub toward ~38s. **This
  needs your ears** — you can force either voice per render with the new
  `VOICE_ENGINE` env (`edge` = new default, `piper` = old). Tell me which sounds
  better and I'll lock it.
- **Script: a frugal Gemini "quality-rescue."** When the free models can only
  manage a weak draft (below the clean bar, like tonight's 6.83), the system now
  spends **one** grounded Gemini attempt to rescue it before shipping-weak or
  aborting. It fires *only* on weak nights — on nights the free models write a
  clean script, Gemini isn't touched ($0). This is the "use some Gemini credits
  but be frugal" trade: pennies, and only when they buy back a genuinely-good
  video. Your ~$10 covers this for months.

### The honest bottom line
The pipeline was quietly running on its *weakest* fallbacks for both voice and
script — that's why quality dipped. The two fixes make it degrade *gracefully*
instead: a smooth free neural voice, and paid-Gemini rescue that only kicks in
when the free tier can't deliver. **The real fix for volume + top-tier voice is
still a cheap paid tier** (ElevenLabs ~$5/mo, or an OpenRouter/Gemini balance for
scripts) — but these changes keep quality up on free until you decide.

## The standing loop
I'm continuing to render, watch, and improve, asking "how else can I improve
this" after each pass. When you wake: skim the newest few drafts, tell me which
voice sounds right (`edge` vs `piper`), and if you have any analytics at all, run
`--record` on them so the system starts learning your audience.
