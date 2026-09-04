# Content Render Overnight Quality Control

Last updated: 2026-09-03 23:22 America/Chicago

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
- SuperChad Writer V2.1 takeover branch: `superchad/writer-v2-semantic-failclosed-01` @ `2f17c23e09d66960c4013fb3c630221586f0dca2`
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

Critical remaining flaw proven by direct source audit:
`generate_candidate_v2()` currently treats a failed/missing critic as `critic_verdict=None`, then `derive_semantic_violations(None, ...)` returns an empty list. This allows semantic verification failure to look like "zero semantic violations". That is a fail-open factual-integrity gap and MUST be closed before another promotion run.

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

## CURRENT HOUR — WORK COMPLETED
1. Created stateful hourly automation `Content Render Overnight Control` at :19 each hour.
2. Automation is instructed to read/update THIS FILE every run so each hour inherits exact prior context rather than restarting.
3. Created takeover branch from Claude's exact final Writer V2.1 SHA.
4. Audited `generate_candidate_v2()` and confirmed semantic critic fail-open path.
5. Added `writer_v21_semantic_gate.py` on takeover branch with:
   - complete hook + every beat + payoff semantic-coverage validation;
   - accepted live fallback-shape normalization through existing V2.1 normalizer;
   - missing/duplicate/out-of-range/unknown verdict fail-closed behavior;
   - required unsupported_proposition for unsupported/contradicted verdicts;
   - bounded retry primitive;
   - explicit SemanticCoverageFailure sentinel so provider outage is not mislabeled as a script hallucination.

## OPEN BLOCKERS / QUESTIONS
1. Integrate semantic fail-closed primitive into `generate_candidate_v2()` without inflating the existing 5-call network bound uncontrollably.
2. Decide exact bounded critic retry budget under quota pressure. Preferred: one normal critic attempt + at most one compact retry, but total V2 calls must remain controlled and measured.
3. Add zero-quota tests proving:
   - critic outage cannot accept a candidate;
   - partial claim_support coverage cannot accept;
   - malformed fallback shape cannot accept;
   - valid full coverage still allows supported candidates;
   - semantic unsupported claim still blocks;
   - retry can recover from one malformed/outage response;
   - no hidden quality-floor bypass returns.
4. Independently audit score_script reliability because stomach_lining's hook/payoff scores swung 6->2 after only the hook changed. Determine whether scoring variance can make candidate selection unstable.
5. Preserve stronger earlier prose when later factual repair becomes hedged/clinical; add explicit craft-regression protection if necessary.
6. After quota availability, run one corrected five-topic panel with all fixes simultaneously active. Do NOT call earlier runs promotion evidence.
7. Only after multiple genuinely postable scripts exist should V2.1 be promoted into the quality-stack integration branch or a certification-only MP4 be prepared.

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
Patch `generate_candidate_v2()` on `superchad/writer-v2-semantic-failclosed-01` so semantic verification is load-bearing:
- a candidate cannot enter the selectable candidate pool unless semantic coverage is complete and valid;
- critic unavailable/malformed after bounded retry => candidate ineligible and explicit debug reason;
- do not silently convert provider outage into zero violations;
- preserve bounded network behavior;
- add targeted regression tests and run the zero-quota suite before any live calls.

After that, independently audit the quality scorer/candidate-ranking stability before spending quota on the corrected five-topic panel.

## APPROVAL / SPEND STATUS
- Merge approval required: NO action requested yet.
- Deploy/publish approval required: not applicable; forbidden overnight.
- Paid spend: $0 known for current SuperChad work.
- Full render: NOT EARNED yet.
