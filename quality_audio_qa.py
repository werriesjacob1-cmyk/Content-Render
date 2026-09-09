#!/usr/bin/env python3
"""Local final-audio mastering QA for private Content Render certification.

The finished MP4 already passes through narration-first mixing and the shared
measured master (``delivery_master``) in ``main.py``. This module independently
measures the *actual encoded artifact* so an ffmpeg/mux/filter regression cannot
silently ship quiet, clipped, missing, or mostly-dead audio.

No network or model call is made. The gate measures:
- audio stream presence / codec / sample rate / channels;
- integrated loudness and true peak via FFmpeg loudnorm analysis;
- long-silence ratio via silencedetect;
- narration words-per-minute as a pacing diagnostic (warning, not hard failure).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

from narration import spoken_text


LUFS_MIN = -16.0
LUFS_MAX = -11.5
MAX_LONG_SILENCE_RATIO = 0.20
MIN_SAMPLE_RATE = 32000

# The delivery contract is OWNED by delivery_contract.py. This module is a
# CONSUMER: the renderer must not have to import a QA module to know how to
# master (backwards layering), and the two must not be able to state different
# numbers. Only the names this module or its callers actually use are imported
# -- re-exporting the rest would be inert scaffolding, which is the exact
# pattern this branch exists to remove.
from delivery_contract import (  # noqa: E402  (contract import, kept beside the gates it feeds)
    DELIVERY_AUDIO_BITRATE,
    DELIVERY_SAMPLE_RATE,
    QA_TRUE_PEAK_CEILING_DB,
)

# What the ENCODED artifact must measure. Deliberately not the same number as
# DELIVERY_TRUE_PEAK_TARGET_DB: the gap between them is the AAC codec headroom.
TRUE_PEAK_MAX_DB = QA_TRUE_PEAK_CEILING_DB
MAX_SAMPLE_RATE = DELIVERY_SAMPLE_RATE
MIN_WPM = 105.0
MAX_WPM = 205.0


class AudioQAError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise AudioQAError(proc.stderr[-1400:] or "command failed")
    return proc


def probe_media(path: str) -> dict[str, Any]:
    proc = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,sample_rate,channels,duration",
        "-of", "json", path,
    ])
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AudioQAError("ffprobe returned invalid JSON") from exc
    streams = payload.get("streams") or []
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    try:
        duration = float((payload.get("format") or {}).get("duration"))
    except (TypeError, ValueError) as exc:
        raise AudioQAError("container duration unavailable") from exc
    return {"duration_s": duration, "audio": audio, "video": video}


def analyze_loudness(path: str) -> dict[str, float]:
    proc = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", path,
        # MEASUREMENT, not delivery. Deliberately NOT delivery_loudnorm_filter():
        # this pass reads the `input_*` fields, which describe the signal as it
        # arrived and do not depend on the target parameters at all. Wiring the
        # delivery target in here would make changing the master silently change
        # the measurement command while measuring exactly the same thing. Leave
        # these numbers alone -- they are inert analysis arguments.
        "-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ], timeout=90)
    # FFmpeg writes loudnorm JSON to stderr. Take the last object containing input_i.
    matches = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not matches:
        raise AudioQAError("loudnorm analysis returned no measurement JSON")
    try:
        data = json.loads(matches[-1])
        return {
            "integrated_lufs": float(data["input_i"]),
            "true_peak_db": float(data["input_tp"]),
            "lra_lu": float(data["input_lra"]),
            "threshold_lufs": float(data["input_thresh"]),
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AudioQAError("loudnorm measurement JSON malformed") from exc


def _silence_intervals(stderr: str, duration_s: float) -> list[tuple[float, float]]:
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", stderr)]
    intervals: list[tuple[float, float]] = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else duration_s
        if end > start:
            intervals.append((max(0.0, start), min(duration_s, end)))
    return intervals


def analyze_silence(path: str, duration_s: float) -> dict[str, Any]:
    # silencedetect returns 0 even when it finds silence; unlike _run we need stderr.
    proc = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", path,
        "-vn", "-af", "silencedetect=noise=-38dB:d=0.35",
        "-f", "null", "-",
    ], capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise AudioQAError(proc.stderr[-1400:] or "silencedetect failed")
    intervals = _silence_intervals(proc.stderr, duration_s)
    total = sum(max(0.0, b - a) for a, b in intervals)
    ratio = total / duration_s if duration_s > 0 else 1.0
    return {
        "long_silence_seconds": round(total, 3),
        "long_silence_ratio": round(ratio, 5),
        "intervals": [[round(a, 3), round(b, 3)] for a, b in intervals],
    }


def evaluate_metrics(
    media: Mapping[str, Any],
    loudness: Mapping[str, Any],
    silence: Mapping[str, Any],
    narration_words: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    warnings: list[str] = []
    audio = media.get("audio") if isinstance(media, Mapping) else None
    duration = float(media.get("duration_s") or 0.0)
    if not isinstance(audio, Mapping):
        reasons.append("final artifact has no audio stream")
        sample_rate = 0
        channels = 0
    else:
        try:
            sample_rate = int(audio.get("sample_rate") or 0)
        except (TypeError, ValueError):
            sample_rate = 0
        try:
            channels = int(audio.get("channels") or 0)
        except (TypeError, ValueError):
            channels = 0
        if sample_rate < MIN_SAMPLE_RATE:
            reasons.append(f"audio sample rate {sample_rate} below {MIN_SAMPLE_RATE}")
        elif sample_rate > MAX_SAMPLE_RATE:
            reasons.append(
                f"audio sample rate {sample_rate} above the {MAX_SAMPLE_RATE} delivery "
                "ceiling (loudnorm's internal resample leaking into the encode)"
            )
        if channels not in {1, 2}:
            reasons.append(f"unexpected final audio channel count {channels}")

    try:
        lufs = float(loudness.get("integrated_lufs"))
        peak = float(loudness.get("true_peak_db"))
    except (TypeError, ValueError):
        lufs, peak = math.nan, math.nan
    if not math.isfinite(lufs) or not (LUFS_MIN <= lufs <= LUFS_MAX):
        reasons.append(f"integrated loudness {lufs} LUFS outside [{LUFS_MIN}, {LUFS_MAX}]")
    if not math.isfinite(peak) or peak > TRUE_PEAK_MAX_DB:
        reasons.append(f"true peak {peak} dB exceeds {TRUE_PEAK_MAX_DB} dB ceiling")

    try:
        silence_ratio = float(silence.get("long_silence_ratio"))
    except (TypeError, ValueError):
        silence_ratio = 1.0
    if silence_ratio > MAX_LONG_SILENCE_RATIO:
        reasons.append(
            f"long-silence ratio {silence_ratio:.1%} exceeds {MAX_LONG_SILENCE_RATIO:.0%}"
        )

    wpm = (float(narration_words) / duration * 60.0) if duration > 0 else 0.0
    if wpm < MIN_WPM:
        warnings.append(f"narration density {wpm:.1f} WPM is unusually slow")
    elif wpm > MAX_WPM:
        warnings.append(f"narration density {wpm:.1f} WPM is unusually fast")

    return {
        "schema": "quality-audio-qa-v1",
        "mechanical_pass": not reasons,
        "mechanical_reasons": reasons,
        "warnings": warnings,
        "duration_s": round(duration, 3),
        "audio_codec": str(audio.get("codec_name") or "") if isinstance(audio, Mapping) else "",
        "sample_rate": sample_rate,
        "channels": channels,
        "integrated_lufs": lufs,
        "true_peak_db": peak,
        "lra_lu": loudness.get("lra_lu"),
        "long_silence_seconds": silence.get("long_silence_seconds"),
        "long_silence_ratio": silence_ratio,
        "narration_words": int(narration_words),
        "narration_wpm": round(wpm, 2),
        "human_listen_required": True,
    }


def review(video_path: str, manifest_path: str) -> dict[str, Any]:
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    words = len(re.findall(r"\b\w+[\w'-]*\b", spoken_text(manifest)))
    media = probe_media(video_path)
    if not isinstance(media.get("audio"), Mapping):
        # Still emit a useful report without trying audio filters on no-audio media.
        return evaluate_metrics(media, {}, {"long_silence_ratio": 1.0, "long_silence_seconds": media.get("duration_s")}, words)
    loudness = analyze_loudness(video_path)
    silence = analyze_silence(video_path, float(media["duration_s"]))
    report = evaluate_metrics(media, loudness, silence, words)
    report["silence_intervals"] = silence.get("intervals") or []
    return report


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--report", default="out/audio_qa_report.json")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        report = review(args.video, args.manifest)
    except Exception as exc:
        report = {
            "schema": "quality-audio-qa-v1",
            "mechanical_pass": False,
            "mechanical_reasons": [f"{type(exc).__name__}: {exc}"],
            "warnings": [],
            "human_listen_required": True,
        }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("mechanical_pass") is True else 1


if __name__ == "__main__":
    sys.exit(main())
