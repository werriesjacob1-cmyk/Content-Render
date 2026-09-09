# Factory-proof closure + release-boundary certification — 2026-09-09

Branch `claude/integrated-factory-proof-20260909` (PR #76, draft, supersedes
#73/#74/#75). Not merged. No provider call, no Gemini spend, no render, no
Release, no Publer, no posting, no secret change, `AUTO_PUBLISH_ENABLED`
untouched.

---

## A. The claim, and what actually backs it

> the integrated branch can take a certified manifest through the downstream
> production machinery, create a correctly finished MP4, detect a targeted
> defect, repair only the authorized scene, reconstruct the finished video
> without losing captions/music/mastering, preserve lineage, and re-certify the
> repaired output — while making zero provider calls and having no publishing
> path.

**Supported**, with two scope limits stated in §F rather than buried.

Exact-head CI, both jobs SUCCESS on the same SHA:

| SHA | `test` | `factory-proof` | run |
|---|---|---|---|
| `763f334` | SUCCESS | SUCCESS | 34301460557 |
| `cb41c89` | SUCCESS | SUCCESS | 34302402466 |
| `b651b59` | SUCCESS | SUCCESS | 34302889958 |
| `1a56a72` (final head) | SUCCESS | SUCCESS | 34303309919 |

The final head's artifact was probed too: both MP4s **48 kHz / ~128 kbit/s AAC**,
audio QA −14.0 LUFS / −1.49 dBTP with no reasons, `repaired_asset_lineage.json`
naming scenes 2→`scene_2.mp4` (was `s2.mp4`) and 3→`scene_3.mp4` (was `s3.mp4`)
with 1 and 4 untouched, and `provider_calls_made` / `network_calls_made` both 0
with an empty detail list.

The artifact was **downloaded and probed**, not inferred from the exit code —
and that is what found the defect in §B.

Measured from artifact `downstream-factory-proof-763f334…` (10.6 MB):

| property | final.mp4 | repaired.mp4 |
|---|---|---|
| container / codecs | mp4, h264 + aac | mp4, h264 + aac |
| resolution / fps | 540×960, 30 fps | 540×960, 30 fps |
| duration | 16.033 s | 16.033 s |
| bytes | 5,369,957 | 5,390,281 |
| sha256 | `938033ac…4fb4` | `4854559d…8d19` |
| integrated loudness | −14.04 LUFS | −14.04 LUFS |
| true peak | −1.46 dB | −1.46 dB |
| audio QA | pass, no reasons | pass, no reasons |

`repair_execution.json` records `output_sha256` `4854559d…8d19` — **byte-identical
to the file downloaded independently**, so the re-QA verdict is bound to the
artifact that actually shipped, not to a different assembly.

Bounded repair, from the same artifact: targets `["2","3"]`; scenes 1 and 4
byte-identical before/after (`b43d8187…`, `6743090d…`); `provider_calls_made` 0;
`network_calls_made` 0 **measured** by intercepting `urlopen`,
`socket.connect` and `socket.create_connection`, with `network_calls_detail`
empty.

**The strongest single piece of evidence is visual.** Frames at t=7 s from both
MP4s carry an identical burned-in caption ("SAME", production karaoke styling,
same position) over a demonstrably different background. Captions, timing and
mastering survived the repair; only the authorized scene's visual changed.

---

## B. What inspecting the artifact found that CI could not

**Every render has been shipping 96 kHz AAC.** `loudnorm` resamples internally
to 192 kHz and never restores the input rate; with no `-ar` the encoder falls
back to the nearest rate it supports. `quality_audio_qa` had been *recording*
`sample_rate: 96000` in its own report and passing it, because it only had a
floor.

Pinning 48 kHz alone made it worse, and that second measurement is the useful
one:

| encode | true peak | verdict |
|---|---|---|
| 48 kHz @ 96 kbit/s | **+0.07 dB** | breaches the −0.5 dB ceiling |
| 48 kHz @ 128 kbit/s | **−1.49 dB** | the loudnorm target, exactly |
| 96 kHz @ 96 kbit/s | −1.50 dB | what shipped |

At the correct rate the encoder was bitrate-starved and its coding error
overshot the limiter by ~1.6 dB; the 96 kHz encode had masked that by spending
the bits above the audible band. Rate and bitrate are therefore **one decision**
and live together in `quality_audio_qa`, imported by `main.py` — the same
anti-drift rule as the Writer length contract. Mastering targets unchanged; cost
~1% file size. `repackage.py` copies the audio stream, so the TikTok cut
inherits it.

The gate gained the missing ceiling, so this fails loudly rather than being
recorded and waved through.

---

## C. Backlog status

| item | status | basis |
|---|---|---|
| **C8** real factory proof green on exact head | **COMPLETE** | both jobs, one SHA, artifact probed |
| **A6** bounded QA → repair → re-QA invariant | **COMPLETE** | adversarial suite + visual frame comparison |
| **A8** per-scene lineage incl. after repair | **COMPLETE** | was a real defect; fixed and CI-gated |
| **S5/S6** visual intent load-bearing | **COMPLETE (production path) / NOT CLAIMED (factory proof)** | counterfactual; see §D |

### A8 — this was a real defect
`final_asset_lineage.json` is written before the repair and still named
`work/s2.mp4` and `work/s3.mp4` after those exact scenes were replaced, while
reporting `all_rendered_scenes_attributable: true`. A repaired video would ship
with provenance naming assets it does not contain — worse than no record,
because it reads as attribution.

`quality_asset_lineage.repaired_lineage()` now derives the repaired record from
the pre-repair one, pointing at the files the repair actually assembled (via the
controller's new `repaired_scene_files`, not a re-derivation), naming which
scenes were swapped and what each replaced. Fails closed on an unknown scene, a
no-op replacement, and an empty replacement set. `phantom_assets()` fails the run
if lineage names a file that is not on disk. Verified:
`repaired_asset_lineage.json` shows 2→`scene_2.mp4` (was `s2.mp4`),
3→`scene_3.mp4` (was `s3.mp4`), 1 and 4 untouched.

---

## D. S5/S6 — proven by counterfactual, and honestly scoped

A bible that is written and ignored yields identical evidence to one that
governs routing: both produce a `visual_bible.json` with the right scene count.
So the test holds narration byte-identical and changes one bible field:

- changing only `must_show` changes which asset **wins** ranking (comparison
  diagram → seafloor footage);
- changing only the intent (ORIENT → PROCESS) flips `motion_required`, a routing
  input;
- applying the same bible twice is identical — the above is sensitivity, not
  nondeterminism;
- `quality_science_render` is pinned to apply the bible **before** motion
  planning and asset resolution, and to feed the directed manifest to both.

**Not claimed:** `quality_downstream_factory_proof` only *writes* the bible. It
renders fixed scene files and performs no asset selection, so there is nothing
for a bible to steer; its `visual_bible_scene_count` means the bible was
produced, not obeyed. A test asserts the proof does not start claiming otherwise.

---

## E. Release boundary

| surface | guard | state |
|---|---|---|
| GitHub Release | `AUTO_PUBLISH_ENABLED == 'true' && certification_only != 'true'` | gated |
| Publer direct API | same, plus `success()`, plus `publish_publer` requires exact `"true"` | gated at both layers |
| scheduled render | job-level `LEGACY_SCHEDULED_GENERATION_ENABLED` | gated |
| scheduled buffer | same | gated |
| scheduled bank expansion | same — **added this mission**; was the one ungated lane that could reach paid generation *and* auto-commit | gated |
| n8n notify | `if: always()`, ungated | **reviewed, accepted**: posts only `{status, run_url}` to a secret webhook; no video, no content, not a publishing path |
| `render.yml` triggers | `workflow_dispatch`, `repository_dispatch`, `schedule` — **no `push`** | pushing cannot render |

Run 34299147373 appears as `event: push` with `conclusion: failure` and zero
elapsed time. That is a **startup failure**: it is GitHub reporting the invalid
workflow YAML on `d4f5d3e` (a bug introduced and fixed within this branch), not
a render triggered by a push. No job ran and no provider was called.

`vars.AUTO_PUBLISH_ENABLED` cannot be read from here; the assurance is that
every publishing step is conditioned on it and `publish_publer` independently
requires the exact string.

---

## F. Scope limits — what this does NOT prove

1. **Production resolution.** The proof renders 540×960 synthetic scenes for
   speed. Production's 1080×1920 scaling path is not exercised. This proves
   finishing, not scaling.
2. **Real narration.** Audio is synthesized tones, not TTS output. Loudness and
   mastering mechanics are proven; speech-dependent behaviour is not.
3. **The Writer.** Unchanged by this mission and still open — the prompt now
   states the budget `validate()` enforces, but whether Gemini obeys it is
   unmeasured and only a paid run can settle it.

---

## G. Storage

Measured, and it corrects an earlier claim made in this branch: **the repository
already enforces 7-day artifact retention.** `final-video-284` (24.7 MB),
`-253` (43.9 MB) and `-248` (39.3 MB) all carry `expires_at` exactly 7 days after
creation and are already expired. The `retention-days: 7` added earlier was a
no-op; the real saving was dropping six redundant encodes and the `work/` scratch
tree.

That explains the 90%-of-0.5 GB alert without any hoard: ~35 MB per render, twice
daily, inside a 7-day window is ~490 MB by itself. The TikTok-only narrowing cuts
each render artifact ~80%.

**Recommendation only — nothing was deleted:**
1. Nothing to reclaim from render artifacts; everything older than 7 days has
   already expired.
2. The only meaningful set is this PR's ~10 superseded factory-proof artifacts
   (~106 MB), of which only the newest has evidentiary value. Safe to delete;
   they also expire on their own.
3. Factory-proof retention cut 7 → 3 days (verified: the final artifact carries
   `expires_at` exactly 3 days out). Its name stays unique per run so a later
   push cannot silently overwrite the artifact an earlier claim was made
   against — but note the name is `github.sha`, which on a `pull_request` event
   is the ephemeral **merge** commit, not the head SHA. To tie an artifact to a
   head SHA, read the run's `head_sha`, as the table in §A does.

---

## H. Recommendation on the next flagship run

**Justified, but only after Jacob merges and CI passes on actual `main`.**

The run would answer exactly one question — does Gemini obey a stated word
budget? — and that question is now genuinely isolated: the corpus showed 18 of
36 rounds died on length arithmetic against a prompt that never stated the
budget, the prompt now states it from the same constants `validate()` enforces,
and a test asserts the two cannot drift. Every cheaper way to answer it has been
used up; `writer_replay.py` can rehearse rejections offline but cannot tell you
what an unseen generation will do.

Two conditions before spending it:
1. merge PR #76 and confirm both jobs green on actual `main`, not on the branch;
2. keep `certification_only: true` so the output stays a private artifact.

Not started here: this mission's authority stops before provider-backed
generation, and triggering it is Jacob's call.
