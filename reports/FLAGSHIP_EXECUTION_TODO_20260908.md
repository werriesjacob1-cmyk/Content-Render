# Content Render flagship execution TODO — 2026-09-08

North Star: **produce a genuinely post-worthy private flagship video with the generic factory path, without weakening quality or publishing containment.**

## Completed

- [x] Merge integrated certification stack PR #72 to `main`.
- [x] Verify merged `main` SHA `240bdc137a0fc4c7636f4e9d5c3ca13e58e2acdb` and actual-main CI clean.
- [x] Preserve publishing kill switch / private-artifact-only boundary.
- [x] Reconstruct flagship Writer rejection corpus from runs #2-#5.
- [x] Quantify corpus: 13 attempts / 36 rounds / 0 accepted.
- [x] Confirm hidden runtime narration-length contract as a primary systemic defect: 17/36 rounds hit total/per-scene length failures.
- [x] Test repair-budget-starvation hypothesis; reject it as the primary cause (only 2/36 rounds Tier-1 clean).
- [x] Add dynamic Writer V2.1 runtime narration contract to initial Writer and repair calls.
- [x] Make scene-1 statement / later-curiosity-question rule unambiguous at the final runtime instruction boundary.
- [x] Add zero-provider rejection replay analyzer (`writer_replay.py`) and regressions.
- [x] Add certification-only Groq capacity skip for requests that cannot fit the known TPM envelope.
- [x] Align Groq capacity reserve with the structured caller's real `max_tokens=3000` budget; exact 8k boundary is regression-tested.
- [x] Keep normal unattended production provider policy unchanged.
- [x] Open draft PR #73 from `superchad/flagship-writer-recovery-20260908`.
- [x] Obtain green exact-head CI on the first reviewed PR #73 head.
- [x] Correct the audit wording so the hook failure is described accurately as an internal prompt ambiguity, not a nonexistent hard requirement to use a question hook.

## Current gate

- [ ] Re-run exact-head CI after the final audit/documentation/provider-capacity hardening.
- [ ] Final narrow merge-boundary audit of PR #73: `main SHA -> PR head -> changed scope -> exact-head CI -> publishing/provider boundaries`.
- [ ] **Jacob merge authorization for PR #73.** No merge without explicit authorization.

## Immediately after PR #73 merge

- [ ] Verify resulting actual `main` SHA and that PR #73 merged from the approved head.
- [ ] Verify actual-main CI is green.
- [ ] Confirm publishing remains disabled and no provider-backed generation/render was triggered by merge.
- [ ] Prepare a new trusted flagship trigger marker using `topic=auto` (do not reuse the old Venus marker).

## Next irreversible boundary — separate authorization required

- [ ] **Jacob authorizes one bounded private flagship factory-proof run.**
- [ ] Run `topic=auto` through the generic Writer path; no evidence-seed preference.
- [ ] Keep artifact private; no Release/public distribution/auto-publish.
- [ ] Allow provider-backed Writer/review calls and free science-network retrieval only inside the authorized run envelope.

## What the next run must answer

- [ ] Did Writer produce at least one accepted candidate within the bounded attempts?
- [ ] Did hidden length failures materially fall from the 47.2% historical round rate?
- [ ] Did any hook-question failure recur?
- [ ] Were semantic/provenance gates still fully enforced?
- [ ] Did capability-aware routing avoid structurally impossible Groq calls?
- [ ] If Writer passes, did the downstream visual/audio factory produce an actual private MP4?
- [ ] Human review: immediate hook, information gain in first ~8s, natural narration, escalation, payoff, low AI smell, explanatory visuals, authentic scientific media, clean captions, polished sound.

## If the private run fails

- [ ] Classify failure from artifacts before changing architecture.
- [ ] Repair only the demonstrated root cause on a branch/PR.
- [ ] Do not widen word limits, add repair rounds, weaken provenance, or special-case the selected topic without evidence.
- [ ] Reuse `writer_replay.py` to compare the new rejection family against the historical corpus.

## Deferred until after tonight's product proof

- [ ] Topic × treatment joint scoring (zero extra LLM calls, reproducible, variety-aware).
- [ ] Broader treatment-quality evidence across more than the two treatments represented in the current rejection corpus.
- [ ] Higgsfield premium generated-visual integration with bounded credit controls.
- [ ] Platform-specific publishing canary / Publer activation.
- [ ] Certified finished-video reserve and automatic replenishment.
