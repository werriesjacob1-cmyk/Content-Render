# Content Render Overnight Quality Control

Last updated: 2026-09-03 23:38 America/Chicago

## NORTH STAR
Build a science-video system that repeatedly produces short-form videos a strong human creator would actually post and that can compete on TikTok, Reels, and Shorts.

Success is NOT green CI or more APIs. Success means:
- a first 1–1.5 seconds that creates a real curiosity gap without lying;
- natural spoken writing with increasing information gain every beat;
- structural variety across videos rather than one repeated AI narrative grammar;
- factual claims mechanically/semantically grounded in real evidence;
- visuals that show the actual subject/mechanism/scale rather than wallpaper B-roll;
- authentic scientific assets when they exist;
- deterministic explanatory motion when code is clearer than footage;
- generated still/video only when reality cannot show the idea, with independent vision QA;
- excellent pacing, narration, captions, restrained sound, and a satisfying visual+story payoff;
- low AI smell and high watch/replay/share/save/comment potential;
- consistency over cadence: aborting weak content is success.

## SAFETY / AUTHORITY BOUNDARIES
Jacob is final authority.
Do NOT merge to main, deploy, publish, enable cron/live delivery, or materially increase spend without explicit Jacob approval.
Do NOT trigger a full certification video unless the script has earned it and the current checkpoint says certification is the next safe step.
Human review remains mandatory before posting.

## LIVE REPOSITORY STATE
- origin/main: `6a045e50a33408ecafdfa21c9ff951d731347bd9` — unchanged throughout takeover work.
- Claude final Writer V2.1 branch: `claude/writer-v2-traceability-repair-01` @ `2256f229be0c5b245cb5c1a2ec7cd4b0d8b3c2e6`
- SuperChad Writer V2.1 takeover branch: `superchad/writer-v2-semantic-failclosed-01` @ `1e8d65576d430332820b487cc06b7a7c74568382`
- Writer takeover draft PR: #56, base = Claude V2.1 branch, NOT main
- Quality-stack integration branch: `superchad/quality-stack-integration-01` @ `9eb299fa19e0de51c905f39ff3f561d39192b986`
- Durable control branch: `superchad/overnight-quality-control-01`

## HOURLY CONTROL LOOP
Automation `Content Render Overnight Control` is stateful and bounded through the morning:
- runs at :19 every hour from 00:19 through 08:19 CT;
- FIRST reads this checkpoint and treats it as the canonical prior-hour handoff;
- re-verifies live main + active branch SHAs;
- continues this file's NEXT EXACT ACTION rather than restarting;
- updates this checkpoint after each run;
- if provider quota blocks live work, advances zero-quota engineering/creative diagnostics instead of idling.

## CLAUDE HANDOFF — AUTHORITATIVE FINDINGS
Writer V2.1 at `2256f22`:
- hard/soft traceability split implemented;
- hard checks: claim IDs, numbers/units, strong named entities, uncited substantive beats;
- old broad unsupported-term word-overlap reduced to soft telemetry;
- semantic claim_support critic detects unsupported additions/contradictions with ordinary words;
- repair priority: factual integrity -> validate() failures -> creative craft;
- stall detection present;
- Groq GPT-OSS reasoning budget/truncation fixed with low reasoning + 3000 max tokens;
- quality-floor bypass fixed in final commit `2256f22`;
- 1503 zero-quota checks passed;
- honest promotion status inherited from Claude: HOLD; zero genuinely floor-clearing accepted live scripts after correcting his own acceptance bug;
- prior live panel was contaminated by Groq 200k/day quota exhaustion and critic failures.

## CLOSED P0 #1 — SEMANTIC CRITIC FAIL-OPEN
Direct audit proved Claude's loop could treat critic outage as zero semantic violations.

Takeover implementation:
- `writer_v21_semantic_gate.py`
- `writer_v21_orchestrator.py`

