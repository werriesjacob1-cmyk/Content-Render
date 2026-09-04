# Content Render — Overnight Quality Control

Updated: 2026-09-03 23:44 America/Chicago

## NORTH STAR
Repeatedly produce science shorts a strong human creator would actually post and that can compete on TikTok/Reels/Shorts. Green CI is necessary, not success.

Optimize for: first 1–1.5s curiosity without lying; information gain every beat; natural spoken syntax; genuine treatment diversity; specific/showable science; authentic evidence; purposeful visual pattern interrupts; clear mechanism/scale; a specific visual+story payoff; replay/share/save/comment value; strong voice/pacing/sound; low AI smell. Abort weak content rather than ship it.

## HARD BOUNDARIES
Jacob is final authority. Overnight: NO merge to main, deploy, publish, cron/live delivery, material spend, or full video render. Human review remains mandatory.

## STATEFUL HOURLY LOOP
`Content Render Overnight Control` runs hourly at :19 from 00:19 through 08:19 CT (9 runs). Every run MUST:
1. read this file first;
2. re-check live main + active branch SHAs;
3. continue NEXT EXACT ACTION rather than restarting solved work;
4. update this file with concrete changes/tests/blockers/next action;
5. if quota blocks live calls, keep advancing zero-quota engineering/creative/integration work.

## LIVE SHAS / BRANCHES
- main: `6a045e50a33408ecafdfa21c9ff951d731347bd9` — unchanged through takeover.
- Claude final Writer V2.1: `claude/writer-v2-traceability-repair-01` @ `2256f229be0c5b245cb5c1a2ec7cd4b0d8b3c2e6`.
- SuperChad Writer takeover: `superchad/writer-v2-semantic-failclosed-01` @ `7a7baffbd90cc08f95ceca3b09507becfdb4df5f`.
- Draft PR #56: takeover branch -> Claude V2.1 branch (NOT main).
- Quality-stack integration: `superchad/quality-stack-integration-01` @ last verified `9eb299fa19e0de51c905f39ff3f561d39192b986`.
- Durable control: `superchad/overnight-quality-control-01`.

## CLAUDE HANDOFF — INHERITED TRUTH
Claude V2.1 @ `2256f22` has hard/soft traceability, semantic claim-support, tiered targeted repair, stall detection, GPT-OSS low-reasoning/3000-token truncation fix, and the production quality-floor fix. 1503 zero-quota checks passed. Honest live promotion status: HOLD; after correcting Claude's own floor bug, zero genuinely floor-clearing accepted scripts existed. Prior five-topic evidence was contaminated by Groq 200k/day quota exhaustion/critic failures.

Canonical torture topics: `stomach_lining`, `neutron_star_spoon`, `mauna_kea`, `chess_possible_games`, `mantis_shrimp`.

## CLOSED P0 #1 — SEMANTIC CRITIC FAIL-OPEN
Audit proved critic outage could become `critic_verdict=None -> [] semantic violations` and make verifier failure look factual-clean.

Takeover files:
- `writer_v21_semantic_gate.py`
- `writer_v21_orchestrator.py`

New behavior:
- complete semantic verdict required for hook + each beat + payoff;
- missing/duplicate/out-of-range/unknown claim-support fails closed;
- unsupported/contradicted requires named proposition;
- provider outage is verifier outage, not fake script defect;
- candidate selectable only with semantic verification;
- one GLOBAL semantic retry max per candidate run, spent only when no known hard/validate defect already dictates repair;
- malformed critic cannot drive creative repair;
- quality floor still load-bearing;
- worst-case structured-call ceiling 7.

Proof: PR #56 run `33836749680` SUCCESS; legacy 1503/0 + 28 new semantic checks.

## SCORER / CRITIC DISAGREEMENT TELEMETRY — IMPLEMENTED, NON-GATING
Finding: legacy `score_script()` and V2 critic both currently use temperature 0.7. Current selection makes legacy overall primary and critic craft average only a <=0.3 tie-breaker. This plausibly explains live score volatility (e.g. stomach-lining dimensions swinging after a local repair).

`writer_v21_quality_signals.py` now records apples-to-apples hook/escalation/payoff/clarity deltas, critic craft average, disagreement band, low human-craft dimensions, and whether legacy-score winner vs critic-craft winner differ. `gating=False`; thresholds/selection unchanged pending live evidence. 18 focused checks pass.

## RETENTION / EDITORIAL DIAGNOSTICS — IMPLEMENTED, NON-GATING
Fresh official TikTok/YouTube/Meta guidance was used only for broad principles: opening seconds matter, maintain curiosity/value/momentum, native vertical visual movement, purposeful sound, clear visual hierarchy.

`writer_v21_editorial_diagnostics.py` surfaces:
- beat information gain;
- premise repetition;
- payoff echoing hook;
- overlong written-sounding sentences;
- monotone cadence;
- generic AI moralizing/fortune-cookie endings;
- generic/missing visual intent;
- adjacent visual repetition;
- explicit human stomach-test questions.
No fake virality probability; `gating=False`. 17 focused checks pass.

