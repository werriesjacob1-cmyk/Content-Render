# OPEN PR TRIAGE — 2026-09-10

Purpose: separate active release work from historical evidence. Open PRs are not
the project-memory system; useful concepts should be captured in the canonical
backlog before obsolete PRs are closed.

Current main for this audit:
`78338ef6d54ca488233ac4505267474b3500c0c0`

## Already closed during cleanup

Closed without merging or deleting branches:

- #86 — superseded by merged #88.
- #83 — superseded by merged #87.
- #68 — integrated/evolved into current main.
- #69 — autopublish kill-switch behavior integrated/evolved.
- #47 — Visual Director integrated/evolved.
- #48 — grounded-research architecture integrated/evolved.
- #46 — superseded by later vision work.
- #84 — completed calibration/evidence mission; no production delta to promote.
- #43 — core Voice Lab implementation already present on main.
- #45 — core FAL/video-model lab implementation already present on main.
- #49 — deterministic science-motion implementation already present on main.
- #50 — final-video multimodal QA implementation already present on main.
- #51 — still-model bakeoff implementation already present on main.
- #52 — constrained video-repair lab implementation already present on main.
- #53 — Sound Brain implementation already present on main.
- #54 — RCSB molecular-media implementation already present on main.
- #55 — end-to-end quality stack integrated/evolved.
- #56 — fail-closed Writer V2.1 semantic coverage integrated/evolved.
- #70 — flagship #4 root-cause fixes integrated/evolved.
- #71 — trusted flagship trigger integrated/evolved; the old scale-comparison
  promotion intent was superseded by the current fail-closed comparability rule.

Branches/history were intentionally retained.

## Partial / extract-before-close

### #37 — topic-bank integrity
**Recommended disposition: KEEP TEMPORARILY; extract one missing safeguard, then
close.**

Most domain-family cleanup has evolved into current `generate.py` and
`funnel.py`.

The one missing safeguard has now been extracted from stale #37 into **draft
PR #91** on current main: after `expand_bank.py` mutates the bank, the existing
zero-quota `tests/test_pipeline.py` suite must pass before the bot may commit.
PR #91 also pins the ordering with a transition-contract regression.

Do not merge stale #37. Once #91 is independently green and merged by explicit
authorization, #37 can be closed as fully superseded.

### #42 — NASA SVS + PubChem direct legacy integration
**Recommended disposition: KEEP AS PRIOR ART until concept is captured/decided.**

`scientific_media.py` exists on current main, but legacy `main.py` does not
currently import it. The old PR's unique integration behavior let NASA SVS
compete with Pexels instead of only acting as a fallback and routed PubChem
before generic still fallbacks for chemical scenes.

Do not merge stale #42. The concept belongs under S6 visual-intent/asset routing
and should be reconsidered only after the current upstream visual-intent repair
is tested on a real MP4.

### #44 — Qwen vision fallback + three-frame synthetic safety
**Recommended disposition: KEEP AS PRIOR ART until concept is captured/decided.**

Current main's #88 work repaired the retired Groq text-judge failure through
runtime model discovery/failover. It does NOT promote the old #44 Qwen
multimodal thumbnail fallback or three-frame generated-video verification.
Those remain distinct resilience/quality ideas.

Do not merge stale #44. Re-evaluate only if a real MP4 shows Gemini vision
availability or single-frame synthetic verification is a material blocker.

### #82 — craft-preserving narrative-function repair
**Recommended disposition: KEEP EXPERIMENT or close after archival reference.**

The systemic premise was not supported by the full repair-pair study. The one
real craft-collapse case remains useful evidence, but the narrative-function
production change is not a proven general fix. #87 extracted the deterministic
`must_preserve` correction without promoting the experiment.

### #85 — Gemini numeric version sorting + manual writer-model override
**Recommended disposition: HOLD / SMALL FUTURE CORRECTNESS PR, not quality-critical.**

The current main still string-sorts numbered Gemini model IDs, so the latent
version-ordering bug remains. Current `render.yml` also lacks the manual
`gemini_model` dispatch input from #85.

Both ideas are real but neither is the current video-quality blocker. A single
model A/B would not settle quality because Writer variance is larger than one
run can distinguish.

## Optional hardening retained

### #80 — apt/repository prerequisite hardening
**Recommended disposition: KEEP OPEN as the single optional hardening PR.**

This is operational robustness, not the current video blocker. Do not allow it
to interrupt the visual-intent -> render loop.

## Target active-PR shape

After the current visual-intent work becomes a PR, aim for:

1. one active release/implementation PR;
2. #80 as one optional hardening PR;
3. at most one explicit experiment/prior-art PR if it needs active discussion.

Everything else should be closed after its useful concept is captured here or
in `CONTENT_RENDER_MASTER_TODO.md`.

## No actions authorized by this file

This triage document is evidence/recommendation only. It does not itself
authorize merges, branch deletion, provider calls, renders, publishing, or
closing PRs not already explicitly authorized by Jacob.