Rules now:
- complete semantic verdict required for hook + every middle beat + payoff;
- missing/duplicate/out-of-range/unknown claim_support fails closed;
- live fallback response shapes tolerated only if full coverage remains valid;
- unsupported/contradicted verdict requires an explicit proposition;
- provider outage is verifier outage, not a fake script factual defect;
- candidate cannot be selectable unless `semantic_verified=True`;
- one GLOBAL semantic retry maximum per candidate run;
- retry spent only when no existing mechanical/validate defect already dictates repair;
- malformed critic response cannot drive a creative rewrite;
- quality floor remains load-bearing;
- worst-case structured invocation ceiling = 7.

Proof:
- PR #56 initial semantic CI run `33836749680`: SUCCESS.
- Legacy suite remained 1503/0.
- 28 semantic adversarial checks pass.

## NON-GATING SCORER / CRITIC DISAGREEMENT TELEMETRY
Finding:
- legacy `score_script()` is one LLM self-score call and provider path uses temperature 0.7;
- V2.1 structured critic also currently uses temperature 0.7;
- current selection makes legacy overall PRIMARY and critic craft average only a <=0.3 tie-breaker.
This is a plausible cause of the live stomach_lining 6->2 dimension swing after a local repair.

Implemented `writer_v21_quality_signals.py`:
- apples-to-apples hook/escalation/payoff/clarity deltas;
- legacy overall vs critic craft average;
- LOW/MODERATE/SEVERE disagreement telemetry;
- exact low critic dimensions for spoken naturalness / AI smell / visual tellability;
- reports whether legacy-score winner and critic-craft winner would be different rounds;
- strictly `gating=False` — NO threshold or selection change yet.

18 focused checks pass.

## NON-GATING RETENTION / EDITORIAL DIAGNOSTICS
Fresh current platform guidance was reviewed before implementation: prioritize the opening seconds, maintain curiosity/value/momentum, vertical motion, purposeful sound, and clear visual hierarchy. These principles are encoded as evidence/diagnostics, NOT a fake virality score.

Implemented `writer_v21_editorial_diagnostics.py`:
- beat-to-beat information-gain telemetry;
- adjacent premise repetition;
- payoff echoing hook;
- overly long written-sounding lines;
- monotone sentence rhythm;
- generic AI moralizing / fortune-cookie ending warnings;
- generic or missing visual intent;
- adjacent visual-subject repetition;
- explicit human stomach-test questions.
All non-gating.

17 focused checks pass.

## CLOSED P0 #2 — V2 HOOK + PAYOFF WERE NOT SPOKEN
This was found by tracing writer assembly into the production renderer.

Verified defect:
- Claude V2.1 `writer_v2.assemble_manifest_v2()` stored hook/payoff at top level but built `scenes` ONLY from treatment middle beats.
- `main.py` builds the narration audio from `m['scenes'][*]['voiceover']` ONLY.
- Therefore V2 could optimize/score/fact-check a great hook and payoff that the viewer would never hear.
- Existing render architecture also assumes the first scene is the hook and final scene is payoff for hero-shot prioritization.

Takeover fix:
- `writer_v21_manifest.py`
  - scene 1 = hook;
  - scenes 2..N+1 = six treatment beats;
  - final scene = payoff;
  - claim IDs preserved on exact spoken scene;
  - script rebuilt from every spoken scene;
  - hook/payoff get distinct deterministic visual queries when possible;
  - six-beat treatment => eight spoken scenes, inside existing production scene windows.
- `writer_v21_runtime.py` composes corrected assembly with fail-closed orchestration in the isolated experiment without rewriting Claude's large source modules.
- `wr21_run.py` routes the corrected live torture panel through this composed runtime.

21 focused manifest/render-contract checks pass.

## COMPLETE TAKEOVER CI — CURRENT VERIFIED GREEN
Head: `1e8d65576d430332820b487cc06b7a7c74568382`
PR #56 workflow run: `33837378476` — SUCCESS.
Evidence from logs:
- legacy pipeline: `1503 passed, 0 failed`
- semantic fail-closed suite: `28 checks` PASS
- scorer/critic telemetry suite: `18 checks` PASS
- retention/editorial diagnostics suite: `17 checks` PASS
- spoken hook/payoff manifest suite: `21 checks` PASS
Total explicit zero-network checks across these suites: 1587, all green.

