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

## The standing loop
I'm continuing to render, watch, and improve on a timer, asking "how else can I
improve this" after each pass. When you wake: skim the newest few drafts, and if
you have any analytics at all, run `--record` on them so the system starts
learning your audience.
