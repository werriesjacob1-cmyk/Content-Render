# Content Render — Canonical Master TODO

Last updated: 2026-09-08
Owner of final decisions: Jacob
Durable audit branch: `superchad/system-audit-backlog-20260908`

This is the **master project backlog**. It is broader than the tactical flagship checklist. Nothing may be silently dropped simply because the current mission is narrower.

Status legend:
- `[x]` complete / evidence decision closed
- `[~]` partial / in progress / proven only for one lane
- `[ ]` not yet complete
- `[D]` deliberately deferred until prerequisite evidence exists

## STANDING RULE P1 — Every substantial prompt must advance 1–5 master-backlog items

This is a load-bearing operating rule for Content Render.

Every substantial engineering, research, audit, experiment, or execution prompt sent to Claude, SUPERCHAD, Codex, or another implementation agent must preserve the immediate premise/objective of that prompt **and also deliberately target between one and five IDs from this canonical backlog**.

The purpose is to make each work cycle produce compound progress instead of solving one isolated symptom at a time.

### Prompt construction requirements

1. **Name the backlog IDs explicitly near the top.** Example: `BACKLOG TARGETS: C8, S2, A8`.
2. **One primary mission, up to four compatible secondary objectives.** The original premise of the prompt remains the primary objective unless Jacob explicitly changes it.
3. **Do not stuff five unrelated items into a mission.** Target only items that share code, evidence, runtime boundaries, or can be advanced safely in the same workstream. One excellent closure is better than five shallow checkboxes.
4. **Bias toward closure, not activity.** Each targeted item should have a concrete exit criterion: implemented + tested, empirically disproved, explicitly deferred with evidence, or blocked by a named irreversible boundary.
5. **Exploit adjacency.** When the agent is already touching a component, it should inspect and, when safe, close related backlog items rather than creating another future mission for trivial adjacent work.
6. **If the primary path becomes blocked, remain productive.** Without violating scope/safety, pivot to the highest-value nonblocked secondary target(s) already named in the prompt instead of idling.
7. **Preserve quality and safety invariants.** Never weaken factual/semantic/quality gates, publishing containment, spend controls, or merge authorization merely to close more TODOs.
8. **Use broad agent autonomy.** State objectives/invariants and let the capable agent choose implementation details, subagents, model tier, tests, and internal sequencing.
9. **Return an item-by-item evidence packet.** For every targeted backlog ID, report one of: `COMPLETE`, `PARTIAL`, `DISPROVED/SUPERSEDED`, `BLOCKED`, with evidence/SHA/tests and the remaining gap.
10. **Update this master TODO after the mission.** Tactical checklists never replace this file. Newly discovered systemic work is added here with a new ID or mapped to an existing one before the next major prompt.

### Productivity target

Default to **2–4 compatible backlog targets per substantial prompt**. Use one when the work is unusually high-risk/deep; use five only when the items are genuinely coupled. The measure of productivity is not number of files changed or TODO boxes touched—it is durable reduction in unresolved product risk and faster progress toward a genuinely post-worthy autonomous video factory.

---

## Immediate execution gate

- [~] PR #73 — Writer V2.1 runtime-contract recovery + rejection replay. Final reviewed head `0136d663d6aa7630c210adc8a844000bff15c1be`; exact-head CI green; waiting for Jacob merge authorization.
- [ ] If merged: verify resulting actual `main` SHA and actual-main CI.
- [ ] Separate Jacob authorization for one bounded private `topic=auto` flagship run.
- [ ] Obtain and human-review the actual private MP4 before any publishing decision.

---

## Claude Top 10 — retain all

### C1 — Re-evaluate Writer length windows
`[D]`
Do not widen merely because Gemini overshoots. PR #73 fixes the previously hidden runtime length contract first. Reassess only after paid/live evidence shows excellent scripts naturally need a different window.

### C2 — Offline Writer replay harness from real rejected drafts
`[x]`
Implemented on PR #73 as `writer_replay.py` with regressions. Real corpus quantified: 13 attempts / 36 rounds; 17/36 length-family failures.

### C3 — Remove single-provider fragility
`[~]`
Gemini is currently funded and usable, but the factory is not yet robustly multi-provider at equivalent quality. Full provider resilience remains open.

