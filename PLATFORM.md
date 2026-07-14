# PLATFORM.md — making the page addictive (the 8-idea build) + the paid-tier plan

Goal: not "a page that posts science facts" (a commodity) but a page people
**follow and binge**, addictive in *both* how the video is displayed and the
content inside. Everything below is free for now; the paid plan at the bottom is
what we turn on once the platforms show traction.

## The 8 ideas — status

| # | Idea | Status | How |
|---|------|--------|-----|
| 1 | Signature persona + one ownable lens | **BUILT** | `PAGE_IDENTITY` in generate.py — "Stranger Than It Sounds": a calm, precise, quietly-eerie narrator revealing ordinary reality is far weirder than it looks. Baked into every script. |
| 6 | Mystery/story structure (not a list) | **BUILT** | "ADDICTIVE CRAFT" prompt block: open loop → tension → reveal; each scene makes you need the next. |
| 8 | Question hooks the brain can't ignore | **BUILT** | Prompt now pushes concrete question-hooks the viewer auto-answers in their head. |
| 7 | Emotional range across the page | **BUILT** | Per-video `EMOTIONAL REGISTER` (awe / unsettling / beautiful / darkly funny) so the page isn't monotone. |
| 2 | Serialized loops / follow-hook | **PARTIAL** | Endings now "leave the page open" (a resonant thought implying a whole world of this, no follow/save command). NEXT: turn on explicit SERIES mode + next-episode teases + cross-video callbacks for true binge chains. |
| 4 | Sound design | **BUILT (v1)** | Signature intro sting (ffmpeg-generated, subtle, gated on profile `sfx`). NEXT: optional soft ambient bed matched to topic; a scene-change whoosh (only if it reads well — annoyance risk). |
| 3 | Real archival / scientific footage | **BUILT** | Four free sources now chain in `_gather_candidates`: Pexels → NASA → **Wikimedia Commons** (video + archival stills; Hubble/microscopy/diagrams/historical, no key) → **Internet Archive** (public-domain documentary film, no key, size-capped at 45 MB). Plus Openverse CC stills in the archival-still fallback. This is the biggest "we don't look like everyone else" lever and it's live + network-tested. NEXT (optional): Pixabay (free key) for more volume on common queries. |
| 5 | Generated data-viz / diagram scenes | **DEFERRED** | A clean animated scale-comparison/counter for the key number *could* help, but the user just had the number-overlay removed for clutter — so this only ships if it's clearly elegant, not busy. Low priority. |

Also live (earlier work) and part of "addictive": whisper-synced captions,
scientist-brain research stage (each scene a different real fact, no repetition),
deeper free voice, no lingering overlays, natural sentence pacing.

## Why the free `GEMINI_API_KEY` matters for all of this

The persona + mystery + research all run through the LLM. Groq's tiny free
budget rate-limits mid-generation, which drops the pipeline to a degraded
fallback (repetitive, un-gated). Gemini's free tier (~1500 req/day) makes the
whole creative engine run reliably AND lets us batch a backlog. It's the single
free step with the most leverage. (aistudio.google.com → key → repo secret
`GEMINI_API_KEY`.)

## The binge architecture (idea 2, full version — next)

What makes someone spend 10 minutes on the page:
1. **Series** — numbered, themed runs ("Things happening in your body right now
   #4") so there's always a "next one." SERIES mode already exists in the code;
   we activate it and rotate a few series.
2. **Cross-video callbacks** — "remember the ocean-floor one? this is why…" —
   builds a connected universe that rewards watching many.
3. **A consistent cold-open + signature sound** (sound-design sting = the audio
   half) so the format is instantly recognizable in the feed.

---

## FUTURE: the paid-tier / subscription plan (turn on after traction)

Kept free until the platforms show real traction. When they do, in priority of
impact-per-dollar:

1. **ElevenLabs (~$5/mo)** — the deep intelligent voice + exact word timings
   (removes the whisper step). Biggest quality-per-dollar jump. ~$5 → the
   channel's flagship voice.
2. **Gemini / Groq paid tier (a few $)** — reliable generation at any hour +
   true batch rendering (weeks of videos in one run). Unlocks volume.
3. **Pixabay/Storyblocks or a stock subscription** — premium, less-common
   footage for a more distinct look, if the free archival sources aren't enough.
4. **Buffer paid (~$6/mo)** — a real 2-week+ multi-channel queue (free caps ~10
   posts/channel); needed once posting cadence is high.

### And the channel's OWN subscription (how the page earns recurring revenue)

The endgame isn't just spending on tools — it's the audience paying us:
- **A paid newsletter / membership** (the funnel in MONETIZATION.md leads here):
  the free weekly "Stranger Than It Sounds" email builds the list; a paid tier
  ($3-5/mo) offers the deep-dive versions, the sources, an ad-free archive, or
  early access. Recurring, owned, platform-proof.
- **Platform subscriptions** once eligible: YouTube channel memberships, TikTok
  subscriptions — same content-quality bar unlocks them.
- Sequence: free videos → email list → affiliate + sponsors → paid membership.
  The quality work in this repo is what makes every one of those convert.

The rule stays: spend only after a platform proves the content converts; the
whole pipeline is built so that day is a switch-flip, not a rebuild.
