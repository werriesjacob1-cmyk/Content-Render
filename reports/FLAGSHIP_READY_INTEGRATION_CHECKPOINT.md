# Flagship-ready integration — mission checkpoint

Recovery state for a fresh session. Concise by design.

- **branch**: `claude/flagship-ready-integration-20260909`
- **base / main SHA**: `fed4b0fd80ca353668fe80283bbe23e3fcbcd8ca` (verified unmoved)
- **PR #78 head integrated**: `08a577f39c0537cbe906e1529d9a4346b069320f` (branch
  started AT this SHA, so #78's delta is present in full and unmodified)
- **PR #77 head**: `88fd8c0906b5d9c10c1264682c31fa5d9a1d2e55` (selectively integrated)
- **pushed SHA**: see `git log -1`

## Irreversible boundaries NOT crossed
No merge, no flagship, no provider/Gemini call, no paid media, no Release, no
Publer, no posting, no deploy, no secret change, `AUTO_PUBLISH_ENABLED` untouched.

---

## Finding 1 — PR #77's shared audio contract was INERT

#77 added `DELIVERY_TRUE_PEAK_TARGET_DB = -2.5` and `delivery_loudnorm_filter()`
to `quality_audio_qa` and declared the renderer and factory shared one contract.
**Nothing called either.** `main.py` imported only rate and bitrate; `main.py`
and *both* branches of `quality_downstream_factory_proof._mix_final` still
carried a hard-coded `loudnorm=I=-14:TP=-1.5:LRA=11`.

The realism proof delegates all mastering to `QDF._mix_final`
(`quality_production_realism_proof.py:289`) and **#77 never touched that file**
(its diff vs main is 5 files; the factory proof is not among them). So the -2.5
target reached no mastering path whatsoever. Both of #77's measurements
(+0.26 and -1.30 dBTP) were produced at **-1.5**. The evidence attributed to the
new constant belongs to the old one.

## Finding 2 — `quality_audio_qa` was the wrong home for the contract

`main.py` importing it made production depend on the module that judges it, and
`quality_audio_qa` is not even a leaf: it imports `narration`, a production
module. The contract now lives in **`delivery_contract.py`**, which imports
nothing; a test enforces that so the cycle cannot return.

## Finding 3 — #77's `quality_audio_qa` rewrite carried two regressions
Taken: the NaN-based no-audio path (yields a real failure reason).
**Not** taken: `review()` dropping `silence_intervals` (only `review()` ever set
it — `evaluate_metrics` does not, so the field would vanish from every report),
and making `--report` required.

---

## Audio delivery architecture (final)

Two modules, split on a real boundary rather than for tidiness:

- **`delivery_contract.py`** — a leaf that imports nothing from the codebase.
  Owns `DELIVERY_SAMPLE_RATE` 48000, `DELIVERY_AUDIO_BITRATE` **"192k"**,
  `DELIVERY_INTEGRATED_LUFS` -14, `DELIVERY_TRUE_PEAK_TARGET_DB` **-2.5**,
  `LIMITER_OVERSAMPLE_RATE` **192000**, `QA_TRUE_PEAK_CEILING_DB` **-0.5**, and
  the filter builders.
- **`delivery_master.py`** — the ONE mastering sequence. Mastering has to
  *measure* its own intermediate result and act on it, which is execution, not
  configuration; forcing that into the contract would break the leaf role that
  exists to stop the import cycle. It imports the contract and nothing else —
  deliberately **not** `quality_audio_qa`, so production never depends on the
  module that judges it, and it carries its own small probe.

Consumers call `master_audio`, never their own sequence: `main.py`,
`quality_downstream_factory_proof._mix_final`, and the realism proof via
`QDF._mix_final`. All three mix to audio, master, then mux. A test asserts they
resolve the same function object; another stubs it out and proves neither path
falls back to a filter string of its own.

**No gate was ever relaxed.** The window is still [-16.0, -11.5] LUFS and
-0.5 dBTP, and a test moves the master target to prove the gate's verdict does
not follow it. Every dB of headroom was bought on the production side.

`analyze_loudness` deliberately keeps its own literal args — it is a MEASUREMENT
pass reading `input_*`, which do not depend on target parameters. A test guards
that decision in both directions, and `delivery_master`'s own probe follows the
same rule.

