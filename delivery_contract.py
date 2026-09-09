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
# 192 kbit/s, not 128, and for the same reason 128 replaced 96: AAC coding error
# pushes the decoded true peak back up, and the size of that overshoot is the
# single most variable term in the whole chain. Measured on real Piper narration
# over a music bed, decoded overshoot above the limited signal:
#
#     128 kbit/s   +0.23 dB typical, +1.72 dB on dense material
#     192 kbit/s   +0.04 dB typical, +0.50 dB on dense material
#
# At 128 that variance alone can eat the entire headroom reserve; at 192 it
# cannot. Audio is a rounding error in a 1080x1920 H.264 file, so buying the
# headroom with bitrate is the cheapest correct fix available.
DELIVERY_AUDIO_BITRATE = "192k"

# Limiting is done here, above the delivery rate, so alimiter's sample peaks
# approximate true peaks. See delivery_limiter_filter().
LIMITER_OVERSAMPLE_RATE = 192000

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


def delivery_loudness_filter() -> str:
    """Stage 1: loudness range control and a first approximation.

    Its true-peak argument is deliberately loose -- the limiter owns the peak.
    Asking loudnorm to hold a tight peak AND hit the loudness target makes its
    internal limiter fight the target, and the loudness loses.
    """
    return (
        f"loudnorm=I={DELIVERY_INTEGRATED_LUFS}:"
        f"TP={LOUDNORM_INTERNAL_TP_DB}:"
        f"LRA={DELIVERY_LRA_LU}"
    )


def delivery_limiter_filter() -> str:
    """Stage 3/5: the ONLY thing responsible for the pre-encode peak ceiling.

    Limiting happens at ``LIMITER_OVERSAMPLE_RATE``, not at the delivery rate,
    because ``alimiter`` bounds the SAMPLE peak and the gate measures the TRUE
    peak. Between samples a limited signal reconstructs higher than any sample
    in it, and the gap grows with density -- measured on real narration over a
    bed, at a -2.5 dB target:

        48 kHz  (sample-peak limiting)   -> true peak -2.42, and -1.60 when hot
        192 kHz (this)                   -> true peak -2.50, and -2.46 when hot

    So without oversampling the limiter silently missed its own target by up to
    0.9 dB on dense material, which is most of why a production artifact decoded
    at -0.0 dBTP while the identical code had decoded at -1.74 dBTP a run
    earlier. Resampling back down can re-introduce a little of it, which is what
    the master's measured verification is for.
    """
    return (f"aresample={LIMITER_OVERSAMPLE_RATE},"
            f"alimiter=limit={_limit_amplitude():.4f}:level=disabled,"
            f"aresample={DELIVERY_SAMPLE_RATE}")


def delivery_master_filter() -> str:
    """Loudness + limiter as one string.

    Kept for callers that master in a single filter graph. It is NOT the
    delivery master on its own: ``delivery_master.master_audio`` closes a
    measured loop around these stages, because loudnorm's single-pass error on
    realistic material (~2.4 dB) is far larger than any filter string can fix.
    """
    return f"{delivery_loudness_filter()},{delivery_limiter_filter()}"


def delivery_audio_encode_args() -> list[str]:
    """The ffmpeg output args for delivery audio: codec, bitrate, sample rate.

    Returned as a list so a caller splices it into a command rather than
    re-typing ``-b:a``/``-ar`` and drifting from the gate again.
    """
    return ["-c:a", "aac", "-b:a", DELIVERY_AUDIO_BITRATE,
            "-ar", str(DELIVERY_SAMPLE_RATE)]