## CLOSED P0 #2 — V2 HOOK + PAYOFF WERE NOT SPOKEN
Verified production-path defect:
- Claude `assemble_manifest_v2()` put only six middle beats into `scenes`;
- hook/payoff remained top-level metadata;
- `main.py` synthesizes narration from `m['scenes'][*]['voiceover']` only;
- therefore V2 could optimize/score/fact-check hook/payoff that viewers would never hear, and first/last hero-shot logic would target the wrong material.

Fix:
- `writer_v21_manifest.py`: scene1 hook -> six treatment beats -> final payoff = 8 spoken scenes; exact source claim IDs move with each line; script rebuilt from all scenes; hook/payoff get distinct deterministic visual queries when possible.
- `writer_v21_runtime.py`: composes corrected assembly with fail-closed orchestrator without rewriting large Claude modules.
- `wr21_run.py`: corrected live entrypoint.

Proof at head `1e8d65576d430332820b487cc06b7a7c74568382`, run `33837378476` SUCCESS:
- legacy 1503/0;
- semantic 28 checks;
- scorer telemetry 18;
- editorial diagnostics 17;
- spoken manifest 21.
1587 explicit zero-network checks, all green.

## REPAIR-REGRESSION TELEMETRY — IMPLEMENTED, CI PENDING
Current head `7a7baffbd90cc08f95ceca3b09507becfdb4df5f`.
New:
- `writer_v21_repair_regression.py`
- `tests/test_writer_v21_repair_regression.py`

It compares consecutive repair rounds without changing selection and preserves exact before/after lines. Flags:
- hook/payoff inflation after repair;
- newly introduced generic AI moralizing;
- increased low-information/repetition/long-written-sentence warnings;
- critic craft drop;
- legacy score drop;
- worsening scorer-vs-critic disagreement;
- text changed outside declared target beats.
The exact Claude failure shape (short visceral stomach hook -> long hedged clinical hook) is a regression fixture. A weak always-true test assertion was caught and removed before CI.

Workflow run `33837656200` is currently in progress. FIRST ACTION next hour: inspect/fix this run before anything else.

## CORRECTED LIVE TORTURE RUNNER — READY, NOT YET RUN
- `wr21_takeover_bakeoff.py`
- `wr21_run.py`
Same five topics, 60s pacing, no render/publish/memory writes, no duplicate research call just for reporting. Uses semantic fail-closed + bounded retry + true quality floors + spoken hook/beats/payoff. Prints full scripts, every round, semantic coverage, hard/soft violations, repair plans, scorer/critic disagreement, acceptance/abort.

Earlier live runs are NOT promotion evidence for this final combined stack.

## QUALITY STACK FOR LATER PROMOTION — DO NOT USE TO MASK WEAK WRITING
Separate integration lane already contains/adapts grounded evidence/claims, Visual Director, NASA SVS/PubChem, RCSB, deterministic science motion, Gemini/Qwen vision QA, still-first generation, verified-still -> I2V, modern T2V lab, model-promotion controller, video repair, Voice Lab 2.0, restrained Sound Brain, holistic final-video QA, preflight, human-review readiness.

Writer V2.1 must produce multiple genuinely postable scripts before convergence/certification.

## CREATIVE REVIEW QUESTIONS — APPLY TO EVERY LIVE CANDIDATE
- Does 0–1.5s create a specific unanswered need-to-know?
- Does scene 2 escalate rather than merely set up/explain?
- Does every beat add a new fact/mechanism/scale/reversal?
- Does it sound like a smart human speaking aloud?
- Is the treatment structurally different from adjacent videos?
- Can each beat be shown with a specific real/mechanistic visual?
- Are visual changes purposeful pattern interrupts, not noise?
- Does payoff specifically answer/reframe opening instead of moralizing?
- Is there a natural save/share/comment reason without forced CTA?
- Would a strong human science creator post this exact script?

## NEXT EXACT ACTION
1. Inspect workflow run `33837656200` for head `7a7baff...`. If red, diagnose/fix repair-regression implementation/tests before proceeding. If green, record exact check count.
2. FREEZE further Writer architecture changes unless another proven P0 correctness/render-contract bug appears. We now need evidence, not endless redesign.
3. Check whether secret-backed Groq quota is actually available. If available, run the corrected five-topic panel through `wr21_run.py`/manual branch diagnostic; ruthlessly read all five scripts and analyze:
   - factual/semantic verification;
   - true floor pass;
   - scorer vs critic disagreement;
   - editorial diagnostics;
   - repair regression;
   - human postability.
4. If quota is unavailable, do NOT idle. Advance zero-quota V2.1 -> quality-stack compatibility and pre-production visual plans for the five canonical topics, but do not infer script promotion.
5. Promotion requires multiple factual-clean, floor-clearing scripts a human editor would actually post. Only then converge into the quality stack and consider asking Jacob for one certification-only render.

## APPROVAL / SPEND
- main untouched; no merge/deploy/publish.
- SuperChad takeover known spend: $0.
- full video render: NOT EARNED.