### C4 — Compact Writer prompt / safely recover Groq eligibility
`[ ]`
Not complete. Current evidence says large dynamic evidence payloads remain important. Compact only where semantics/provenance stay intact; Groq compatibility is a bonus, not the objective.

### C5 — Skip structurally impossible Groq calls
`[~]`
Done for the **private flagship certification lane** on PR #73 using estimated prompt + actual 3000-token structured completion reserve against the known 8k TPM envelope. Unattended production routing remains unchanged.

### C6 — Repair-budget starvation
`[x]` evidence decision closed; no broad repair-budget change justified.
Real corpus disproved the original primary-starvation hypothesis: only 2/36 rounds were Tier-1 clean, while 33/36 repair plans were legitimately provenance-first. Do not add repair rounds without new evidence.

### C7 — Remove Writer prompt contradictions / improve craft failures
`[~]`
PR #73 fixes the hidden runtime word contract and makes scene-1 statement vs later curiosity-question unambiguous at the final runtime instruction boundary. It also reinforces distinct beats, jargon translation, concrete payoff, no fake interrogatives, and spoken register. Needs paid/live validation.

### C8 — Exercise downstream render / visual / audio / QA stack with known-good manifest
`[ ]`
Still open. Five flagship attempts have not yet proven the full new downstream factory. This is one of the highest-priority next technical jobs.

### C9 — Add writability to topic selection
`[ ]`
Not implemented. Must become part of topic × treatment fit rather than a standalone simplistic score.

### C10 — Update `CLAUDE.md` and provider/control-plane docs
`[ ]`
Still materially stale. Must reflect paid Gemini reality, PR #72/#73 state, private-vs-production architecture, provider status, and current authority model.

---

## SUPERCHAD Top 10 — retain all

### S1 — Topic × Treatment joint intelligence
`[ ]`
Locally score topic-treatment combinations for hook potential, distinct-beat availability, jargon burden, evidence richness, payoff strength, visual potential, duration fit, and recent repetition. Zero extra LLM calls by default.

### S2 — Persistent append-only failure / attempt / certification learning ledger
`[ ]`
Separate durable learning from 14-entry operational memory. Record topic, treatment, defects, repairs, provider, QA, human verdict, and outcome; feed back only compact relevant lessons.

### S3 — Audience Intelligence shadow mode
`[~]` research done; implementation not done.
Use audience signals such as questions, misconceptions, search/outlier interest, and discussion language to measure demand/curiosity. Must never become factual evidence.

### S4 — Human Preference Evaluation
`[~]` framework defined conceptually; system not implemented.
Durably capture `definitely post / probably post / borderline / reject` plus reasons and use that as the real product-quality optimization target.

### S5 — Per-video Visual Continuity Contract / visual bible
`[ ]`
Define recurring subjects, source families, style/camera language, typography, scale conventions, approved references/keyframes, and cross-scene continuity checks.

### S6 — Explicit Visual Intent before asset search
`[ ]`
Each scene should have a visual job such as demonstrate, reveal, compare, orient, establish scale, show consequence, or reset—not merely a search phrase derived from narration.

### S7 — Premium visual escalation lane
`[ ]`
Add Higgsfield or equivalent only after authentic science / real footage / deterministic graphics fail scene intent. Require references, caching, hard spend limits, bounded retries, and QA.

### S8 — Finished-video certified reserve / manufacturing queue
`[ ]`
Move Delivery Guarantee from a script queue to multiple finished, certified, fresh MP4s available ahead of posting slots.

### S9 — Provider capability + cost + health router
`[~]`
PR #73 adds one capability-aware Groq guard in private certification. Full router still needs task type, request size, quality history, provider health, cooldown, latency, and cost.

### S10 — Champion/challenger manufacturing experiments
`[~]`
`writer_replay.py` is foundational, but full promotion experiments across Writer, selector, visual planner, repair policy, and audience-aware ranking remain open. Promote only on measured quality improvement.

---

## Additional Full-System Audit Items — retain all

### A1 — Converge private certification and unattended production
`[ ]`
After Writer V2.1 earns private promotion, deliberately cut daily production to the same promoted Writer/quality architecture. Current unattended production still uses legacy generation logic.

### A2 — Queue versioning / migration at Writer cutover
`[ ]`
Prevent legacy queued manifests from silently entering the V2.1 production factory. Add writer/certification version compatibility or deliberately flush incompatible queue inventory.

