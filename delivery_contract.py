#!/usr/bin/env python3
"""The single delivery contract for finished audio: one source, no restatements.

WHY THIS MODULE EXISTS AT ALL

The renderer (``main.py``) masters the audio; ``quality_audio_qa`` judges the
encoded artifact afterwards. Those two must agree, and twice now they have not:

1. ``loudnorm`` resamples internally to 192 kHz and never restores the input
   rate, so with no ``-ar`` every render shipped 96 kHz AAC while the gate --
   which recorded ``sample_rate: 96000`` in its own report -- had only a floor
   and waved it through.
2. A later change added ``DELIVERY_TRUE_PEAK_TARGET_DB = -2.5`` to the QA
   module and a ``delivery_loudnorm_filter()`` helper, and declared that the
   renderer and the factory shared one contract. Neither actually called it:
   ``main.py`` imported only the rate and bitrate, and both finishing paths
   still carried a hard-coded ``loudnorm=I=-14:TP=-1.5:LRA=11``. The constant
   was inert, so the artifact that "proved" it was in fact mastered at -1.5.

Both are the same defect: a value stated in one place and enforced from
another. So the contract lives HERE, in a module that imports nothing from the
codebase, and both the renderer and the gate import it.

WHY NOT IN ``quality_audio_qa``

Production code importing a QA module is backwards layering -- the renderer
would depend on the thing that judges it, and would drag the QA module's own
imports into every render. ``quality_audio_qa`` re-exports these names so
existing callers keep working, but it is a consumer here, not the owner.

THE NUMBERS, AND THE EVIDENCE BEHIND THEM

``DELIVERY_TRUE_PEAK_TARGET_DB`` is the target handed to the limiter BEFORE the
lossy encode. It is deliberately lower than the gate's ceiling because AAC is
not peak-preserving: coding error and intersample peaks push the decoded signal
back up. Measured on real content, not reasoned:

    48 kHz @  96 kbit/s, TP=-1.5, synthetic tones -> +0.07 dBTP decoded  FAIL
    48 kHz @ 128 kbit/s, TP=-1.5, synthetic tones -> -1.49 dBTP decoded  pass
    48 kHz @ 128 kbit/s, TP=-1.5, real speech+bed -> +0.26 dBTP decoded  FAIL

Real narration over a music bed overshot by ~1.8 dB where synthetic tones
overshot by ~0.01 dB, which is why a bitrate that looked sufficient on the
factory fixture was not sufficient in production. Targeting -2.5 dBTP reserves
2.0 dB against the -0.5 dBTP gate.

The gate's ceiling is NOT relaxed to accommodate any of this: the artifact is
still required to decode at or below -0.5 dBTP. This module lowers the target
so the artifact meets that ceiling honestly.
"""
from __future__ import annotations

# Container/stream delivery.
DELIVERY_SAMPLE_RATE = 48000
DELIVERY_AUDIO_BITRATE = "128k"

# Mastering targets applied before the AAC encode.
DELIVERY_INTEGRATED_LUFS = -14
DELIVERY_TRUE_PEAK_TARGET_DB = -2.5
DELIVERY_LRA_LU = 11

# What the finished artifact must actually measure. Separate from the target
# above on purpose: the gap between them IS the codec headroom, so a single
# number could not express both.
QA_TRUE_PEAK_CEILING_DB = -0.5


# loudnorm's OWN true-peak argument, kept deliberately loose. Asking loudnorm to
# both reach -14 LUFS and hold a tight true peak makes its internal limiter fight
# its loudness target, and the loudness loses: on real Piper narration a
# TP=-2.5 single pass landed -16.42 LUFS, outside the gate's -16.0 floor. The
# peak ceiling is enforced by a dedicated limiter below instead, which measured
# strictly better on BOTH axes than folding the job into loudnorm:
#
#   peaky speech+bed   loudnorm TP=-2.5          -> I=-14.90  decoded TP=-2.13
#                      loudnorm TP=-1.5 + limiter-> I=-14.65  decoded TP=-2.11
#   quiet speech+bed   loudnorm TP=-2.5          -> I=-15.10  decoded TP=-2.11
#                      loudnorm TP=-1.5 + limiter-> I=-14.90  decoded TP=-2.28
#
# More loudness at the same peak safety, because each stage does one job.
LOUDNORM_INTERNAL_TP_DB = -1.5


def _limit_amplitude() -> float:
    """DELIVERY_TRUE_PEAK_TARGET_DB as the linear amplitude alimiter wants."""
    return 10.0 ** (DELIVERY_TRUE_PEAK_TARGET_DB / 20.0)


def delivery_master_filter() -> str:
    """The complete final-master audio chain: loudness, then peak ceiling.

    Two stages with one job each. ``loudnorm`` sets integrated loudness;
    ``alimiter`` enforces the pre-encode peak target that reserves codec
    headroom. Callers append their own graph around this and never restate the
    numbers.

    Deliberately NOT used for measurement passes -- an analysis filter reads
    ``input_*`` values that do not depend on these targets, so coupling the two
    would mean changing the delivery target silently changed the measurement
    command while measuring exactly the same thing.

    NOTE: two-pass loudnorm (``measured_*`` + ``linear=true``) was measured and
    REJECTED. Linear mode applies a fixed gain and does not limit, so it made
    the decoded peak WORSE -- +0.06 dBTP on peaky speech, failing the gate --
    while buying ~0.2 dB of loudness accuracy. Peak safety is the hard
    constraint; do not "improve" this by reintroducing it.
    """
    return (
        f"loudnorm=I={DELIVERY_INTEGRATED_LUFS}:"
        f"TP={LOUDNORM_INTERNAL_TP_DB}:"
        f"LRA={DELIVERY_LRA_LU}"
        f",alimiter=limit={_limit_amplitude():.4f}:level=disabled"
    )


def delivery_audio_encode_args() -> list[str]:
    """The ffmpeg output args for delivery audio: codec, bitrate, sample rate.

    Returned as a list so a caller splices it into a command rather than
    re-typing ``-b:a``/``-ar`` and drifting from the gate again.
    """
    return ["-c:a", "aac", "-b:a", DELIVERY_AUDIO_BITRATE,
            "-ar", str(DELIVERY_SAMPLE_RATE)]
