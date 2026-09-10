# Content Render — canonical master backlog

**Authoritative control-plane status as of 2026-09-10.**

This file is the canonical repo-level backlog for Content Render. It replaces the
stale 2026-09-09 status language that predated PRs #81, #87, and #88 and several
live/private render attempts. Historical PRs remain in GitHub history; open PRs
must not be used as the project's memory system.

Current production main at this update:

`78338ef6d54ca488233ac4505267474b3500c0c0`

That commit is the merge of PR #88 (footage relevance + live judge failover),
on top of PR #87 (deterministic Writer repair) and PR #81 (Actions artifact
storage budget). Actual-main CI was green after the #88 merge.

## North Star

**UNMET: no certified, post-worthy science video has yet cleared the complete
factory and human product bar.**

Private/diagnostic MP4s have been produced and are useful evidence, but an MP4
or a machine PASS does not by itself satisfy the product goal. The target is a
video Jacob would genuinely publish without excuses.

Until the North Star is met, each substantial engineering cycle must end in one
of two outcomes:

1. a better real MP4 to inspect; or
2. one narrowly proven blocker that directly prevented a real MP4.

Do not insert broad research/measurement projects between those outcomes unless
the experiment directly decides which blocker to attack.

## Immediate critical path

1. **S6 upstream visual intent — ACTIVE / PARTIAL.** The downstream certification
   renderer already has Visual Director, Visual Bible, science-motion routing,
   authentic-media adapters, lineage, and final QA. The live legacy generation
   path can still reject an otherwise usable script solely because disposable
   `search_query` metadata is bad before those downstream systems get a chance
   to help.
2. **Metadata-only visual-intent repair — IN PROGRESS, not yet pushed/merged.**
   Desired contract: bad retrieval metadata may be repaired generically and
   deterministically, narration/evidence must remain byte-identical, the full
   existing validator must run again, and unrecoverable cases still fail closed.
3. **Next real private render.** Once the above change is exact-head green and
   merged by explicit authorization, run one real private candidate and judge
   the finished MP4 under `engineering/NEXT_MP4_ACCEPTANCE.md`.
4. **Do not start topic-filmability architecture, Writer V2.1 redesign, provider
   model bakeoffs, Audience Intelligence, Sound Brain, or premium-visual spend
   before that render unless new evidence directly requires it.**

## Canonical backlog — Claude / production items

### C1 — empirical word-window recalibration — DEFERRED
Current prompt/validator length arithmetic was materially improved and live
length failures stopped being the dominant blocker. Revisit only with enough
new live data to justify changing the window.

### C2 — offline Writer replay harness — COMPLETE / ACTIVE TOOLING
`writer_replay.py` and the accumulated Writer corpus provide zero-provider
replay for prompt/repair experiments.

### C3 — remove single-provider fragility — PARTIAL
Provider fallback exists, but the project should continue removing avoidable
single-provider dependencies only when they are observed on the critical path.

### C4 — compact prompt / recover constrained-provider eligibility — PARTIAL
Useful optimization, not today's blocker.

### C5 — structurally impossible provider skip — SUBSTANTIALLY COMPLETE
Request-size/capability accounting and skip evidence are load-bearing.

### C6 — "more repair rounds will solve Writer failures" — CLOSED / DISPROVEN
Historical replay showed extra rounds would not solve the dominant failure
classes. Keep bounded repair.

### C7 — Writer reliability / creative-output quality — PARTIAL
Legacy calibration showed the current deterministic gates are not the primary
miscalibration: 12/12 real August controls survived them. The Writer remains
high-variance and topic-sensitive, but a live legacy candidate has reached 7.14.
Do not reopen broad Writer architecture before the next visual-intent/render
cycle.

### C8 — downstream render / visual / audio / QA proof — COMPLETE
Production-realism evidence proved 1080x1920 rendering, real TTS/Piper/Edge
paths, Whisper alignment, captions, shared mastering, AAC 48 kHz, true-peak
headroom, repair/reassembly parity, and zero-provider factory proof. Reopen only
if a new real artifact falsifies one of those guarantees.

### C9 — topic / production readiness — PARTIAL / OPEN
Do not blacklist abstract subjects. If topic readiness is advanced, it should
measure whether the *current* visual stack can plausibly illustrate the story,
preferably as a non-gating preference/tie-breaker first. Not on the critical
path until visual-intent repair has been tested on another real render.

### C10 — documentation — PARTIAL
Keep canonical status here and remove stale path/provider/publishing comments
that repeatedly create false work.

## Canonical backlog — SUPERCHAD items

### S1 — Topic x Treatment intelligence — SHADOW
Do not promote from small convenience samples.

### S2 — append-only learning ledger — IMPLEMENTED / LIVE-PROVEN
Failed private attempts and treatment/context evidence have been captured.

### S3 — Audience Intelligence shadow — OPEN
Not on the current render blocker.

### S4 — Human Preference Evaluation — OPEN
Lexical deterministic craft proxies are useful longitudinal diagnostics but are
not human preference or prose-quality measurement.

### S5 — Visual Continuity — LOAD-BEARING DOWNSTREAM
Visual Bible/continuity behavior is in the production certification renderer.

