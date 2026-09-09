#!/usr/bin/env python3
"""Ten named ways the delivery-audio architecture could silently rot, each tried.

Every one of these has a real precedent in this repo, and every one of them was
invisible to a green CI tick at the time:

  * a delivery constant was declared shared while every consumer kept a private
    copy of the string, so the constant was inert and the artifact that
    "proved" it had been mastered at the OLD value;
  * ``loudnorm`` resamples to 192 kHz internally and never restores the rate, so
    with no ``-ar`` every render shipped 96 kHz while the gate RECORDED
    ``sample_rate: 96000`` in its own report and passed it;
  * pinning the rate then exposed a starved bitrate that overshot the peak
    ceiling, proving rate and bitrate are one decision, not two;
  * mastering inside a single filter graph could not correct loudnorm's own
    error -- correcting it requires measuring its output -- and the artifact
    decoded at -16.26 LUFS against a -16.0 floor.

So these are adversarial: each test MOVES something and asserts the constructed
behaviour moves with it (or, for the gates, pointedly does NOT). Grep cannot
tell a load-bearing constant from a decorative one; changing it and watching the
command can.

Zero network, zero providers, zero ffmpeg: commands are captured, not executed.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import delivery_contract as DC
import delivery_master as DM
import quality_audio_qa as AQA
import quality_downstream_factory_proof as QDF
import quality_repair_controller as RC

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STUB_MEASURED_LUFS = -20.0


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _capture(**contract_overrides):
    """Run the REAL finishing path with both execution seams intercepted.

    Returns (commands, measured_paths): the ffmpeg commands the pipeline built,
    and the files its loudness probe was pointed at -- the latter is what makes
    "the loop measured the same file twice" detectable.
    """
    cmds: list[str] = []
    measured: list[str] = []
    saved_contract = {k: getattr(DC, k) for k in contract_overrides}
    saved = (QDF.run, QDF.legacy._ensure_music_bed, QDF.legacy._apply_vibe,
             DM._run, DM.measure_integrated_lufs)

    def _probe(path):
        measured.append(str(path))
        return STUB_MEASURED_LUFS

    QDF.run = lambda cmd: cmds.append(" ".join(str(x) for x in cmd))
    QDF.legacy._ensure_music_bed = lambda duration: ""
    QDF.legacy._apply_vibe = lambda vibe: None
    DM._run = lambda cmd: cmds.append(" ".join(str(x) for x in cmd))
    DM.measure_integrated_lufs = _probe
    for key, value in contract_overrides.items():
        setattr(DC, key, value)
    try:
        with tempfile.TemporaryDirectory() as td:
            QDF._mix_final(Path(td) / "in.mp4", Path(td) / "out.mp4", 16.0)
    finally:
        (QDF.run, QDF.legacy._ensure_music_bed, QDF.legacy._apply_vibe,
         DM._run, DM.measure_integrated_lufs) = saved
        for key, value in saved_contract.items():
            setattr(DC, key, value)
    return cmds, measured


def _delivery_cmd(cmds):
    hits = [c for c in cmds if "-c:a aac" in c]
    check(len(hits) == 1, f"exactly one command encodes delivery audio ({len(hits)})")
    return hits[0]


# 1 ----------------------------------------------------------------------------
def test_1_production_and_proof_cannot_drift_into_two_implementations():
    """The renderer and the proofs must be the SAME function, not lookalikes.

    This is the defect that started all of it: two paths that agreed in prose
    and diverged in code, with the proof certifying the path nobody shipped.
    """
    sentinel_calls = []
    orig = DM.master_audio
    DM.master_audio = lambda src, dest, work: sentinel_calls.append(str(src)) or {}
    try:
        cmds, _ = _capture()
    finally:
        DM.master_audio = orig
    check(len(sentinel_calls) == 1,
          "the factory path calls the shared master_audio -- swapping it out "
          "stops mastering entirely, so it holds no private copy")
    check(not any("alimiter" in c for c in cmds),
          "and with the shared master stubbed, NO mastering filter is built "
          "locally as a fallback")

    src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("from delivery_master import master_audio" in src
          and "master_audio(_mix_wav, _mastered, WORK)" in src,
          "the renderer imports and calls that same function")
    check(QDF.DM.master_audio is DM.master_audio,
          "and both resolve to one object, not two copies of a sequence")


# 2 ----------------------------------------------------------------------------
def test_2_a_hard_coded_loudness_target_cannot_return():
    moved, _ = _capture(DELIVERY_INTEGRATED_LUFS=-9)
    check(any("loudnorm=I=-9:" in c for c in moved),
          "moving the shared integrated target moves the constructed loudnorm")
    check(not any("I=-14" in c for c in moved),
          "and NO command retains the old -14, which is exactly how the "
          "true-peak target went inert while looking shared")
    # Probe stubbed at -20: a -14 target needs +6.00 dB, a -9 target needs
    # +11.00 dB. The gain moving is what proves the correction is computed from
    # the contract rather than from a frozen number that merely agrees with it.
    check(any("volume=11.00dB" in c for c in moved),
          "the corrective gain is computed against the moved target too, not "
          "against a frozen -14")


# 3 ----------------------------------------------------------------------------
def test_3_a_hard_coded_true_peak_target_cannot_return():
    moved, _ = _capture(DELIVERY_TRUE_PEAK_TARGET_DB=-7.25)
    check(any("limit=0.4340" in c for c in moved),
          "moving the shared peak target moves the limiter amplitude")
    check(not any("limit=0.7499" in c for c in moved),
          "and no stage keeps the old amplitude")


# 4 ----------------------------------------------------------------------------
def test_4_the_qa_gates_are_not_weakened_and_do_not_follow_the_master():
    """The gate must not soften to accommodate whatever the master produces.

    Headroom is bought by lowering the MASTER target, never by raising the
    ceiling. If the gate tracked the master, every mastering regression would
    silently redefine "acceptable" instead of failing.
    """
    check(AQA.TRUE_PEAK_MAX_DB == -0.5, "the true-peak ceiling is still -0.5 dBTP")
    check(AQA.LUFS_MIN == -16.0 and AQA.LUFS_MAX == -11.5,
          "the integrated-loudness window is still [-16.0, -11.5]")

    def _verdict():
        media = {"duration_s": 16.0,
                 "audio": {"codec_name": "aac", "sample_rate": 48000, "channels": 1}}
        loudness = {"integrated_lufs": -14.0, "true_peak_db": -0.4, "lra_lu": 2.1}
        return AQA.evaluate_metrics(media, loudness, {"long_silence_ratio": 0.0,
                                                     "long_silence_seconds": 0}, 45)

    check(_verdict()["mechanical_pass"] is False,
          "an artifact at -0.4 dBTP fails the gate")
    orig = DC.DELIVERY_TRUE_PEAK_TARGET_DB
    try:
        DC.DELIVERY_TRUE_PEAK_TARGET_DB = -0.1
        check(_verdict()["mechanical_pass"] is False,
              "and STILL fails after the master target is loosened -- the gate "
              "is independent of what the renderer happens to aim for")
    finally:
        DC.DELIVERY_TRUE_PEAK_TARGET_DB = orig


# 5 ----------------------------------------------------------------------------
def test_5_the_analysis_pass_stays_decoupled_from_the_delivery_target():
    """The opposite mistake: 'tidying' the measurement to match the master.

    analyze_loudness reads input_i/input_tp/input_lra, which describe the signal
    as it arrived and are unaffected by the target arguments. Wiring the
    delivery target in would change the command while measuring the same thing.
    """
    seen: list[str] = []

    class _Proc:
        stderr = ('{"input_i":"-14.0","input_tp":"-1.5","input_lra":"2.0",'
                  '"input_thresh":"-24.0"}')

    orig_run = AQA._run
    AQA._run = lambda cmd, timeout=None: (seen.append(" ".join(cmd)), _Proc())[1]
    orig_target = DC.DELIVERY_INTEGRATED_LUFS
    try:
        AQA.analyze_loudness("x.mp4")
        DC.DELIVERY_INTEGRATED_LUFS = -9
        AQA.analyze_loudness("x.mp4")
    finally:
        AQA._run = orig_run
        DC.DELIVERY_INTEGRATED_LUFS = orig_target
    check(len(seen) == 2 and seen[0] == seen[1],
          "moving the delivery target does not move the measurement command")
    check("print_format=json" in seen[0],
          "and it is still an analysis pass, not a delivery filter")

    # Same probe, same rule, in the production-side module.
    dm_src = (ROOT / "delivery_master.py").read_text(encoding="utf-8")
    probe = dm_src.split("def measure_integrated_lufs(", 1)[1].split("\ndef ", 1)[0]
    check("DELIVERY_INTEGRATED_LUFS" not in probe and "DC." not in probe,
          "delivery_master's own probe is likewise not wired to the target")


# 6 ----------------------------------------------------------------------------
def test_6_each_measurement_reads_the_stage_before_it():
    """The loop is only closed if pass 2 measures what pass 1 actually wrote.

    Measuring the same intermediate twice would leave the residual correction
    computing against a signal the limiter had not touched -- which is precisely
    the 0.75 dB of margin that separates this architecture from the previous
    one, and it would still look like a working loop from the outside.
    """
    cmds, measured = _capture()
    check(len(measured) == 3,
          f"three measurements: loudnorm output, limited signal, result ({len(measured)})")
    check(len(set(measured)) == 3,
          f"and all three read DIFFERENT files, not the same one repeatedly "
          f"({measured})")
    written = [c.split()[-1] for c in cmds]
    for i, path in enumerate(measured):
        check(path in written,
              f"measurement {i + 1} reads a file this pipeline actually wrote")
    check(measured[-1] == written[-2],
          "the final measurement reads the mastered file, taken before the mux "
          "-- so the reported result describes the delivered audio")


# 7 ----------------------------------------------------------------------------
def test_7_the_limiter_cannot_disappear_from_a_gain_stage():
    """Every corrective gain must be limited in the same chain that applies it.

    A gain without a limiter after it is how a loudness fix turns into a clipped
    artifact: the corrective gains here are up to 12 dB, applied precisely
    because the signal measured quiet.
    """
    cmds, _ = _capture()
    gains = [c for c in cmds if "volume=" in c]
    check(len(gains) == 2, f"both corrective gains are present ({len(gains)})")
    for cmd in gains:
        chain = re.search(r"-af (\S+)", cmd)
        check(chain is not None, "the gain is applied through a filter chain")
        check("alimiter=" in chain.group(1),
              f"and that same chain limits it: {chain.group(1)}")
        check(chain.group(1).index("volume=") < chain.group(1).index("alimiter="),
              "with the limiter AFTER the gain, not before it")


# 8 ----------------------------------------------------------------------------
def test_8_a_repaired_assembly_cannot_be_finished_differently():
    """Repair reassembly must go through the one finishing path, or re-QA lies.

    They diverged before: repair re-assembled with a bare concat -- no captions,
    no bed, no mastering -- and was judged by the same gate that demands
    normalized -14 LUFS, so a repaired artifact could never pass.
    """
    qdf_src = (ROOT / "quality_downstream_factory_proof.py").read_text(encoding="utf-8")
    call_sites = [m.start() for m in re.finditer(r"(?<!def )_mix_final\(", qdf_src)]
    check(len(call_sites) == 1,
          f"_mix_final has exactly ONE call site ({len(call_sites)}), so there is "
          "no second finishing path for repair to take")
    finish_start = qdf_src.index("def _finish_assembly(")
    finish_end = qdf_src.index("\n        repair_plan", finish_start)
    check(finish_start < call_sites[0] < finish_end,
          "and that call site is inside _finish_assembly")
    check("assemble=_finish_assembly" in qdf_src,
          "which is exactly what the repair controller is handed")

    rc_src = (ROOT / "quality_repair_controller.py").read_text(encoding="utf-8")
    for banned in ("ffmpeg", "loudnorm", "subprocess", "concat"):
        check(banned not in rc_src,
              f"the repair controller cannot assemble on its own -- no {banned!r}")
    check("assemble" in RC.execute_replacements.__code__.co_varnames,
          "it only ever reassembles through the injected finishing callable")


# 9 ----------------------------------------------------------------------------
def test_9_the_sample_rate_cannot_drift_from_the_gate():
    """96 kHz shipped for months because the renderer and the gate disagreed."""
    moved, _ = _capture(DELIVERY_SAMPLE_RATE=32000)
    check("-ar 32000" in _delivery_cmd(moved),
          "the delivery encode pins whatever rate the contract states")
    check(not any("-ar 48000" in c for c in moved),
          "and no intermediate stage keeps a private 48000 -- the master's own "
          "stages track the contract too")
    check(AQA.MAX_SAMPLE_RATE == DC.DELIVERY_SAMPLE_RATE,
          "the gate's ceiling IS the renderer's target, restored and equal")
    check(AQA.MIN_SAMPLE_RATE <= DC.DELIVERY_SAMPLE_RATE,
          "and the floor does not contradict it")


# 10 ---------------------------------------------------------------------------
def test_10_the_bitrate_cannot_drift_below_what_the_peak_target_needs():
    """Rate and bitrate are ONE decision, pinned by measurement.

    At 48 kHz, 96 kbit/s was bitrate-starved: coding error overshot the limited
    signal by ~1.6 dB and the artifact decoded at +0.07 dBTP, breaching the
    gate's own ceiling. 128 kbit/s landed at -1.49 dB.
    """
    moved, _ = _capture(DELIVERY_AUDIO_BITRATE="64k")
    check("-b:a 64k" in _delivery_cmd(moved),
          "the delivery encode carries the contract's bitrate, not a literal")
    kbps = int(re.sub(r"[^0-9]", "", DC.DELIVERY_AUDIO_BITRATE))
    check(kbps >= 128,
          f"and the restored value ({kbps} kbit/s) is at least the 128 measured "
          "as sufficient to hold the limiter's peak through AAC")
    headroom = AQA.TRUE_PEAK_MAX_DB - DC.DELIVERY_TRUE_PEAK_TARGET_DB
    check(headroom >= 1.5,
          f"with {headroom:.2f} dB reserved for codec overshoot (real speech "
          "over a bed overshot ~1.8 dB where tones overshot ~0.01 dB)")


if __name__ == "__main__":
    test_1_production_and_proof_cannot_drift_into_two_implementations()
    test_2_a_hard_coded_loudness_target_cannot_return()
    test_3_a_hard_coded_true_peak_target_cannot_return()
    test_4_the_qa_gates_are_not_weakened_and_do_not_follow_the_master()
    test_5_the_analysis_pass_stays_decoupled_from_the_delivery_target()
    test_6_each_measurement_reads_the_stage_before_it()
    test_7_the_limiter_cannot_disappear_from_a_gain_stage()
    test_8_a_repaired_assembly_cannot_be_finished_differently()
    test_9_the_sample_rate_cannot_drift_from_the_gate()
    test_10_the_bitrate_cannot_drift_below_what_the_peak_target_needs()
    print("delivery mastering adversarial tests: PASS")
