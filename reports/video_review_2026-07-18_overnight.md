# Video review + overnight quality batch — 2026-07-18

## Render 105 reviewed — "The Cosmic Proof of Relativity in Your Pocket"
Topic: muon time dilation (physics). 40.8s. Run 29627399572, sha f9ead7e.

**Provider / access levers — all confirmed firing (first render actually
spending the paid Gemini key):**
- `[model] using gemini:gemini-flash-latest` — Gemini carried generation.
- `[research] grounded on live Google Search` → 9 dossier angles.
- `[vision] Gemini picked clip …` on 3 scenes (all 8/10). Imagen did not fire —
  Pexels covered all 6 scenes, so the MAX_AI_IMAGES cost cap spent nothing.

**Verdict: solid B / B+.** Watched all 16 frames.
- + Strong topic; train-motion-blur clip is a great time-dilation metaphor with a
  clean gold DILATION keyword pop; gorgeous sunrise-over-clouds ending (resonant,
  not a command); captions synced; overall brightness fine (YAVG 74.8).
- − One ~2s **near-black scene** (scene 3, "scientist laboratory equipment") — a
  white caption sitting on a black frame reads like a glitch.
- − **Keyword "einstein time dilation"** — cold jargon, lowercased; it names the
  concept instead of explaining it. The hook was a flat statement, so the
  curiosity-gap validator failed 3× ("no '?' in first four lines") and the run
  **shipped a 7.33 near-miss** (below the 7.5 clean bar) with a known-redundant
  scene 8 as last-resort fallback.
- − Roman-ruins aerial lingered ~5s (a 7.9s scene loops one clip).

## Root-cause found: a CI bug was hiding the real generation
The branch showed a stale "Deep Time" manifest, which looked like a duplicate
generation. It wasn't — `git add memory_*.json manifest.json … queue_*` aborts
**atomically** when `queue_*` matches nothing (the empty-buffer live-gen case),
so the freshly generated manifest AND `memory_science.json` (used-fact / domain /
hook-frame dedup history) never committed. Topic-diversity memory was silently
frozen for every live render. Fixed by splitting the always-present paths onto
their own `git add` (render.yml + buffer.yml).

## What shipped tonight (branch `claude/epic-edison-jybjd1`, 97 zero-quota checks)
Each flaw above → a concrete fix, plus reach for more wow/variety:

1. **CI staging bug** — memory/manifest now persist from live renders (topic
   diversity restored).
2. **Brightness** — `_clip_luma` samples across ~8s and rejects a near-black
   *stretch*; dim-but-real footage is **lifted** (`_shadow_lift_filter`, capped
   gamma/brightness, unit-tested) rather than rejected → no black-screen frames,
   and science footage (space/deep-sea/night) is kept instead of collapsing into
   text cards.
3. **Prompt** — the early-question rule is now mechanical (mirror of validate():
   a '?' in the first four lines) with a statement-hook + question-scene-2 pattern
   so drafts pass first try; keyword must be plain search words (jargon banned).
4. **Pacing** — scene floor 6 → 7 (ceiling 10) → shorter scenes, more distinct
   clips, no 8-second linger.
5. **Creativity/relevance** — +2 hook frames (SCALE_SHOCK, COMPARISON_COLLISION);
   vision judge given scoring bands (0-3 when nothing matches → re-search) + a
   penalty for text/watermark/cartoon/3D thumbnails.
6. **Topics** — deduped 5 twin facts (same topic, different IDs — they defeated
   the diversity memory), then added 18 verified "leaves-you-thinking" facts in
   thin domains. **91 → 104 facts across 20 domains.**

## Still needs a render to verify (do first, then WATCH)
The brightness lift, scene-floor pacing, prompt, and new topics are logic-safe
and unit-tested but not yet seen on screen. Trigger one render after the 07:00
UTC reset, confirm `[grade] lifting dim clip …` where relevant, confirm ≥7
scenes with no lingering clip, and check that the hook opens a real question and
the keyword reads plain.

## Not done (deferred, with reasons)
- **Within-scene B-roll cutaway** ("use more videos"): the scene-floor bump
  already delivers more clips per video, so this became low-marginal-value and
  render-risky. Revisit only if linger reappears.
- **Multi-word phrase captions**: still blocked on ASS WrapStyle 2 + wide font;
  needs a real render to tune, best paired with a font-size change.
