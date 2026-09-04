# Overnight Quality Control Addendum — 2026-09-04 00:21–00:59 CT

This addendum extends `engineering/OVERNIGHT_QUALITY_CONTROL.md` and is the canonical continuation handoff for the next hourly run.

## LIVE STATE VERIFIED THIS RUN
- `origin/main`: `6a045e50a33408ecafdfa21c9ff951d731347bd9` — unchanged.
- Claude Writer V2.1 base: `claude/writer-v2-traceability-repair-01` @ `2256f229be0c5b245cb5c1a2ec7cd4b0d8b3c2e6` — unchanged.
- Quality-stack integration: `superchad/quality-stack-integration-01` @ `9eb299fa19e0de51c905f39ff3f561d39192b986` — unchanged.
- SuperChad takeover latest known write: `332569563babf81f9ce9546f8b8d634ea86dedfe`; re-read live branch head before next write.
- PR #56 remains takeover -> Claude Writer V2.1 base, NOT main.
- No merge, deploy, render, publish, cron/live-delivery change, or paid-provider call. Known spend remains $0.

## CI FINDINGS + FIXES THIS HOUR
Run `33837971247` exposed one story-shape diagnostic defect: reworded versions of the same narrative grammar could score too different. The guard itself was retained. Fix `00db83c96f505096c1b931710e1ac4786ca78f1a` added observation/reversal/consequence recognition and better narrative-function priority. The same-grammar >=0.70 test then passed in the next CI.

Run `33840336089` subsequently proved the story-shape fix worked: legacy `1503/1503`, semantic 28, quality signals 18, editorial 17, manifest 21, repair regression 20, pairwise, torture corpus, and ALL story-shape/first-8-second tests passed. The only failure moved forward to the brand-new hook-surface suite.

Exact new failure: a correct, highly specific first-frame visual — `stomach lining epithelial cells regenerating close up` — was flagged as not anchored to the hook because the first metric used Jaccard overlap. Extra useful visual detail inflated the union and reduced the score. That creates the wrong incentive: specificity should not be punished.

Fix `332569563babf81f9ce9546f8b8d634ea86dedfe` changes first-frame anchoring from broad Jaccard to subject-token containment:
- one real shared subject token (e.g. `stomach`) establishes anchoring;
- additional specific visible nouns (`lining`, `epithelial`, `cells`) do not dilute that anchor;
- generic-only first frames remain separately flagged;
- a visually specific frame with zero shared subject tokens still warns as unanchored.

The test threshold/intent was NOT weakened. CI for `3325695...` had not appeared yet at checkpoint time; verify first next run.

## NEW ZERO-SPEND QUALITY LAYER — HOOK SURFACES + PAYOFF PROOF
`writer_v21_hook_payoff.py` + `tests/test_writer_v21_hook_payoff.py` now treat four opening surfaces as separate jobs:
1. spoken hook;
2. profile/cover headline;
3. first on-screen hook text;
4. first-frame visual.

They surface duplicate copy, generic/missing first frames, and subject misalignment. Payoff proof records hook/opening overlap, causal/reversal resolution cues, generic AI payoff patterns, lack of connection to the opening reason-to-stay, and endings that simply open another question. All output remains `gating=False`.

## BAKEOFF REPORTING ADVANCED
`wr21_takeover_bakeoff.py` at `523dd47e690c572f7cb1e81a486fbfc172cc8a80` now reports semantic/mechanical integrity, floor state, scorer-vs-critic disagreement, editorial information-gain warnings, story shape, first-eight-second exposure, repair regression, blind pairwise plans, payoff proof, and final hook-surface separation. It remains script-only: no render/publish/memory/queue writes and no automatic pairwise provider call.

## CREATIVE FINDING THIS HOUR
Two useful principles are now encoded in tests rather than prose:
- **Different wording is not a different story shape.** Structural diversity must survive paraphrase.
- **Specificity is not irrelevance.** A first-frame visual should retain the hook's literal subject while becoming more visually concrete; the metric must reward `stomach -> stomach lining epithelial cells`, not prefer vague token-matched wallpaper.

## PROMOTION STATUS
HOLD. No genuinely postable, floor-clearing Writer V2.1 script has yet been demonstrated under the final combined stack. Full certification render remains NOT EARNED.

## NEXT EXACT ACTION
1. Re-read takeover branch head and verify CI triggered by/after `332569563babf81f9ce9546f8b8d634ea86dedfe`. If red, fix the exact guard without lowering it.
2. Add a zero-network syntax/import preflight for `wr21_takeover_bakeoff.py` so reporting-path breakage cannot hide behind unit suites that never import it.
3. Build PRE-RENDER VISUAL FEASIBILITY telemetry: every important beat must name a specific visible subject/mechanism/action; flag generic lab/space/person-thinking wallpaper and abstract non-showable intentions before asset acquisition.
4. Wire visual-feasibility output into the corrected torture runner.
5. Only after zero-network CI is fully green, check secret-backed Groq availability once. If quota is available, run ONE corrected five-topic panel through the combined stack; do not repeatedly burn quota under contention.
6. Human-read every live script. Multiple fact-clean, floor-clearing, genuinely postable outputs are required for promotion.
7. Build structured failure-learning records + promotion evidence packet from the live panel's observed outcomes, not guessed labels.
