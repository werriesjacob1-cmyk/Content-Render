#!/usr/bin/env python3
"""Zero-provider regressions for quality_audio_qa.py."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_audio_qa as A


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _media():
    return {
        "duration_s": 40.0,
        "audio": {"codec_name": "aac", "sample_rate": "48000", "channels": 2},
        "video": {"codec_name": "h264"},
    }


def test_social_mastering_target_passes_with_human_listen_still_required():
    report = A.evaluate_metrics(
        _media(),
        {"integrated_lufs": -14.0, "true_peak_db": -1.4, "lra_lu": 5.0},
        {"long_silence_seconds": 1.0, "long_silence_ratio": 0.025},
        narration_words=105,
    )
    check(report["mechanical_pass"] is True, "healthy final social master clears mechanical audio gate")
    check(report["sample_rate"] == 48000 and report["channels"] == 2, "encoded stream format is preserved in report")
    check(report["human_listen_required"] is True, "technical pass never substitutes for listening review")


def test_quiet_clipped_or_dead_audio_fails_closed():
    quiet = A.evaluate_metrics(
        _media(), {"integrated_lufs": -22.0, "true_peak_db": -2.0, "lra_lu": 4.0},
        {"long_silence_seconds": 0.0, "long_silence_ratio": 0.0}, 100)
    clipped = A.evaluate_metrics(
        _media(), {"integrated_lufs": -14.0, "true_peak_db": 0.1, "lra_lu": 4.0},
        {"long_silence_seconds": 0.0, "long_silence_ratio": 0.0}, 100)
    dead = A.evaluate_metrics(
        _media(), {"integrated_lufs": -14.0, "true_peak_db": -1.0, "lra_lu": 4.0},
        {"long_silence_seconds": 12.0, "long_silence_ratio": 0.30}, 100)
    check(not quiet["mechanical_pass"] and "loudness" in " ".join(quiet["mechanical_reasons"]),
          "quiet master is rejected")
    check(not clipped["mechanical_pass"] and "true peak" in " ".join(clipped["mechanical_reasons"]),
          "clipped/over-peak master is rejected")
    check(not dead["mechanical_pass"] and "silence" in " ".join(dead["mechanical_reasons"]),
          "accidental long-dead audio is rejected")


def test_missing_or_bad_stream_format_is_rejected():
    missing = A.evaluate_metrics(
        {"duration_s": 40.0, "audio": None}, {},
        {"long_silence_seconds": 40.0, "long_silence_ratio": 1.0}, 100)
    lowrate = A.evaluate_metrics(
        {"duration_s": 40.0, "audio": {"codec_name": "aac", "sample_rate": "16000", "channels": 4}},
        {"integrated_lufs": -14.0, "true_peak_db": -1.0, "lra_lu": 3.0},
        {"long_silence_seconds": 0.0, "long_silence_ratio": 0.0}, 100)
    check(not missing["mechanical_pass"] and "no audio stream" in " ".join(missing["mechanical_reasons"]),
          "missing audio cannot masquerade as successful video")
    reasons = " ".join(lowrate["mechanical_reasons"])
    check(not lowrate["mechanical_pass"] and "sample rate" in reasons and "channel count" in reasons,
          "bad sample-rate/channel encoding is rejected")


def test_silence_parser_handles_open_ended_interval():
    stderr = """
[silencedetect @ x] silence_start: 3.5
[silencedetect @ x] silence_end: 4.2 | silence_duration: 0.7
[silencedetect @ x] silence_start: 9.0
"""
    intervals = A._silence_intervals(stderr, 10.0)
    check(intervals == [(3.5, 4.2), (9.0, 10.0)], "silence parser closes trailing silence at media duration")


if __name__ == "__main__":
    test_social_mastering_target_passes_with_human_listen_still_required()
    test_quiet_clipped_or_dead_audio_fails_closed()
    test_missing_or_bad_stream_format_is_rejected()
    test_silence_parser_handles_open_ended_interval()
    print("quality_audio_qa tests: PASS")
