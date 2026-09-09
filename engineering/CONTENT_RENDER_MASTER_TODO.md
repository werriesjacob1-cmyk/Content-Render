# Content Render — master backlog

**Status of this file (read first).** The closure mission asked for
`engineering/CONTENT_RENDER_MASTER_TODO.md` to be *updated*, preserving an
existing 33-item backlog and reconciling rather than overwriting. **That file did
not exist** — not at this path, not anywhere in `content-render`, and not in the
sibling `TikTok2` repo attached to this session. Nothing was overwritten, but
nothing could be reconciled either: the 33-item list is not reproduced below,
because inventing 33 plausible items would be worse than admitting they are not
in hand. What follows is only what there is direct evidence for. If the real
backlog exists somewhere else, merge it into this file rather than treating this
as the whole picture.

Last updated: 2026-09-09, branch `claude/integrated-factory-proof-20260909`
(PR #76). Exact-head CI verified on `b651b596f2415ac4555109a9ef879f5f23d60851`
— both the `test` job and the `factory-proof` job SUCCESS on that same SHA.

---

## Named closure targets

### C8 — real zero-provider factory proof green on exact head — **COMPLETE**
Both jobs SUCCESS on one SHA, and the artifact was downloaded and probed rather
than inferred from the exit code. That inspection is what found the audio defect
below, which is the point of the standard.

Evidence: run 34302889958 (`b651b59`), artifact
`downstream-factory-proof-<sha>`; both MP4s h264 540×960 / AAC 48 kHz, 16.03 s;
`provider_calls_made` 0 and `network_calls_made` 0 **measured** via interception,
with `network_calls_detail` empty.

### A6 — bounded QA → repair → reassemble → re-QA invariant — **COMPLETE**
`tests/test_repair_invariant_adversarial.py`. Attacks the invariant from the
directions the real defect came from: unauthorized scene refused, partial
replacement refused, missing asset fails closed, no-op replacement refused,
unaffected scenes proven unchanged by SHA256, re-QA measured on the *repaired*
artifact, failing re-QA surfaced rather than swallowed, and both assemblies
proven to run through the same canonical finishing path.

Visual confirmation from the CI artifact: at t=7 s the two cuts carry an
identical burned-in caption over a demonstrably different background — the
repair changed the visual and nothing else.

### A8 — per-scene asset lineage, including after repair — **COMPLETE**
Was a real defect, not a gap in test coverage: `final_asset_lineage.json` is
written before the repair and still named `work/s2.mp4` / `work/s3.mp4` after
those exact scenes were replaced, while reporting
`all_rendered_scenes_attributable: true`. A repaired video would have shipped
with provenance naming assets it does not contain.

Now `quality_asset_lineage.repaired_lineage()` derives the repaired record from
the pre-repair one, pointing at the files the repair actually assembled (from the
controller's new `repaired_scene_files`, not a re-derivation), naming which
scenes were swapped and what each replaced. Fails closed on an unknown scene, a
no-op replacement, and an empty replacement set. `phantom_assets()` fails the run
when lineage names a file that is not on disk. Gated in CI.

### S5/S6 — visual intent load-bearing before asset selection — **COMPLETE for the production render path; explicitly NOT claimed for the factory proof**
The distinction the mission warned about is real and is recorded rather than
rounded up. A bible that is written and ignored produces identical evidence to
one that governs routing, so the proof is a counterfactual with narration held
byte-identical:

- changing only `must_show` changes which asset **wins** ranking (diagram →
  seafloor footage);
- changing only the intent (ORIENT → PROCESS) flips `motion_required`;
- applying the same bible twice is identical, so the above is sensitivity and
  not nondeterminism;
- `quality_science_render` is pinned to apply the bible **before** motion
  planning and asset resolution, and to feed the directed manifest to both.

`quality_downstream_factory_proof` only *writes* the bible. It renders from fixed
scene files and performs no asset selection, so there is nothing for a bible to
steer there; its `visual_bible_scene_count` means the bible was produced, not
obeyed. A test asserts the proof does not start claiming otherwise.

---

## Also closed in this mission

- **Delivery audio encode.** Every render shipped 96 kHz AAC: `loudnorm`
  resamples internally to 192 kHz and never restores the rate, so with no `-ar`
  the encoder fell back to the nearest rate it supports. The audio gate had
  recorded `sample_rate: 96000` and passed it, because it only had a floor.
  Fixing the rate then exposed that 96 kbit/s was bitrate-starved at 48 kHz
  (+0.07 dBTP, breaching the gate's own ceiling); 128 kbit/s lands at −1.49 dB,
  the loudnorm target. Rate and bitrate now live together in `quality_audio_qa`
  and are imported by `main.py`.
- **Three boundary safety gaps**: `expand_bank.yml` was the one scheduled lane
  that could still reach paid generation ungated *and* auto-commit;
  `stamp_manifest` could bless an unversioned V2.1-certified manifest as legacy;
  the proof's zero-call claims were hardcoded literals and are now measured.
- **Evidence serialization** (`quality_evidence.py`): one fail-closed boundary
  for all ten evidence-writing sites.

---

## Open

- **The Writer question is still open and only a paid run can close it.** The
  V2.1 prompt now states the budget `validate()` enforces, with a drift test.
  Whether Gemini *obeys* it is unmeasured. Use `writer_replay.py` against
  `tests/fixtures/writer_corpus/` for any further prompt idea first — that is
  free; a flagship run is not.
- **Production resolution is unproven by the factory proof.** It renders
  540×960 synthetic scenes for speed, so production's 1080×1920 scaling path is
  not exercised. The proof covers finishing, not scaling.
- **ffmpeg encoding and audio QA on real TTS remain unproven end to end** — the
  proof uses synthesized tones, not a real narration track.
- **The publishing path is still documented inconsistently.** `CLAUDE.md`'s
  architecture section says "GitHub Release → Zapier → Buffer"; the code has no
  Buffer anywhere and `render.yml` has a direct **Publer** step. Needs Jacob to
  say which path is actually live, then the wording fixed.

## Storage — inventory and recommendation (no deletion performed)

Deleting historical artifacts is Jacob's decision and none were deleted.

Measured, not assumed: **the repository already applies a 7-day artifact
retention** — `final-video-284` (2026-09-01, 24.7 MB), `final-video-253`
(43.9 MB) and `final-video-248` (39.3 MB) all show `expires_at` exactly 7 days
after creation and all are already `expired: true`. An earlier commit message in
this branch claimed render artifacts inherited a 90-day default; that claim was
wrong, and the `retention-days: 7` it added was a no-op. The real saving came
from dropping six redundant encodes and the `work/` scratch tree.

That also explains the 90%-of-0.5 GB alert without any 90-day hoard: at ~35 MB
per successful render, twice daily, a 7-day window holds ~490 MB on its own. The
TikTok-only narrowing cuts each render artifact to roughly one encode plus small
JSON, an ~80% reduction, and directly addresses the alert.

**Recommendation, for Jacob to accept or decline:**

1. **Nothing to reclaim from render artifacts** — every one older than 7 days is
   already expired. There is no historical hoard to delete.
2. **The only meaningful reclaimable set is this PR's own superseded
   factory-proof artifacts**: roughly ten commits × ~10.6 MB ≈ ~106 MB, of which
   only the newest has evidentiary value. Deleting the superseded ones is safe;
   they also expire on their own.
3. Factory-proof retention has been cut 7 → 3 days. Its name intentionally
   carries the commit SHA, because this mission's evidence standard is exact-SHA
   and a stable name would let a later push silently replace the artifact a claim
   was made against. Storage therefore grows with pushes, not time, so retention
   is the only lever that does not weaken the evidence.