## Proof the contract is load-bearing (not grep)

`tests/test_delivery_contract_load_bearing.py` calls the **real** `_mix_final`
with both execution seams intercepted, captures all five constructed ffmpeg
commands, moves the shared constant to -7.25 and asserts every command moves
with it and none keeps the old value. Plus: no finishing path hard-codes a
delivery target; the renderer holds no literal filter; measurement stays
decoupled; the master measures at every stage including after the limiter.

`tests/test_delivery_mastering_adversarial.py` covers ten named rot paths, each
one MOVED and the constructed behaviour asserted to move with it (or, for the
gates, pointedly not to): production/proof drift, a hard-coded loudness target,
a hard-coded true-peak target, a weakened QA ceiling, analysis-pass coupling,
two measurements reading the same file, a limiter vanishing from a gain stage or
losing its true-peak oversampling, a repaired assembly finished differently,
sample-rate drift, bitrate drift.

---

## Status

- **Phase 1 integration** — DONE (branch from #78 head + #77's 4 harness files).
- **Phase 2 contract** — DONE (`delivery_contract.py`, all 4 delivery sites).
- **Phase 3 load-bearing proof** — DONE.
- **Phase 4 production-realism** — DONE on `e86f930`, artifact probed.
- **Phase 5 Edge** — Edge/Whisper routing in `main.py` is byte-identical to main
  (this branch's only `main.py` changes are the contract import and the
  mastering block), so #77's Edge evidence stands; the workflow's own bounded
  free probe still runs as part of its job.
- **Phase 6 Writer/provider regression** — carried from #78, re-verified locally.
- **Phase 7 adversarial review** — DONE: ten named tests, plus true-peak
  awareness and the master's own peak verification.
- **Phase 8 CI** — `test` + `factory-proof` + `production-realism-proof` all
  green on one exact SHA, with the artifact downloaded and independently probed.

## Local proof
62 CI checks registered; all suites green at zero provider cost.

## Exact next action
PR #79 is a **draft** and stays that way: merging is outside this mission's
boundary. The decision now belongs to a human. If more confidence is wanted
before merge, the cheapest useful thing is another `production-realism-proof`
run on the certified SHA — it costs nothing (zero provider calls) and it is
exactly what caught the true-peak defect.

## Backlog (do not overstate)
C7 — complete on this branch pending release proof. **C8 — CLOSED**: the
downstream factory proof now runs at production realism, green on an exact SHA
with a probed artifact. **S9 — PARTIAL**: capability + health closed,
cost-aware LLM routing still OPEN and deliberately not attempted here.
A6 parity holds structurally — `_mix_final` has exactly one call site, inside
the `_finish_assembly` the repair controller is handed, and the controller
contains no ffmpeg of its own, so a repaired artifact cannot be mastered
differently from the original.

---

# BLOCKER — production-realism audio delivery — **CLOSED**

**Closed on `e86f930`**: `test`, `factory-proof` and `production-realism-proof`
all green on that exact SHA, and the artifact was downloaded and independently
probed (not inferred from the tick).

The diagnosis below is preserved because the fix it led to was NOT the one it
proposed, and because closing it exposed a SECOND defect the first green run had
hidden — see "The second defect" below. Read both before touching delivery audio.

Everything else in the realism proof works on the integrated head: Piper
SUCCESS, Whisper **57/57** word timings, 1080x1920 scenes, per-scene audio
split, ASS captions, music bed, ducking, mastering, AAC 48 kHz. The artifact is
then rejected by the audio gate for loudness alone.

| exact head | mastering | measured | gate |
|---|---|---|---|
| `ec2a649` | single loudnorm `TP=-2.5` | **-16.42 LUFS** | outside [-16.0, -11.5] |
| `cab66a8` | loudnorm `TP=-1.5` + `alimiter -2.5 dBFS` | **-16.26 LUFS** | outside, by 0.26 dB |

True peak is NOT the problem any more; the decoupled limiter fixed that. The
remaining gap is integrated loudness undershooting the -14 target.

## What is established

- Single-pass loudnorm in dynamic mode **systematically undershoots** its
  integrated target, and the tighter its true-peak argument, the worse:
  measured ~0.2 dB per 0.5 dB of TP tightening on synthetic mixes, ~2.4 dB on
  real Piper speech.
- Decoupling helped and is strictly better on both axes (see the commit), but
  only bought 0.16 dB of the 0.42 dB needed.
- Two-pass loudnorm with `linear=true` was measured and **rejected on its own**:
  linear mode does not limit, so it pushed the decoded peak to +0.06 dBTP.

## The leading hypothesis was tested and REJECTED

The proposed fix above was two-pass loudnorm for loudness only, with the
`alimiter` owning the peak. It was built and measured against a mix whose LRA
(7.2) matches real narration, and it does not clear the gate. Decoded AAC:

| candidate | decoded LUFS | decoded TP | verdict |
|---|---|---|---|
| 1-pass loudnorm + limiter (the shipped blocker) | -16.97 | -1.37 | FAIL |
| **2-pass `measured_*` + limiter (`linear=true`)** | **-16.18** | -2.12 | **FAIL** |
| 2-pass `measured_*` + limiter (`linear=false`) | -16.18 | -2.12 | FAIL |
| single corrective gain + limiter | -15.62 | -1.97 | pass, +0.38 dB |
| **loop-closed gain after limiting** | **-14.87** | **-1.80** | **PASS, +1.13 dB** |

Two-pass improves loudnorm's OWN accuracy by ~0.8 dB, but the miss on realistic
material is ~2.4 dB and the limiter then costs another 0.4-1.6 dB depending on
how peaky the content is. It was never going to be enough, and its 0.18 dB
shortfall would have looked like bad luck rather than a wrong model.

Stage-boundary measurement is what settled it: the loss is inside `loudnorm`
(2.4 dB), not the limiter (0.36 dB) or the AAC encode (0.16 dB).

## What was actually built

`delivery_master.master_audio()` — a measured loop, not a filter string:

1. `loudnorm` for loudness range control and a first approximation;
2. measure what the signal ACTUALLY is;
3. corrective gain + `alimiter` (bounded at 12 dB);
4. measure AGAIN, because the limiter itself costs loudness;
5. residual gain + `alimiter` (bounded at 6 dB), closing the loop against the
   LIMITED signal.

Step 4-5 is the difference between +0.38 dB and +1.13 dB of floor margin. Across
three mixes: dynamic -14.87, loud -14.34, quiet -14.24 — content-independent,
which a single correction is not.

Sequencing lives in `delivery_master.py`, not `delivery_contract.py`: mastering
has to MEASURE and act, which is execution, and forcing it into the contract
would break the leaf role that exists to stop the import cycle. It imports the
contract and nothing else — deliberately not `quality_audio_qa`, so it carries
its own small probe rather than depending on the module that judges it.

**One implementation, three consumers.** `main.py`, the factory proof and the
realism proof (via `QDF._mix_final`) all mix to audio, call `master_audio`, then
mux. A test asserts they resolve the same function object; another stubs it out
and proves neither path falls back to a filter string of its own.

**No gate was touched.** `LUFS_MIN = -16.0`, `LUFS_MAX = -11.5` and
`TRUE_PEAK_MAX_DB = -0.5` are unchanged, and a test moves the master target and
asserts the gate's verdict does NOT follow it. The realism proof now goes
further than the gate: it reports the margin to every edge and FAILS a result
that only barely passes (`MIN_DELIVERY_MARGIN_DB = 0.5`), because an artifact
that clears the floor by 0.05 dB is as fragile as the one that missed it by 0.26
and shows the same green tick.

## The second defect — found by re-running, not by the first green tick

The loudness fix went green on `b7a02ad`: −14.57 LUFS, −1.74 dBTP, all three
workflows passing. The next commit changed **two docstrings and nothing else**,
and the realism proof FAILED: **true peak −0.0 dBTP** against the −0.5 ceiling.
Same code, 1.7 dB apart, one run later. Certifying on that first green run —
which was the plan — would have shipped a peak ceiling that held by luck.

Two compounding causes, both measured on the real Piper-over-bed audio:

1. **`alimiter` bounds the SAMPLE peak; the gate measures the TRUE peak.**
   Between samples a limited signal reconstructs higher than any sample in it,
   and the gap grows with density. At a −2.5 dB target it delivered −2.42 on the
   real mix and **−1.60** when pushed 4 dB hotter: the limiter missing its own
   target by 0.9 dB.
2. **AAC coding error at 128 kbit/s** pushed the decoded peak back up +0.23 dB
   typically and **+1.72 dB** on dense material — enough variance to consume the
   whole 2.0 dB reserve by itself.

0.9 + 1.72 against 2.0 dB of reserve is −0.0 dBTP. The arithmetic accounts for
the failure exactly, and **neither term appeared in any report**: the master
reported the loudness it achieved and never the peak.

Fixes, each measured, none of them a relaxed gate:
- limiting runs at **192 kHz** and returns to 48, landing the true peak within
  0.01 dB of target on every mix tested;
- **192 kbit/s** delivery, where coding error is +0.04…+0.50 dB instead of
  +0.23…+1.72 (the same reasoning that replaced 96 with 128, applied to a
  measurement that has since got more honest);
- the master **reads back the peak it achieved**, trims if over target, and
  RAISES rather than handing the encoder a signal that cannot hold the ceiling;
- `mastered_true_peak_db` is in the master report, so the next failure of this
  kind is visible in the artifact rather than only in the gate's verdict.

A previously-passing assertion — "128 kbit/s is sufficient" — was measured on
the factory fixture and disproven by real content. It was corrected, not left
green. **Green and wrong is the failure mode this whole seam exists to kill.**

## Closure evidence (`e86f930`, independently probed)

| | before | after |
|---|---|---|
| integrated loudness | −16.26 LUFS FAIL | **−14.59 LUFS** |
| true peak | −0.0 dBTP FAIL | **−2.40 dBTP** |
| floor margin | −0.26 (outside) | **+1.41 dB** |
| peak margin | −0.50 (outside) | **+1.90 dB** |

Master report from the artifact: loudnorm landed −15.83 (1.83 dB short of its
own target), +1.83 → limiter → −15.06 (limiter cost 0.77 dB), +1.06 residual →
−14.59 mastered at **exactly −2.50 dBTP**, `peak_trim_db: 0.0` (oversampled
limiting needed no correction), decoding to −14.59 / −2.40 — **0.10 dB** of AAC
overshoot where 128 kbit/s had produced up to 1.72.

Offline, through the real production chain across a 13 dB input range:

| source | pre-encode TP | decoded LUFS | decoded TP | floor | peak |
|---|---|---|---|---|---|
| real | −2.50 | −14.19 | −2.39 | +1.81 | +1.89 |
| hot (+4 dB) | −2.49 | −14.01 | −2.47 | +1.99 | +1.97 |
| quiet (−9 dB) | −2.50 | −14.19 | −2.36 | +1.81 | +1.86 |

Rest of the artifact: 1080×1920 h264, AAC 48 kHz / 210 kbit/s mono, 23.1 s,
Piper narration, **57/57** Whisper word timings, 47 caption dialogue lines, real
music bed with sidechain duck, `provider_calls_made: 0`, `network_calls_made: 0`,
and a viewer-facing proof frame with the karaoke caption burned in at canvas.

## Adversarial coverage for this architecture

`tests/test_delivery_mastering_adversarial.py` — ten named rot paths, each one
MOVED and the constructed behaviour asserted to move with it (or, for the gates,
pointedly not to): production/proof drift, a hard-coded loudness target, a
hard-coded true-peak target, a weakened QA ceiling, analysis-pass coupling, two
measurements reading the same file, a limiter vanishing from a gain stage, a
repaired assembly finished differently, sample-rate drift, bitrate drift.

**Do not infer media success from a green tick, and do not infer it from ONE
green tick either.** The 96 kHz defect passed CI for months and was found by
probing; the true-peak defect passed one full CI cycle and was found only
because a docstring commit forced a second run. Both lessons are the same size.

## Also proven on an earlier head (`cab66a8`)

Edge voice probe PASSED: `en-GB-RyanNeural`, `edge_boundary_counts_returned: [0]`,
`timing_source: faster_whisper_fallback`, 40/40 words, `provider_calls_made: 0`,
`publishing_side_effects: 0`. Phase 5 evidence re-confirmed post-integration.

`tests` workflow (zero-provider `test` + `factory-proof`) is green on the head
before this one; re-confirm on whatever head fixes the loudness.
