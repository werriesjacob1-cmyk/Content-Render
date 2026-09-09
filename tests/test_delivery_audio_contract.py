#!/usr/bin/env python3
"""The delivery sample-rate contract: what the renderer ENCODES must equal what
the audio gate ENFORCES, from one constant.

This exists because of a real defect found by probing an actual CI artifact
rather than trusting the workflow's exit code. ffmpeg's loudnorm resamples
internally to 192 kHz and never restores the input rate; with no explicit -ar
the AAC encoder falls back to the nearest rate it supports, 96 kHz. So every
render shipped 96 kHz audio built from a 24 kHz TTS source, spending a fixed
bitrate on an inaudible band. The audio gate recorded sample_rate=96000 in its
own report and passed it, because it only had a FLOOR.

Fixing the rate alone then exposed a second defect, and the measurements are why
both constants are pinned together here:

    48 kHz @  96 kbit/s   TP = +0.07 dB   FAILS the -0.5 dB ceiling
    48 kHz @ 128 kbit/s   TP = -1.49 dB   the loudnorm target, exactly
    96 kHz @  96 kbit/s   TP = -1.50 dB   what shipped

At 48 kHz the encoder was bitrate-starved and its coding error overshot the
limited signal by ~1.6 dB. The 96 kHz encode had hidden that by spending the
same bits above the audible band. So the rate and the bitrate are one decision.

Zero network, zero providers, no ffmpeg: the encode commands are asserted as
source text and the gate is exercised through its pure verdict function.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import delivery_contract as DC
import quality_audio_qa as AQA

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _metrics(sample_rate, **over):
    """A verdict input that is clean apart from whatever the test varies."""
    media = {"duration_s": 16.0,
             "audio": {"codec_name": "aac", "sample_rate": sample_rate, "channels": 1}}
    loudness = {"integrated_lufs": -14.0, "true_peak_db": -1.5, "lra_lu": 2.1}
    silence = {"long_silence_ratio": 0.0, "long_silence_seconds": 0}
    media.update(over)
    return AQA.evaluate_metrics(media, loudness, silence, 45)


def _rate_reasons(verdict):
    return [r for r in verdict["mechanical_reasons"] if "sample rate" in r]


def test_the_delivery_rate_is_a_single_shared_constant():
    check(AQA.DELIVERY_SAMPLE_RATE == 48000,
          "the delivery sample rate is 48 kHz, the standard for social delivery")
    check(AQA.MAX_SAMPLE_RATE == AQA.DELIVERY_SAMPLE_RATE,
          "the gate's ceiling IS the rate the renderer targets, not a second number")
    check(AQA.MIN_SAMPLE_RATE <= AQA.DELIVERY_SAMPLE_RATE,
          "the floor and the target do not contradict each other")


def test_the_gate_accepts_the_rate_the_renderer_actually_produces():
    v = _metrics(AQA.DELIVERY_SAMPLE_RATE)
    check(v["mechanical_pass"] is True,
          "a file encoded at exactly the delivery rate passes the gate")
    check(not _rate_reasons(v), "and it is not failed for its sample rate")
    # 44.1 kHz is a legitimate delivery rate and must not be collateral damage.
    check(_metrics(44100)["mechanical_pass"] is True,
          "44.1 kHz is still accepted -- the ceiling did not become an equality test")


def test_the_exact_shipped_defect_is_now_rejected():
    """96000 is not hypothetical: it is what the CI artifact measured."""
    v = _metrics(96000)
    check(v["mechanical_pass"] is False,
          "96 kHz -- the rate loudnorm actually produced -- now fails the gate")
    reasons = _rate_reasons(v)
    check(reasons, "the failure names the sample rate rather than failing opaquely")
    check("above" in reasons[0] and "48000" in reasons[0],
          "the reason states the ceiling that was exceeded")


def test_the_floor_still_catches_the_opposite_failure():
    v = _metrics(22050)
    check(v["mechanical_pass"] is False, "a below-floor rate still fails")
    check("below" in _rate_reasons(v)[0],
          "and is reported as below the floor, not confused with the new ceiling")


# The mastering regions: the code that finishes the audio and writes the artifact
# the audio gate then measures. Locating them by their enclosing region (rather
# than by text near the word "loudnorm") is what makes this test bite: the mixing
# graph is built up in a list, so a run() call never contains the string
# "loudnorm" and a proximity check would silently pass.
MASTERING_REGIONS = (
    ("main.py", '_mix_wav = os.path.join(WORK, "final_mix.wav")',
     'with open(os.path.join(OUT, "post.json")'),
    ("quality_downstream_factory_proof.py", "def _mix_final(", "\ndef _repair_verdict("),
)


def _encode_calls(region: str):
    return [" ".join(c.split()) for c in re.findall(r"run\(\[(.*?)\]\)", region, re.S)]


def test_every_mastering_encode_pins_the_rate():
    """Exactly one command per path writes delivery audio, and it uses the helper.

    The check is on the DELIVERY encode specifically. Both paths also run
    intermediate audio passes (the mix, and the master's own stages), and those
    write WAV -- asserting the contract args on them would be meaningless. What
    matters is that nothing else in the region encodes delivery audio behind the
    helper's back, which is exactly how -ar went missing the first time.
    """
    checked = 0
    for mod, start, end in MASTERING_REGIONS:
        src = (ROOT / mod).read_text(encoding="utf-8")
        check(start in src and end in src,
              f"{mod}: the mastering region is still where this test looks for it")
        region = src.split(start, 1)[1].split(end, 1)[0]
        calls = _encode_calls(region)
        check(len(calls) >= 2,
              f"{mod}: the mix and the mux are separate commands ({len(calls)} found)")
        delivery = [c for c in calls if "delivery_audio_encode_args()" in c]
        check(len(delivery) == 1,
              f"{mod}: exactly one command encodes delivery audio "
              f"({len(delivery)} found), so there is one place to get it wrong")
        for cmd in calls:
            if cmd in delivery:
                # The rate and the bitrate are one decision: pinning 48 kHz while
                # leaving 96 kbit/s measured +0.07 dBTP, breaching the gate's own
                # ceiling. Anything that re-pins the rate must carry the bitrate too.
                check('"96k"' not in cmd,
                      f"{mod}: the starved 96 kbit/s mastering bitrate is gone")
            else:
                check('"-c:a"' not in cmd and '"-b:a"' not in cmd,
                      f"{mod}: an intermediate pass does not hand-roll a second "
                      "audio encode alongside the shared one")
            checked += 1
    check(checked >= 5,
          f"all {checked} commands in both finishing paths are constrained")


def _code_only(region: str) -> str:
    """The region with comments and triple-quoted prose stripped.

    Both regions EXPLAIN loudnorm at length -- that is the point of the comments.
    The assertion below is about whether a mastering filter string reaches
    ffmpeg, so the prose has to go first. An earlier test in this file matched
    its own explanatory comment and therefore asserted nothing at all.

    A '#' inside a string literal is preceded by a quote, not whitespace, so it
    survives; that is deliberate, since such a string could be a filter arg.
    """
    no_docs = re.sub(r'"""(?:.|\n)*?"""', "", region)
    return "\n".join(re.sub(r"(^|\s)#.*$", "", ln) for ln in no_docs.splitlines())


def test_both_finishing_paths_call_the_one_mastering_implementation():
    """A shared CONSTANT was not enough last time; the sequence is shared too.

    delivery_contract's true-peak target was declared shared while every path
    kept its own hard-coded filter string, so the constant was inert. The fix is
    that neither path can express a master at all: they call master_audio().
    """
    for mod, start, end in MASTERING_REGIONS:
        src = (ROOT / mod).read_text(encoding="utf-8")
        region = _code_only(src.split(start, 1)[1].split(end, 1)[0])
        check("master_audio(" in region,
              f"{mod}: finishing delegates to the shared measured master")
        # "loudnorm=" / "alimiter=" -- with the '=' -- is how an ffmpeg filter is
        # actually written, and distinguishes a filter from the master report's
        # own `stage1_loudnorm_lufs` field, which this path legitimately prints.
        check("loudnorm=" not in region and "alimiter=" not in region,
              f"{mod}: and holds no mastering filter string of its own")
        check("delivery_master_filter()" not in region,
              f"{mod}: nor the single-graph shortcut, which cannot measure its "
              "own output and undershot the loudness gate by 2.4 dB on real speech")


def test_the_shared_master_measures_rather_than_asserts():
    """The loop is closed against the LIMITED signal, not loudnorm's output.

    Correcting only loudnorm's error left +0.38 dB of margin; correcting again
    after the limiter (which itself costs 0.4-1.6 dB) left +1.13 dB. Losing the
    second measurement would silently give back most of the margin, so the shape
    of the loop is pinned here rather than left to a comment.
    """
    src = (ROOT / "delivery_master.py").read_text(encoding="utf-8")
    body = src.split("def master_audio(", 1)[1]
    check(body.count("measure_integrated_lufs(") >= 3,
          "the master measures at every stage, including after the limiter")
    check(body.count("delivery_limiter_filter()") >= 1 and body.count("limiter") >= 3,
          "the limiter -- the only owner of the peak ceiling -- is applied, not just named")
    check("_clamp(" in body,
          "a corrective gain is bounded, so a bad measurement fails the gate "
          "loudly instead of muting or blowing up a render")
    for banned in ("import main", "import quality_", "import generate", "import narration"):
        check(banned not in src,
              f"delivery_master does not import {banned!r} -- production must not "
              "depend on the module that judges it")


def test_the_bitrate_is_high_enough_for_the_delivery_rate():
    """Pinned by measurement: 96 kbit/s at 48 kHz overshot the limiter by 1.6 dB.

    This is the number that keeps the true-peak target honest, so it is asserted
    rather than left to whoever next edits an ffmpeg line.
    """
    kbps = int(re.sub(r"[^0-9]", "", DC.DELIVERY_AUDIO_BITRATE))
    check(kbps >= 128,
          f"the mastering bitrate ({kbps} kbit/s) is at least the 128 measured as "
          "sufficient for a limited signal at 48 kHz")


def test_the_renderer_reads_the_contract_from_a_neutral_module():
    """Production must not import the module that judges it.

    main.py used to do `from quality_audio_qa import ...`, which made the
    renderer depend on QA -- and quality_audio_qa itself imports `narration`, a
    production module, so it was never a leaf. delivery_contract imports nothing.
    """
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("from delivery_contract import" in src,
          "main.py takes the delivery contract from the neutral module")
    check("from quality_audio_qa import" not in src,
          "and no longer imports the QA module it is judged by")
    check(not re.search(r'"-ar",\s*"48000"', src),
          "main.py does not restate 48000 as a literal beside the import")
    contract_src = (ROOT / "delivery_contract.py").read_text(encoding="utf-8")
    for banned in ("import main", "import quality_", "import generate", "import narration"):
        check(banned not in contract_src,
              f"delivery_contract stays a leaf -- no {banned!r} (that would re-create the cycle)")


if __name__ == "__main__":
    test_the_delivery_rate_is_a_single_shared_constant()
    test_the_gate_accepts_the_rate_the_renderer_actually_produces()
    test_the_exact_shipped_defect_is_now_rejected()
    test_the_floor_still_catches_the_opposite_failure()
    test_every_mastering_encode_pins_the_rate()
    test_both_finishing_paths_call_the_one_mastering_implementation()
    test_the_shared_master_measures_rather_than_asserts()
    test_the_bitrate_is_high_enough_for_the_delivery_rate()
    test_the_renderer_reads_the_contract_from_a_neutral_module()
    print("delivery audio contract tests: PASS")
