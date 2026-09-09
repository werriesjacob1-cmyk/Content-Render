# Content Render — Standing Execution Rules

These rules govern substantial prompts and autonomous work cycles for Content Render.

## P1 — Backlog compounding
Every substantial engineering, research, audit, experiment, or execution prompt must preserve its immediate premise and deliberately target 1–5 compatible IDs from `engineering/CONTENT_RENDER_MASTER_TODO.md`.

## P2 — Precise execution toward the North Star
The purpose of P1 is **not** to maximize the number of TODOs touched. The governing objective is precise execution toward the North Star: a generic autonomous factory that reliably produces genuinely post-worthy short-form science videos.

For every substantial prompt/work cycle:

1. State one measurable **PRIMARY OUTCOME** that directly shortens the critical path to the North Star.
2. Select only backlog items that materially support that primary outcome. Do not add an item merely because it is nearby or convenient.
3. Prefer closure of one critical-path blocker over shallow progress on five lower-value items.
4. Use secondary backlog targets only when they share evidence, code boundaries, runtime state, or can be closed with negligible distraction while the primary work is already open.
5. If new evidence disproves the planned route, change the implementation—not the goal. Record the disproved hypothesis and take the shortest evidence-backed route forward.
6. Every change needs an explicit causal claim: **what bottleneck does this remove, and how will we know?** Tests/experiments must measure that claim rather than merely exercise code.
7. Do not confuse infrastructure activity with product progress. Green CI, more modules, higher internal scores, or more provider options are not sufficient unless they improve reliability, quality, learning, delivery, or time-to-post-worthy-video.
8. Keep irreversible boundaries separate: merge, meaningful provider spend, publishing/deploy, credential changes, and autopublish activation still require Jacob's explicit authorization where established.
9. End each work cycle with: primary outcome status, targeted backlog IDs and status, evidence, exact SHA/tests, newly discovered critical-path blockers, and the single best next move.
10. Re-rank the backlog when new evidence changes marginal payoff. The backlog is persistent; its order is evidence-driven, not frozen.

### Default prompt header

`PRIMARY OUTCOME: <one measurable result>`

`BACKLOG TARGETS: <1–5 IDs>`

`WHY THESE NOW: <one sentence explaining why they are on the current critical path>`

### Productivity definition

**Productivity = durable reduction of critical-path uncertainty/risk per unit of time, spend, and model usage.**

The goal is not "do more things." The goal is **reach an excellent autonomous video factory faster without sacrificing rigor.**
