# NEXT MP4 ACCEPTANCE — Content Render

This is the product-review contract for the next real private Content Render
video. It is deliberately separate from production acceptance code.

**Machine PASS is necessary, not sufficient.**

The purpose is to stop treating "the pipeline completed" as success. A video
only satisfies the current North Star when the finished artifact is something
Jacob would genuinely post without having to excuse weak writing, irrelevant
visuals, obvious AI artifacts, or broken pacing.

## Verdicts

Every reviewed MP4 must end in exactly one verdict:

1. **POST-WORTHY** — technically sound, factually safe, machine QA passes, and
   the finished creative product is genuinely publishable.
2. **REPAIRABLE — NOT POST-WORTHY YET** — core story/product is good enough to
   preserve, but one or a small number of bounded visual/audio/edit fixes are
   needed.
3. **REJECT — NEW CANDIDATE** — the premise, writing, structure, or visual plan
   is weak enough that repairing the current artifact is lower-value than
   generating a new candidate.

Do not invent a softer fourth category.

## Gate 1 — technical hard gate

The final MP4 must:

- exist and decode end-to-end;
- be 1080x1920 vertical H.264;
- carry AAC audio at 48 kHz;
- contain no material black/frozen/truncated section;
- satisfy the existing audio QA contract:
  - integrated loudness between -16.0 and -11.5 LUFS;
  - decoded true peak <= -0.5 dBTP;
  - long-silence ratio <= 20%;
- have usable caption timing throughout;
- have no missing scene file or final-assembly corruption.

Failure => **REJECT** unless the defect is trivially repairable without changing
the creative candidate.

## Gate 2 — science / factual hard gate

Reject any artifact with a material factual-integrity problem, including:

- narration that states an unsupported/contradicted central claim;
- a visual that materially contradicts the narrated science;
- invented scientific numbers, labels, mechanisms, dates, entities, or diagrams;
- a generated scientific object/anatomy depiction with a severe correctness
  problem;
- misleading footage that implies the wrong subject/mechanism;
- critical garbled baked-in text, fake labels, or hallucinated scientific
  notation.

A visually beautiful false explanation still fails.

## Gate 3 — existing machine holistic QA

Run the repository's existing final-video QA.

Required:
- overall >= 7.5;
- every required dimension >= 6.0;
- zero critical failures;
- zero critical evidence violations.

The machine judge covers:
- hook visual;
- narration/visual match;
- scientific integrity;
- visual variety;
- pacing;
- captions;
- continuity;
- payoff visualization;
- AI/media artifacts.

A machine PASS does **not** automatically produce POST-WORTHY.

## Gate 4 — first 8 seconds

Inspect the opening more densely than the normal whole-video sample.

Review approximately:
- 0.5 s
- 1.5 s
- 3 s
- 5 s
- 8 s

The opening must:

- reveal the actual subject immediately;
- establish a concrete curiosity gap;
- deliver information gain quickly;
- avoid generic series filler;
- avoid "Part one", "Did you know", or equivalent throat-clearing unless the
  wording is genuinely load-bearing;
- avoid generic wallpaper before the viewer understands what the video is about;
- give the viewer a reason to continue before 3-5 seconds.

A technically good video with a weak first 8 seconds is not POST-WORTHY.

## Gate 5 — scene-by-scene explanatory match

For every scene, ask:

> **Does this visual help the viewer understand or feel the exact sentence, or
> is it merely related wallpaper?**

Classification:

- **EXPLAINS/PROVES** — the visual directly shows the mechanism, scale,
  comparison, event, object, or evidence being narrated.
- **SUPPORTS** — the visual is directly relevant and strengthens the sentence,
  even if it is not itself a full explanation.
- **WALLPAPER** — the visual shares a noun/theme but does not help explain the
  line.
- **CONTRADICTS/OFF-TOPIC** — visual subject is materially wrong.

Core mechanism, escalation, and payoff scenes should normally be
**EXPLAINS/PROVES**. Too many WALLPAPER scenes means the video is not
POST-WORTHY even if clip relevance technically clears a machine threshold.

Examples of the distinction:
- a glass of water during kidney/homeostasis narration is related but does not
  explain the mechanism;
- a physical chessboard can support a chess-combinatorics scene, while a
  deterministic branching graphic can explain the combinatorial explosion;
- generic galaxy imagery is not an acceptable substitute for a non-space scene
  merely because the narration uses a "bigger than the universe" comparison.

## Gate 6 — human/SUPERCHAD creative product review

Watch the entire MP4 at normal speed, then spot-check problem sections.

Target quality:
- hook / scroll-stop: about 8/10;
- first-8-second information gain: about 8/10;
- narration naturalness: about 8/10;
- narration-to-visual explanatory match: about 8/10;
- payoff: about 8/10;
- low AI smell: about 8/10;
- pacing / rhythm: >= solid 7/10;
- visual variety / progression: >= solid 7/10;
- captions / typography: >= solid 7/10;
- music / sound / mix: >= solid 7/10;
- continuity / cohesion: >= solid 7/10;
- science authenticity: no meaningful concern.

These are product-review targets, not new hidden production gates. The decisive
question is:

> **Would Jacob genuinely post this without explaining away obvious weaknesses?**

If NO, it is not POST-WORTHY.

## Repairability rule

Choose **REPAIRABLE** only when:

- the premise and narration are worth preserving;
- factual integrity is intact;
- the number of material defects is small and localized;
- bounded repair can change the defective scene(s) without destabilizing the
  rest of the artifact;
- the expected repaired result is higher-value than generating a new candidate.

Choose **REJECT** when the video needs broad rewriting, many scene replacements,
a different visual strategy, or a different premise.

## Evidence packet required after every real render

Record:

- run ID;
- exact main/branch SHA;
- topic + treatment/path;
- Writer score and gate state;
- final MP4 artifact identity;
- duration / resolution / codec / audio probe;
- audio QA values;
- final machine QA;
- first-8-second observations;
- per-scene EXPLAINS / SUPPORTS / WALLPAPER / OFF-TOPIC classification;
- top 3 creative defects;
- final POST-WORTHY / REPAIRABLE / REJECT verdict;
- exact next action.

Do not start a new architecture mission until that packet identifies the real
viewer-facing blocker.

## Current boundary

This document does not authorize publishing.

No Release, Publer, deployment, posting, or AUTO_PUBLISH activation follows from
POST-WORTHY without Jacob's explicit authorization.
