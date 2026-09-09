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

## Audio contract architecture (final)

`delivery_contract.py` (leaf) owns: `DELIVERY_SAMPLE_RATE` 48000,
`DELIVERY_AUDIO_BITRATE` "128k", `DELIVERY_INTEGRATED_LUFS` -14,
`DELIVERY_TRUE_PEAK_TARGET_DB` **-2.5**, `QA_TRUE_PEAK_CEILING_DB` **-0.5**,
`delivery_loudnorm_filter()`, `delivery_audio_encode_args()`.

Consumers import, never restate: `main.py` (both mastering branches),
`quality_downstream_factory_proof._mix_final` (both branches),
`quality_audio_qa` (re-exports for existing callers), and the realism proof via
`QDF._mix_final`.

**The QA ceiling is unchanged at -0.5 dBTP.** Headroom came from lowering the
master target, never from relaxing the gate: 2.0 dB reserved, because real
speech over a music bed overshot ~1.8 dB through AAC where synthetic tones
overshot ~0.01 dB.

`analyze_loudness` deliberately keeps its own literal args — it is a MEASUREMENT
pass reading `input_*`, which do not depend on target parameters. A test guards
that decision in both directions.

## Proof the target is load-bearing (not grep)

`tests/test_delivery_contract_load_bearing.py` calls the **real** `_mix_final`
with `run()` intercepted and the music bed stubbed, captures the constructed
ffmpeg command, moves the shared constant to -7.25 and asserts the captured
command moves with it. Plus: no active finishing path hard-codes a delivery
target; the renderer holds no literal filter; measurement stays decoupled;
target-to-ceiling gap >= 1.5 dB.

---

## Status

- **Phase 1 integration** — DONE (branch from #78 head + #77's 4 harness files).
- **Phase 2 contract** — DONE (`delivery_contract.py`, all 4 delivery sites).
- **Phase 3 load-bearing proof** — DONE.
- **Phase 4 production-realism** — pending exact-head CI; Piper/Whisper are not
  installed locally, so the proof runs in `production_realism_proof.yml`, which
  auto-triggers on `pull_request` for the paths this branch changes.
- **Phase 5 Edge** — Edge/Whisper routing in `main.py` is byte-identical to main
  (this branch's only `main.py` changes are the contract import and the
  mastering block), so #77's Edge evidence stands; the workflow's own bounded
  free probe still runs as part of its job.
- **Phase 6 Writer/provider regression** — carried from #78, re-verified locally.
- **Phase 7 adversarial review** — pending.
- **Phase 8 CI** — pending.

## Local proof
61 CI checks registered; all suites green; **1598 zero-provider checks**.

## Exact next action
Open the draft integration PR (supersedes #77 and #78 if evidence passes),
obtain exact-head CI for `tests.yml` (test + factory-proof) AND
`production_realism_proof.yml`, then DOWNLOAD and probe the realism artifact —
resolution, codecs, 48 kHz, decoded true peak <= -0.5 dBTP, Whisper alignment
count, caption evidence. Do not infer media success from a green tick.

## Backlog (do not overstate)
C7 — complete on this branch pending release proof. C8 — production-realism
extension is the open half. **S9 — PARTIAL**: capability + health closed,
cost-aware LLM routing still OPEN and deliberately not attempted here.

---

# OPEN BLOCKER — production-realism loudness (as of `cab66a8`)

**Status: NOT merge-ready. One measured, well-diagnosed problem remains.**

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

## Exact next action (the synthesis, untried)

Two-pass loudnorm **for loudness only**, with the `alimiter` still enforcing the
peak ceiling. The earlier objection to two-pass was that linear mode does not
limit — that objection is neutralised now that a dedicated limiter owns the
peak. Expected: accurate -14 LUFS *and* a guaranteed ceiling, each stage doing
one job.

Implementation shape: `_mix_final` (and `main.py`'s mastering block, which must
stay identical or the contract diverges again) build the mixed audio, measure it
with the existing analysis pass, then apply
`loudnorm=...:measured_I=..:measured_TP=..:measured_LRA=..:measured_thresh=..:offset=..:linear=true,alimiter=...`.
That is a real restructure of both finishing paths, not a constant change.

**Do NOT** resolve this by widening `LUFS_MIN`, lowering the QA ceiling, or
relaxing any gate. The gate is correct; the mastering is what is inaccurate.

## Also proven on this head (`cab66a8`)

Edge voice probe PASSED: `en-GB-RyanNeural`, `edge_boundary_counts_returned: [0]`,
`timing_source: faster_whisper_fallback`, 40/40 words, `provider_calls_made: 0`,
`publishing_side_effects: 0`. Phase 5 evidence re-confirmed post-integration.

`tests` workflow (zero-provider `test` + `factory-proof`) is green on the head
before this one; re-confirm on whatever head fixes the loudness.
