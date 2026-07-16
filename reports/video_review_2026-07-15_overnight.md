# Overnight render→watch→improve loop — 2026-07-15 (session log)

Autonomous loop on branch `claude/epic-edison-jybjd1`. Goal: 3–5 consistently
post-worthy, addictive science videos across different domains, improving each
render before the next (never re-render without a concrete change).

## Videos produced (watched frame-by-frame + scored)

| # | Run | Title | Domain | Length | Verdict | Notes |
|---|-----|-------|--------|--------|---------|-------|
| 2 | 66 | The Hidden Social Life of Forests | plants | 49s | B+ | great topic; hook opened on a literal Dubai **city** (metaphor hijack) — fixed after |
| 3 | 67 | The Sound That Broke the World (Krakatoa) | physics | 53s | A− | brutal specifics; **command ending** "send this to a friend" — fixed after |
| 4 | 68 | The Hidden Giant of Oregon (honey fungus) | fungi | 47s | A−/B+ | vivid footage, non-command question ending; a touch long |
| 5 | 69 | The Hawaiian Conveyor Belt | geology | **40s** | **A/A−** | fingernail-macro hook, sunset-horizon LOOP ending; pace nailed |

**Post-worthy streak: renders 3, 4, 5 (physics, fungi, geology) — different
domains, all A−/A.** Render 6 (caption polish) in flight.

## Provider reality (honest)
The daily free quotas (reset 2 AM CT) were largely spent by the day's ~13
sibling-session renders, so `gemini-2.0-flash` was 429 by evening. Generation
was unblocked by adding **`gemini-2.0-flash-lite`** — a SEPARATE free daily
bucket that the day's renders hadn't touched. `gemini-2.5-flash` is now dead
(404 "no longer available to new users") and was removed.

## Improvements shipped this session (each tested; 59/59 unit tests pass)
1. **Fast-fail when throttled** — wall-clock budget + circuit-aware backoff
   skip; a fully-throttled run aborts in seconds instead of grinding ~10 min.
2. **Zero-quota test suite** (`tests/test_pipeline.py`) — caption alignment,
   footage diversification, timing, `validate()` across 5 topics. Caught a real
   `validate()` false-positive (good astronomy scripts like "243 vs 225 Earth
   days" wrongly aborted as "contradictory numbers") — fixed.
3. **Footage anchoring** — the judge/requery now lead with the scene's
   `search_query` subject, not the metaphor-laden voiceover, so a hook like
   "a trip through a city" can't pull a literal city over a forest video. This
   single fix visibly lifted footage relevance from render 67 onward.
4. **No command endings** — dropped the SHARE cta_style (its "send this to a
   friend" ending is the exact command the rubric bans); hardened the guard to
   reject send/tag/share phrasings. Endings are now resonant payoff / rewatch
   loop / genuine question.
5. **Pace to ~40s** — narration `-12% → -5%` (keeps dense scripts, just speaks
   them a touch faster; whisper re-aligns captions) + word cap 112→100. Render
   69 landed at exactly 40.0s.
6. **Caption polish** — fold short function words into an adjacent content word
   so a lone "THE"/"TO"/"INTO" never gets its own caption frame (render 6+).
7. **Topic bank 70 → 91 facts, 19 domains** — added materials/weather/deep_time/
   history/geology/senses + high-wow facts (more trees than Milky Way stars,
   sharks older than trees, the pistol shrimp's sun-hot snap, the 20-watt brain,
   octopus 3 hearts, Sahara feeding the Amazon, glass-rain exoplanet, …). The
   Hawaii video (render 69) came straight from these additions.

## Still open / next levers
- Multi-word phrase captions (blocked on WrapStyle: 2 / no-wrap + wide font —
  would need a font-size or wrap change, best verified with a real render).
- Occasional slightly-dark ocean/space clips (a min-brightness footage filter
  could help).
- Keep accumulating different-domain topics; consider the series/binge idea.
