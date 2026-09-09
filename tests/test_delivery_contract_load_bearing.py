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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import delivery_contract as DC
import quality_downstream_factory_proof as QDF

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _capture_factory_mix(tp_target):
    """Call the factory's REAL _mix_final and capture the command it builds.

    No ffmpeg runs: `run` is intercepted. The music bed is stubbed empty so the
    deterministic no-bed branch is taken.
    """
    captured = []
    orig_run, orig_bed, orig_vibe = QDF.run, QDF.legacy._ensure_music_bed, QDF.legacy._apply_vibe
    orig_tp = DC.DELIVERY_TRUE_PEAK_TARGET_DB
    QDF.run = lambda cmd: captured.append(list(cmd))
    QDF.legacy._ensure_music_bed = lambda duration: ""
    QDF.legacy._apply_vibe = lambda vibe: None
    DC.DELIVERY_TRUE_PEAK_TARGET_DB = tp_target
    try:
        QDF._mix_final(Path("in.mp4"), Path("out.mp4"), 16.0)
    finally:
        QDF.run, QDF.legacy._ensure_music_bed, QDF.legacy._apply_vibe = orig_run, orig_bed, orig_vibe
        DC.DELIVERY_TRUE_PEAK_TARGET_DB = orig_tp
    check(len(captured) == 1, f"exactly one mastering command was built (got {len(captured)})")
    return " ".join(captured[0])


def test_changing_the_shared_target_changes_the_FACTORY_command():
    baseline = _capture_factory_mix(DC.DELIVERY_TRUE_PEAK_TARGET_DB)
    check("limit=0.7499" in baseline,
          "the factory's real command carries the shared peak target as a limiter")
    moved = _capture_factory_mix(-7.25)
    check("limit=0.4340" in moved,
          "moving the shared constant moves the factory's constructed filter -- "
          "the target is wired in, not merely declared beside it")
    check("alimiter" in moved,
          "and the peak ceiling is enforced by a dedicated limiter stage")
    check("-ar 48000" in moved and "-b:a 128k" in moved,
          "the same command still carries the shared rate and bitrate")


def test_changing_the_shared_target_changes_the_RENDERER_filter():
    """main.py's mastering filter is built by the same function.

    main._render's mastering block cannot be invoked without a full render, so
    the binding is proven at the boundary it actually uses: the renderer holds no
    literal filter, and the function it calls responds to the constant.
    """
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("_LOUDNORM = delivery_master_filter()" in src,
          "the renderer's mastering filter comes from the shared contract")
    check(not re.search(r'_LOUDNORM\s*=\s*["\']loudnorm', src),
          "the renderer holds no literal loudnorm string of its own")

    orig = DC.DELIVERY_TRUE_PEAK_TARGET_DB
    try:
        DC.DELIVERY_TRUE_PEAK_TARGET_DB = -9.5
        check("limit=0.3350" in DC.delivery_master_filter(),
              "the function the renderer calls tracks the shared constant "
              "(-9.5 dBFS -> limit=0.3350)")
    finally:
        DC.DELIVERY_TRUE_PEAK_TARGET_DB = orig
    check("limit=0.7499" in DC.delivery_master_filter(), "and is restored afterwards")


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
    test_changing_the_shared_target_changes_the_RENDERER_filter()
    test_no_active_finishing_path_still_hard_codes_a_delivery_target()
    test_the_measurement_pass_is_deliberately_not_the_delivery_filter()
    test_headroom_is_reserved_between_the_target_and_the_gate()
    print("delivery contract load-bearing tests: PASS")
