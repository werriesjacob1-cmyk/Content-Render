#!/usr/bin/env python3
"""The delivery mastering target must be LOAD-BEARING, not merely declared.

The defect this exists to prevent, verbatim from history: a change added
``DELIVERY_TRUE_PEAK_TARGET_DB = -2.5`` plus a ``delivery_loudnorm_filter()``
helper to the QA module and declared that the renderer and the factory now
shared one contract. Neither called it. ``main.py`` imported only the rate and
bitrate, and BOTH finishing paths still carried a hard-coded
``loudnorm=I=-14:TP=-1.5:LRA=11``. The constant was inert, so the artifact that
appeared to validate -2.5 dBTP had in fact been mastered at -1.5.

Grep alone cannot catch that -- the constant existed and the helper existed.
So these tests CHANGE the shared target and assert the ffmpeg commands the
consumers actually construct change with it.

Zero network, zero providers, no ffmpeg is executed: the commands are captured,
not run.
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
import quality_downstream_factory_proof as QDF

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# What the stubbed probe reports the intermediate signal measures. Any value
# below the target works; -20 makes both corrective gains non-zero, so a stage
# that silently stopped applying gain would show up as a missing volume= filter.
# The stubbed true peak sits exactly ON target so the master's corrective peak
# trim does not fire -- these tests are about the ordinary path.
STUB_MEASURED_LUFS = -20.0


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _capture_factory_mix(tp_target):
    """Call the factory's REAL _mix_final and capture every command it builds.

    No ffmpeg runs. Both execution seams are intercepted -- the factory's own
    `run` and the shared master's `_run` -- and the loudness probe is stubbed,
    because the master is a MEASURED loop and would otherwise need real audio.
    The music bed is stubbed empty so the deterministic no-bed branch is taken.
    """
    captured = []
    orig = (QDF.run, QDF.legacy._ensure_music_bed, QDF.legacy._apply_vibe,
            DM._run, DM._measure, DC.DELIVERY_TRUE_PEAK_TARGET_DB)
    QDF.run = lambda cmd: captured.append(list(cmd))
    QDF.legacy._ensure_music_bed = lambda duration: ""
    QDF.legacy._apply_vibe = lambda vibe: None
    DM._run = lambda cmd: captured.append(list(cmd))
    DM._measure = lambda path: (STUB_MEASURED_LUFS, DC.DELIVERY_TRUE_PEAK_TARGET_DB)
    DC.DELIVERY_TRUE_PEAK_TARGET_DB = tp_target
    try:
        # A real temp dir: _mix_final and master_audio both mkdir their scratch
        # space, and a proof that leaves master_work/ in the repo is its own bug.
        with tempfile.TemporaryDirectory() as td:
            QDF._mix_final(Path(td) / "in.mp4", Path(td) / "out.mp4", 16.0)
    finally:
        (QDF.run, QDF.legacy._ensure_music_bed, QDF.legacy._apply_vibe,
         DM._run, DM._measure, DC.DELIVERY_TRUE_PEAK_TARGET_DB) = orig
    return [" ".join(c) for c in captured]


def test_changing_the_shared_target_changes_the_FACTORY_command():
    baseline = _capture_factory_mix(DC.DELIVERY_TRUE_PEAK_TARGET_DB)
    check(any("limit=0.7499" in c for c in baseline),
          "the factory's real pipeline carries the shared peak target as a limiter")
    moved = _capture_factory_mix(-7.25)
    check(any("limit=0.4340" in c for c in moved),
          "moving the shared constant moves the constructed filter -- the target "
          "is wired in, not merely declared beside it")
    check(not any("limit=0.7499" in c for c in moved),
          "and NO command keeps the old value, so nothing holds a private copy")
    limited = [c for c in moved if "alimiter" in c]
    check(len(limited) == 2,
          f"the peak ceiling is enforced by a dedicated limiter on every gain "
          f"stage, including the final one ({len(limited)} found)")
    delivery = [c for c in moved if "-c:a aac" in c]
    check(len(delivery) == 1 and "-ar 48000" in delivery[0]
          and f"-b:a {DC.DELIVERY_AUDIO_BITRATE}" in delivery[0],
          "the one delivery encode still carries the shared rate and bitrate")


def test_the_factory_mix_is_a_measured_loop_not_a_single_graph():
    """The sequence, not just the constants, is what fixed the loudness blocker.

    A single filter graph cannot correct loudnorm's error because correcting it
    requires measuring its output. On realistic narration that error was ~2.4 dB
    and the artifact decoded at -16.26 LUFS, outside the gate's -16.0 floor.
    """
    cmds = _capture_factory_mix(DC.DELIVERY_TRUE_PEAK_TARGET_DB)
    check(len(cmds) == 5,
          f"mix, three master stages and mux are five distinct commands (got {len(cmds)})")
    check("loudnorm" not in cmds[0] and "alimiter" not in cmds[0],
          "the mix stage does no mastering -- its output is what gets measured")
    check("loudnorm=I=-14" in cmds[1],
          "stage 1 is loudness/LRA control at the shared integrated target")
    gains = [c for c in cmds if "volume=" in c]
    check(len(gains) == 2,
          f"two corrective gains are applied: one against loudnorm's output and "
          f"one against the LIMITED signal (got {len(gains)})")
    check("volume=6.00dB" in gains[0] and "volume=6.00dB" in gains[1],
          "each gain is computed from the measurement, not hard-coded "
          f"(probe stubbed at {STUB_MEASURED_LUFS} vs a -14 target)")


def test_the_renderer_uses_the_same_shared_master():
    """main.py's finishing path calls the same function, not a lookalike.

    main._render's mastering block cannot be invoked without a full render, so
    the binding is proven at the boundary it actually uses: the renderer imports
    and calls the shared master, holds no filter string of its own, and the
    function it calls is the same object the factory pipeline above exercised.
    """
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("from delivery_master import master_audio" in src,
          "the renderer takes the mastering sequence from the shared module")
    check("master_audio(_mix_wav, _mastered, WORK)" in src,
          "and calls it on the mix it just built, rather than mastering in-graph")
    check(not re.search(r'["\']loudnorm=', src),
          "the renderer holds no literal loudnorm string of its own")
    check(QDF.DM.master_audio is DM.master_audio,
          "the factory proof resolves the same master_audio object the renderer "
          "imports -- one implementation, not two that look alike")

    orig = DC.DELIVERY_TRUE_PEAK_TARGET_DB
    try:
        DC.DELIVERY_TRUE_PEAK_TARGET_DB = -9.5
        check("limit=0.3350" in DC.delivery_limiter_filter(),
              "the limiter that master_audio applies tracks the shared constant "
              "(-9.5 dBFS -> limit=0.3350)")
    finally:
        DC.DELIVERY_TRUE_PEAK_TARGET_DB = orig
    check("limit=0.7499" in DC.delivery_limiter_filter(), "and is restored afterwards")


def test_no_active_finishing_path_still_hard_codes_a_delivery_target():
    """The exact shape of the original defect: a literal beside the constant."""
    offenders = []
    for path in sorted(ROOT.glob("*.py")):
        if path.name in {"delivery_contract.py"}:
            continue  # its docstring quotes the historical literals on purpose
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"loudnorm=I=-14:TP=[-\d.]+:LRA=\d+", src):
            line = src[:m.start()].count("\n") + 1
            context = src.splitlines()[line - 1]
            # The QA measurement pass legitimately carries inert target args --
            # it reads input_* values, which do not depend on them.
            if "print_format=json" in context:
                continue
            offenders.append(f"{path.name}:{line}")
    check(not offenders,
          f"no active finishing path hard-codes a delivery loudnorm target "
          f"(offenders: {offenders})")


def test_the_measurement_pass_is_deliberately_not_the_delivery_filter():
    """Guard the opposite mistake: 'fixing' the analysis filter to match.

    analyze_loudness reads input_i/input_tp, which describe the signal as it
    arrived and are unaffected by the target arguments. Wiring the delivery
    target into it would make changing the master silently change the
    measurement command while measuring exactly the same thing.
    """
    src = (ROOT / "quality_audio_qa.py").read_text(encoding="utf-8")
    body = src.split("def analyze_loudness(", 1)[1].split("\ndef ", 1)[0]
    # Comments are stripped first: the assertion is that no CALL is made, and the
    # comment explaining why deliberately names the function it must not call.
    code = "\n".join(re.sub(r"#.*$", "", ln) for ln in body.splitlines())
    check("print_format=json" in code, "the analysis pass is still an analysis pass")
    check("delivery_master_filter()" not in code,
          "measurement is NOT built from the delivery target -- they are different jobs")
    check("MEASUREMENT, not delivery" in body,
          "and the reason is stated where the next reader will see it")


def test_headroom_is_reserved_between_the_target_and_the_gate():
    """The gap between master target and QA ceiling IS the codec headroom.

    Real speech over a music bed overshot ~1.8 dB through AAC where synthetic
    tones overshot ~0.01 dB, so the target must sit meaningfully below the gate.
    """
    import quality_audio_qa as AQA
    headroom = AQA.TRUE_PEAK_MAX_DB - DC.DELIVERY_TRUE_PEAK_TARGET_DB
    check(headroom >= 1.5,
          f"at least 1.5 dB is reserved for codec overshoot (got {headroom:.2f} dB)")
    check(AQA.TRUE_PEAK_MAX_DB == -0.5,
          "the QA ceiling itself is UNCHANGED at -0.5 dBTP -- headroom was added "
          "by lowering the master target, never by relaxing the gate")
    check(DC.QA_TRUE_PEAK_CEILING_DB == AQA.TRUE_PEAK_MAX_DB,
          "the gate's ceiling and the contract's stated ceiling are one value")


if __name__ == "__main__":
    test_changing_the_shared_target_changes_the_FACTORY_command()
    test_the_factory_mix_is_a_measured_loop_not_a_single_graph()
    test_the_renderer_uses_the_same_shared_master()
    test_no_active_finishing_path_still_hard_codes_a_delivery_target()
    test_the_measurement_pass_is_deliberately_not_the_delivery_filter()
    test_headroom_is_reserved_between_the_target_and_the_gate()
    print("delivery contract load-bearing tests: PASS")
