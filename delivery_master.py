#!/usr/bin/env python3
"""The ONE final-audio mastering implementation. Production and every proof use it.

WHY A SEPARATE MODULE FROM ``delivery_contract``

``delivery_contract`` is a pure leaf: constants and filter-string builders, no
I/O. Mastering correctly requires *measuring* the intermediate result and acting
on it, which is execution, not configuration. Forcing that into the contract
would break its leaf role, so sequencing lives here and imports the contract.
This module deliberately does NOT import ``quality_audio_qa`` -- production must
not depend on the module that judges it -- so it carries its own small loudness
probe (an ffmpeg analysis pass and a regex, nothing more).

WHY THE MASTER IS A MEASURED LOOP AND NOT A FILTER STRING

``loudnorm`` is inaccurate in single-pass dynamic mode, and the error scales with
the material's loudness range. Measured on a mix whose LRA (7.2) matches real
narration, against the artifact gate of [-16.0, -11.5] LUFS and <= -0.5 dBTP:

    loudnorm alone, pre-encode                     I = -16.45
    1-pass loudnorm + limiter        (decoded AAC) I = -16.97   FAIL
    2-pass loudnorm measured_* + limiter  (decoded) I = -16.18   FAIL
    single corrective gain + limiter      (decoded) I = -15.62   pass, +0.38 dB
    THIS: loop-closed gain + limiter      (decoded) I = -14.87   PASS, +1.13 dB

Two-pass loudnorm was the obvious fix and it is NOT sufficient: it improves
loudnorm's own accuracy by ~0.8 dB, but the miss on realistic material is ~2.4 dB
and the limiter then removes another 0.4-1.6 dB depending on how peaky the
content is. Only closing the loop on the ACTUAL limited signal is content
independent.

Also previously measured and rejected: two-pass with ``linear=true`` and no
separate peak owner, which pushed the decoded peak to +0.06 dBTP. The limiter
owns the peak here; the loudness stage never has to.

STAGE RESPONSIBILITIES, one job each
    1. loudnorm        -- loudness range control and a first approximation
    2. measure         -- what the signal ACTUALLY is, not what was requested
    3. gain + limiter  -- correct the error; the limiter guarantees the ceiling
    4. measure again   -- the limiter itself costs loudness (0.4-1.6 dB measured)
    5. residual gain + limiter -- close the loop against the limited signal
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any

import delivery_contract as DC

# A corrective gain is a fix for a measurement error, not a creative decision.
# Bounding it means a pathological measurement can never silently blow up or
# mute a render -- it fails the audio gate loudly instead.
MAX_STAGE1_GAIN_DB = 12.0
MAX_RESIDUAL_GAIN_DB = 6.0


class DeliveryMasterError(RuntimeError):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise DeliveryMasterError(
            f"command failed ({proc.returncode}): {' '.join(cmd[:6])}...\n{proc.stderr[-1200:]}")
    return proc


def measure_integrated_lufs(path: str | Path) -> float:
    """Integrated loudness of `path`, via loudnorm's analysis pass.

    Reads ``input_i``, which describes the signal as it arrived and does not
    depend on the target arguments -- so the arguments here are inert and must
    NOT be wired to the delivery target (that would make changing the master
    silently change the measurement while measuring the same thing).
    """
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    blobs = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not blobs:
        raise DeliveryMasterError("loudness measurement returned no JSON")
    try:
        return float(json.loads(blobs[-1])["input_i"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise DeliveryMasterError("loudness measurement JSON malformed") from exc


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def master_audio(src_audio: str | Path, dest_audio: str | Path,
                 work_dir: str | Path) -> dict[str, Any]:
    """Master `src_audio` to the delivery loudness/peak contract.

    Returns the measurements at every stage so a proof can show the loop
    actually converged rather than asserting that it did.
    """
    src, dest, work = Path(src_audio), Path(dest_audio), Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    target = float(DC.DELIVERY_INTEGRATED_LUFS)
    limiter = DC.delivery_limiter_filter()
    tag = dest.stem

    stage1 = work / f"master_{tag}_s1.wav"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
          "-af", DC.delivery_loudness_filter(),
          "-ar", str(DC.DELIVERY_SAMPLE_RATE), str(stage1)])
    m1 = measure_integrated_lufs(stage1)

    gain1 = _clamp(target - m1, MAX_STAGE1_GAIN_DB)
    stage2 = work / f"master_{tag}_s2.wav"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(stage1),
          "-af", f"volume={gain1:.2f}dB,{limiter}",
          "-ar", str(DC.DELIVERY_SAMPLE_RATE), str(stage2)])
    m2 = measure_integrated_lufs(stage2)

    # The limiter costs loudness -- 0.4 to 1.6 dB depending on how peaky the
    # material is -- so the loop is closed against the LIMITED signal, not
    # against loudnorm's output. This second correction is what separates a
    # +1.13 dB floor margin from a +0.38 dB one.
    gain2 = _clamp(target - m2, MAX_RESIDUAL_GAIN_DB)
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(stage2),
          "-af", f"volume={gain2:.2f}dB,{limiter}",
          "-ar", str(DC.DELIVERY_SAMPLE_RATE), str(dest)])
    m3 = measure_integrated_lufs(dest)

    return {
        "schema": "content-render-delivery-master-v1",
        "target_lufs": target,
        "stage1_loudnorm_lufs": round(m1, 2),
        "stage1_gain_db": round(gain1, 2),
        "stage2_limited_lufs": round(m2, 2),
        "residual_gain_db": round(gain2, 2),
        "mastered_lufs": round(m3, 2),
        "target_error_db": round(m3 - target, 2),
        "limiter": limiter,
        "loudness_filter": DC.delivery_loudness_filter(),
    }