### S6 — Visual Intent — PARTIAL / ACTIVE
**Important correction to the old status:** downstream visual intent is
load-bearing, but upstream legacy generation can still die on bad visual-query
metadata before downstream routing. The current mission is to close this seam
without weakening validation or hardcoding individual topics.

### S7 — premium visual escalation — OPEN
No Higgsfield/FAL/premium spend without explicit authorization and a demonstrated
need from a real video.

### S8 — finished-video certified reserve — OPEN
Long-term delivery guarantee remains unfinished.

### S9 — provider capability + cost + session-health router — PARTIAL
Capability and session-health behavior are substantially implemented; explicit
cost-aware LLM routing remains unimplemented. Not today's blocker.

### S10 — champion/challenger experiments — ADVANCED / PARTIAL
Deterministic replay/rescore coverage is useful, but weak lexical proxies must
not be mistaken for human creative quality.

## Canonical backlog — audit / operating items

### A1 — deliberate V2.1 cutover — OPEN
No cutover until a real candidate proves the promoted path.

### A2 — queue migration/version safety — IMPLEMENTED
Legacy/version compatibility guards are present.

### A3 — operational memory vs append-only evidence — FOUNDATION PRESENT

### A4 — persist failed private attempts — LIVE-PROVEN

### A5 — treatment persistence — LIVE-PROVEN

### A6 — bounded QA -> repair -> re-QA — COMPLETE
Repair cannot bypass final QA and both original/repaired assemblies use the
same finishing path.

### A7 — temporal/video-aware QA — OPEN
Current final QA samples the video but long-term temporal understanding can
still improve.

### A8 — final per-scene asset lineage — COMPLETE
Lineage is updated through repair and fails closed on phantom/unknown assets.

### A9 — finished certified reserve — OPEN
Same long-term delivery problem as S8.

### A10 — scheduled provider-spend policy — GUARDED
Legacy scheduled spend is opt-in; manual/private runs remain explicit actions.

### A11 — operational prerequisites/storage — PARTIAL HARDENING
PR #81's storage split is merged. PR #80 remains an optional apt/repository
hardening change and is not a current video blocker.

### A12 — analytics/human-preference dataset — OPEN

### A13 — branch/ruleset integrity — OPEN
Main remains operationally sensitive; explicit merge boundaries continue to be
required.

## Proven durable capabilities already on main

Do not rebuild these from scratch:

- Visual Director / visual-class routing.
- Visual Bible and continuity contracts.
- Authentic scientific-media adapters (NASA/PubChem/RCSB modules).
- Deterministic science-motion machinery.
- Quality stack / quality runtime.
- Writer semantic coverage fail-closed primitives.
- Final-video multimodal QA.
- Per-scene final asset lineage.
- Bounded repair controller and re-QA.
- Real-production audio mastering contract.
- Provider session-health/cooldown.
- Footage subject anchoring and relevance-over-forced-uniqueness.
- Runtime Groq judge-model discovery/failover.
- TikTok-only retained video artifact policy during certification.
- Publishing/autopublish kill switches.

Some older PRs contain *integration concepts* that are not fully load-bearing in
the legacy lane. Preserve those concepts as backlog evidence rather than
merging stale branches.

## Known useful concepts not yet promoted

- **PR #37:** topic/domain cleanup is mostly evolved into main, but its
  `expand_bank.yml` pre-commit zero-quota validation step is not present on
  current main. Extract that safeguard as a small future hardening change rather
  than merging the stale PR.
- **PR #42:** `scientific_media.py` exists on main, but the old direct
  `main.py` integration that let NASA SVS compete with Pexels and routed
  PubChem before generic still fallback is not currently present in the legacy
  path. Preserve as prior art; do not merge stale #42.
- **PR #44:** current main fixed the retired Groq text judge via runtime model
  discovery, but the old Qwen multimodal thumbnail fallback and three-frame
  generated-video verification remain distinct, unpromoted ideas. Re-evaluate
  only after a real MP4 shows the need.
- **PR #82:** narrative-function repair remains an experiment, not a measured
  systemic fix. Do not merge from its stale branch.
- **PR #85:** numeric Gemini-version sorting and manual Writer-model override are
  valid latent correctness/experiment-enablement ideas, but neither is a proven
  current quality lever. Keep off the critical path.

## PR hygiene policy

Open PRs are release state, not project memory.

Default target:
- at most 1 active implementation/release PR;
- at most 1 explicit experiment PR;
- at most 1 optional hardening PR.

When a PR is integrated, superseded, or reduced to historical evidence, close
it without deleting the branch unless branch deletion is separately authorized.
Record any still-useful concept here first.

## Publishing boundary

AUTO_PUBLISH remains OFF.

No Release, Publer, posting, deployment, or autopublish activation without
Jacob's explicit authorization. The production code currently contains direct
Publer support; stale documentation that describes Buffer/Zapier as the active
path should be corrected separately once the intended distribution path is
confirmed.

## Product acceptance

The next real MP4 is judged under:

`engineering/NEXT_MP4_ACCEPTANCE.md`

Machine PASS is necessary but not sufficient. The final product verdict must be
one of:

- **POST-WORTHY**
- **REPAIRABLE — NOT POST-WORTHY YET**
- **REJECT — NEW CANDIDATE**

The North Star closes only on **POST-WORTHY**.