## CORRECTED LIVE TORTURE RUNNER READY
`wr21_takeover_bakeoff.py` + entrypoint `wr21_run.py`:
- exact same five comparable topics: stomach_lining, neutron_star_spoon, mauna_kea, chess_possible_games, mantis_shrimp;
- NO render/publish/memory/queue writes;
- no duplicate research call merely to print evidence;
- uses fail-closed takeover orchestrator + corrected spoken manifest;
- logs all rounds, semantic coverage, floors, critic support, hard/soft violations, repair plans, score-vs-critic disagreement, full text, acceptance/abort;
- 60s inter-topic pacing retained.
Live execution still depends on secret-backed workflow/quota availability; do not waste calls under a known-open quota circuit.

## QUALITY STACK ALREADY AVAILABLE FOR LATER PROMOTION
Separate integration lane contains/adapts:
- grounded evidence / claim registry;
- Writer V2.1 compatibility;
- Visual Director / scene routing;
- NASA SVS + PubChem;
- RCSB molecular structures;
- deterministic science motion;
- Gemini/Qwen asset vision QA;
- still-first generation lab;
- verified-still -> image-to-video lab;
- current text-to-video lab;
- generated-media promotion controller;
- constrained video repair;
- Voice Lab 2.0 (Edge, Orpheus, Cartesia Sonic 3.6, Eleven v3);
- restrained Sound Brain;
- holistic final-video multimodal QA;
- capability preflight / zero-spend planning;
- human-review readiness gate.
Do NOT use this stack to compensate for a weak script. V2.1 must earn promotion first.

## OPEN BLOCKERS / QUESTIONS
1. Repair-regression protection: factual repair can still make a once-good line hedged/clinical/less watchable. Instrument round-to-round craft/editorial regression before changing selection rules.
2. Current scorer and critic both use temperature 0.7. Do NOT change temperature or thresholds yet; corrected live disagreement evidence comes first.
3. Corrected five-topic live panel has never run with ALL of these simultaneously:
   - Claude hard/soft semantic design,
   - claim-support parser fixes,
   - quality-floor fix,
   - semantic fail-closed coverage,
   - bounded semantic retry,
   - spoken hook/payoff manifest.
4. No genuinely postable, floor-clearing V2.1 script has yet been demonstrated under that final combined stack.
5. Full video certification remains NOT EARNED.

## CREATIVE QUALITY QUESTIONS TO ANSWER ON EVERY LIVE SCRIPT
- Does the first 1–1.5 seconds create a specific unanswered need-to-know?
- Does scene 2 escalate rather than explain/setup?
- Does every beat add a new fact/mechanism/scale/reversal?
- Does the syntax sound like a smart human speaking rather than an article/LLM?
- Is the treatment genuinely structurally different from adjacent videos?
- Can every beat be shown with a specific subject/mechanism?
- Are visual changes purposeful pattern interrupts rather than random flashing?
- Does the payoff specifically answer/reframe the opening rather than moralize?
- Is there a natural reason to save/share/comment without a forced CTA?
- Would a strong human science creator actually post this exact script?

## NEXT EXACT ACTION
Build PURE round-to-round repair-regression telemetry on the Writer takeover branch, without changing selection:
- compare before/after repaired beat text and editorial diagnostics;
- flag hook/payoff word inflation after repair;
- flag newly introduced generic AI moralizing;
- flag lower information gain / higher repetition after repair;
- flag critic craft average decline and score-vs-critic disagreement movement;
- preserve exact before/after lines in diagnostics;
- add zero-network tests;
- keep `gating=False` until corrected live evidence shows whether selection policy needs to change.

Then:
A) if secret-backed Groq quota is available, run `wr21_run.py` through branch_recon/manual diagnostics and ruthlessly read all five scripts;
B) if quota is still unavailable, continue zero-quota V2.1-to-quality-stack compatibility and pre-production visual planning; do not idle and do not invent acceptance evidence.

## APPROVAL / SPEND STATUS
- Merge: no approval requested; forbidden overnight.
- Deploy/publish: forbidden overnight.
- Paid spend from SuperChad takeover: $0 known.
- Full render: NOT EARNED.