### A3 — Separate operational recent-memory from durable learning memory
`[ ]`
Keep lightweight recent-dedup state; move long-term learning into append-only structured history.

### A4 — Persist failed private attempts and treatment outcomes
`[ ]`
A failed private `topic=auto` attempt should influence future selection rather than disappearing from selector state.

### A5 — Persist `treatment` reliably
`[ ]`
Recent-treatment diversity logic currently lacks dependable treatment history in production memory.

### A6 — Automatic bounded QA → repair → re-QA loop
`[ ]`
Connect existing targeted defect localization and `video_repair_lab` concepts so one bad scene can be repaired without discarding an otherwise strong video. Must preserve unaffected scenes and re-certify the final result.

### A7 — Temporal/video-aware viewer QA
`[ ]`
Static contact sheets cannot truly judge motion, transition timing, caption timing, narrator prosody, music dynamics, or edit rhythm. Add temporal evaluation after basic factory proof.

### A8 — Persist actual final per-scene asset lineage
`[ ]`
Record the asset that actually rendered: scene intent, query, source/provider, asset ID/URL, winner, relevance/QA result, reuse/continuity metadata—not merely candidate IDs.

### A9 — Replace/augment script buffer with certified finished-video reserve
`[ ]`
The current buffer of manifests does not satisfy the Delivery Guarantee because downstream rendering and QA can still fail later.

### A10 — Scheduled provider-spend policy during V2.1 transition
`[ ]`
Legacy scheduled `render.yml` and daily `buffer.yml` can consume funded Gemini capacity and bank legacy scripts even while publishing is off. Deliberately control this during cutover.

### A11 — Port fast prerequisites into unattended production
`[ ]`
The private flagship received the safer/faster `fc-match`/ffmpeg-font prerequisite path; scheduled `render.yml` still contains the older slow/fragile probe.

### A12 — Current analytics ingestion + labeled human-preference dataset
`[ ]`
The existing performance learner is data-starved. Build current platform metrics and human labels before trusting automated performance weighting.

### A13 — Repository/ruleset integrity compatible with state-writing workflows
`[ ]`
`main` is currently unprotected, while some workflows intentionally commit state directly. Design integrity controls without breaking legitimate state mutation.

---

## Priority order after the current PR #73 gate

1. **Merge/validate PR #73 only if Jacob authorizes it; run one bounded private flagship.** Product evidence beats more speculation.
2. **C8 Downstream Factory Proof.** Get a known-good manifest through visuals/audio/render/QA so Writer success does not uncover another multi-day hidden blocker.
3. **S2 + A3 + A4 + A5 Learning Ledger foundation.** Stop repeating failed topic/treatment/repair patterns and separate operational memory from learning.
4. **C9 + S1 Topic × Treatment × Writability.** Improve what story architecture gets written before paying for Writer.
5. **A6 QA → targeted repair → re-QA.** Salvage almost-good videos instead of throwing them away.
6. **S5 + S6 + A8 Visual Intent / Continuity / Asset Lineage.** Historical human reviews show visual relevance is a major downstream quality lever.
7. **C3/C4/C5 + S9 Provider resilience/control.** Remove outage fragility and impossible calls while protecting quality.
8. **A1 + A2 + A10 + A11 Production convergence/cutover.** Only after private factory earns promotion.
9. **S3 + S4 + A12 Audience + human preference + real performance learning.** Optimize toward actual desirability, not internal score alone.
10. **S8 + A9 Delivery Guarantee / finished-video reserve.** Continuous manufacturing and certified inventory.
11. **S7 Premium visual escalation.** Activate only where proven free/authentic lanes cannot deliver the scene.
12. **A7 Temporal viewer QA.** Improve final judgment of motion/prosody/edit rhythm.
13. **C10 + A13 documentation/operations integrity.** Keep bootstrap truth and repo controls aligned.
14. **C1 word-window recalibration.** Only when excellent-script evidence justifies it.

## Operating rule

When a tactical checklist is shown, it is a **subset** of this master backlog, never a replacement. Completed tactical work must update this file's status; unfinished C/S/A items remain tracked until explicitly completed, disproven, superseded with a documented mapping, or intentionally abandoned by Jacob.

Every substantial Content Render prompt must also obey **STANDING RULE P1** above: preserve the prompt's immediate premise while deliberately advancing **1–5 compatible canonical backlog IDs**, with explicit exit criteria and item-by-item evidence on return.