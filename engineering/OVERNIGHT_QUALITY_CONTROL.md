# Content Render Overnight Quality Control

Last updated: 2026-09-03 23:27 America/Chicago

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
- origin/main: `6a045e50a33408ecafdfa21c9ff951d731347bd9` (verified 2026-09-03 23:19 CT)
- Claude final Writer V2.1 branch: `claude/writer-v2-traceability-repair-01` @ `2256f229be0c5b245cb5c1a2ec7cd4b0d8b3c2e6`
- SuperChad Writer V2.1 takeover branch: `superchad/writer-v2-semantic-failclosed-01` @ `857b86d5a314b4bc762859a7643f367772512fb2`
- Writer takeover draft PR: #56, base = Claude V2.1 branch, NOT main
- Quality-stack integration branch: `superchad/quality-stack-integration-01` @ `9eb299fa19e0de51c905f39ff3f561d39192b986`
- Durable control branch: `superchad/overnight-quality-control-01`

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
- honest current promotion result: HOLD, zero genuinely floor-clearing accepted live scripts after correcting the acceptance bug;
- live bakeoff was contaminated by Groq 200k/day quota exhaustion and critic failures.

## BLOCKER CLOSED THIS HOUR — SEMANTIC CRITIC FAIL-OPEN
Direct audit confirmed Claude's `generate_candidate_v2()` treated critic failure as `critic_verdict=None`, then `derive_semantic_violations(None, ...)` returned `[]`, which could make verifier outage look like factual cleanliness.

Takeover implementation on `superchad/writer-v2-semantic-failclosed-01`:
- `writer_v21_semantic_gate.py` requires complete hook + every beat + payoff semantic coverage;
- accepts live-observed fallback response shapes only after coverage validation;
- missing/duplicate/out-of-range/unknown verdicts fail closed;
- unsupported/contradicted verdicts require an explicit unsupported proposition;
- provider outage is represented as verifier outage, NOT a fake script provenance defect;
- `writer_v21_orchestrator.py` extracts the V2.1 loop without rewriting the 4k-line `generate.py`;
- candidate selection requires semantic_verified=True;
- one GLOBAL semantic retry maximum across the entire candidate run;
- retry is spent only when no known mechanical/validate defect already dictates repair;
- malformed critic responses cannot drive creative repair;
- quality floors remain load-bearing;
- worst-case structured invocation ceiling is explicit at 7 (Claude's prior loop = 6).

Proof:
- PR #56 CI run `33836749680`: SUCCESS.
- Existing suite: `1503 passed, 0 failed`.
- New adversarial semantic suite: `28 checks`, all passing.
- Proved critic outage cannot accept a mechanically clean high-score candidate.
- Proved partial semantic coverage cannot accept.
- Proved one malformed response can recover with exactly one bounded retry.
- Proved clean semantic coverage cannot bypass creative quality floors.

## QUALITY STACK ALREADY AVAILABLE
The separate integration lane contains or has adapters for:
- grounded evidence / claim registry;
- Writer V2.1 compatibility;
- Visual Director / scene routing;
- NASA SVS + PubChem authentic science media;
- RCSB molecular structures;
- deterministic science motion;
- Gemini/Qwen asset vision QA;
- current still-generation lab;
- verified-still -> image-to-video lab;
- current text-to-video lab;
- generated-media promotion controller;
- constrained video repair;
- Voice Lab 2.0 (Edge, Orpheus, Cartesia Sonic 3.6, Eleven v3);
- restrained Sound Brain;
- holistic final-video multimodal QA;
- capability preflight / zero-spend planning;
- human-review readiness gate.

These remain experimental/draft and must not be used to compensate for a weak script.

## NEW FINDING — SCORER INSTABILITY RISK
`score_script()` is a single LLM self-score call over hook/surprise/escalation/payoff/rewatch/clarity/coherence, with overall recomputed as an arithmetic mean. The provider path uses temperature 0.7. Writer V2.1's structured critic also currently uses temperature 0.7.

This is a plausible mechanism for Claude's live stomach_lining observation where hook/payoff scores swung 6 -> 2 after only a limited hook repair. Current candidate selection uses legacy score as PRIMARY and critic craft average only as a tie-breaker when scores are within 0.3. Therefore a stochastic score jump/drop >0.3 can dominate even if critic craft opinion disagrees.

Do NOT lower or rewrite thresholds yet. Instrument disagreement first.

## OPEN BLOCKERS / QUESTIONS
1. Add zero-cost score/critic disagreement telemetry on every V2.1 round.
2. Quantify whether current `score_script` winner and critic-craft winner diverge on the corrected live five-topic panel.
3. Preserve stronger earlier prose when later factual repair becomes hedged/clinical; use disagreement/regression evidence before changing selection.
4. Decide whether promotion should eventually require a dual-signal craft floor or robust combined ranking. No change until evidence exists.
5. After quota availability, run one corrected five-topic panel with all fixes simultaneously active. Do NOT call earlier runs promotion evidence.
6. Only after multiple genuinely postable scripts exist should V2.1 be promoted into the quality-stack integration branch or a certification-only MP4 be prepared.

## CREATIVE QUALITY QUESTIONS TO ANSWER OVERNIGHT
Do not let engineering consume the whole mission. Continue asking:
- Does the hook create a specific unanswered question within 1.5 seconds?
- Does each beat add a new fact/mechanism/scale/turn rather than rephrasing the premise?
- Is the spoken syntax something a smart human would actually say aloud?
- Does the treatment create a genuinely different narrative shape?
- Can every important beat be shown visually with specificity?
- Is there a visual pattern interrupt every few seconds for a reason, not as noise?
- Does the payoff answer the opening and give the viewer a satisfying reframe?
- Is there a natural reason to save/share/comment rather than a forced CTA?
- Does any line sound like generic AI cleverness, motivational filler, or "danger hides in plain sight" copy?

## NEXT EXACT ACTION
Implement a PURE, non-gating quality-signal diagnostic on `superchad/writer-v2-semantic-failclosed-01`:
- compare apples-to-apples dimensions between legacy score_script and V2.1 critic (hook, escalation, payoff, clarity);
- record legacy overall, critic average, mean/max mapped disagreement, and a diagnostic disagreement band;
- surface when the current legacy-score winner would differ from the critic-craft winner;
- add to each round's debug output;
- add zero-network tests;
- do NOT change acceptance thresholds or selection rule yet.

Then prepare the corrected five-topic bakeoff script to call the fail-closed orchestrator. Live execution waits only on actual quota availability, not on more architecture work.

## APPROVAL / SPEND STATUS
- Merge approval required: NO action requested yet.
- Deploy/publish approval required: not applicable; forbidden overnight.
- Paid spend: $0 known for current SuperChad work.
- Full render: NOT EARNED yet.
