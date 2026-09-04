# Overnight Quality Control Addendum — 2026-09-04 00:21–00:55 CT

This addendum extends `engineering/OVERNIGHT_QUALITY_CONTROL.md` and is the canonical continuation handoff for the next hourly run.

## LIVE STATE VERIFIED THIS RUN
- `origin/main`: `6a045e50a33408ecafdfa21c9ff951d731347bd9` — unchanged.
- Claude Writer V2.1 base: `claude/writer-v2-traceability-repair-01` @ `2256f229be0c5b245cb5c1a2ec7cd4b0d8b3c2e6` — unchanged.
- Quality-stack integration: `superchad/quality-stack-integration-01` @ `9eb299fa19e0de51c905f39ff3f561d39192b986` — unchanged.
- SuperChad takeover advanced through `523dd47e690c572f7cb1e81a486fbfc172cc8a80`; re-read live head before any next write because CI-triggering commits may advance it.
- PR #56 remains takeover -> Claude V2.1 base, NOT main.
- No merge, deploy, render, publish, cron/live-delivery change, or paid-provider call. Known spend remains $0.

## CI FINDING + FIX
The previously pending run `33837880251` was cancelled by a newer push, not a failure. The authoritative newer run `33837971247` on head `947fa44c...` failed exactly one new test after all legacy and prior takeover suites passed:

`tests/test_writer_v21_story_shape.py::test_same_story_grammar_scores_high_even_with_rewording`

The failure was valuable: the story-shape diagnostic under-recognized lexical rewordings of the same narrative grammar. It could therefore overstate treatment diversity.

Fix committed as `00db83c96f505096c1b931710e1ac4786ca78f1a` WITHOUT lowering the >=0.70 similarity expectation:
- added an `observation` narrative function for signal/reading/anomaly openings;
- expanded reversal detection to catch reversed/reversal/broke-the-idea phrasing;
- expanded consequence/reframe detection to catch changed/forced/reframed language;
- reordered primary-function priority so a payoff such as “the evidence forced a new interpretation” is classified by its narrative consequence rather than merely the word “evidence.”

This preserves the purpose of the test: different wording must not masquerade as a different story shape.

## NEW ZERO-SPEND QUALITY LAYER — HOOK SURFACES + PAYOFF PROOF
Implemented `writer_v21_hook_payoff.py` at commit `c6912bfb357c30445912e6005f7b4b4c08280533` and tests at `160d9b8c83fadc385dd56eaa8e569c83f69f4a6c`.

Non-gating diagnostics now explicitly treat four surfaces as separate jobs:
1. spoken hook;
2. profile/cover headline;
3. first on-screen hook text;
4. first-frame visual.

Telemetry catches:
- cover merely repeating the spoken hook;
- on-screen text merely repeating spoken/cover copy;
- generic first frames such as “science laboratory cinematic footage”;
- first-frame visuals not anchored to the hook’s actual subject.

Payoff proof now records:
- hook/payoff overlap;
- opening-question/payoff overlap;
- explicit resolution cues such as causal/reversal language;
- generic AI payoff patterns (including the observed mantis-shrimp “danger hides in plain sight” shape);
- payoff that opens a new question instead of resolving/reframing the reason the viewer stayed.

All output is `gating=False`; no new arbitrary promotion threshold was introduced.

Workflow updated at `74af3c1ea41c6445b38318f6e877c60f50e2820c` to run the new tests. Latest observed Actions run for that head was `33840336089`, IN PROGRESS at checkpoint time. Read its final result first next run.

## BAKEOFF REPORTING ADVANCED
`wr21_takeover_bakeoff.py` updated at `523dd47e690c572f7cb1e81a486fbfc172cc8a80` so corrected live attempts will now print:
- semantic/mechanical integrity;
- true floor state;
- scorer-vs-critic disagreement;
- editorial/information-gain diagnostics;
- story shape + first-eight-second exposure;
- repair regression;
- blind pairwise plans;
- payoff-proof warnings per round;
- final manifest hook-surface separation and payoff proof if accepted.

No pairwise-provider calls were added to the runner; pairwise prompts remain prepared evidence only unless deliberately invoked later. No extra render/publish path exists.

## CREATIVE FINDING THIS HOUR
A useful emerging principle is now mechanical enough to test: **“different treatment” and “different hook wording” are not diversity.** We need different narrative FUNCTION progressions, and the four opening surfaces should compound curiosity instead of saying the same sentence four ways. Likewise a dramatic final sentence is not a payoff unless it visibly resolves/reframes the opening reason-to-stay.

## PROMOTION STATUS
HOLD. No genuinely postable, floor-clearing Writer V2.1 script has yet been demonstrated under the final semantic-failclosed + spoken-hook/payoff + current diagnostics stack. Full certification render is NOT earned.

## NEXT EXACT ACTION
1. Re-read takeover branch head and final result of latest CI (starting with run `33840336089` if still authoritative). If red, fix the exact guard without weakening it.
2. If green, syntax/preflight-check the updated `wr21_takeover_bakeoff.py` path in CI or a zero-network test because the reporting file changed after the current workflow trigger.
3. Add the next deterministic zero-spend layer: PRE-RENDER VISUAL FEASIBILITY. Require every important beat to name a specific visible subject/mechanism/action and identify generic lab/space/person-thinking wallpaper before asset acquisition.
4. Wire visual-feasibility output into the corrected torture runner.
5. Only after all zero-network gates are green, check secret-backed Groq availability once. If quota is available, run ONE corrected five-topic panel with the combined stack. Do not repeatedly burn quota under contention.
6. Read every live script as a human. Promotion requires multiple factual-clean, floor-clearing scripts that are actually postable, not merely green telemetry.
7. Build structured failure-learning records + promotion packet from observed live evidence after that panel, not guessed outcomes.
