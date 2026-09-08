#!/usr/bin/env python3
"""Zero-provider regressions for quality_science_render timeline/provenance helpers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_science_render as R


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_scene_timeline_uses_measured_rendered_scene_files():
    old_work, old_out, old_probe = R.legacy.WORK, R.legacy.OUT, R.legacy.ffprobe_dur
    manifest = {
        "scenes": [
            {"id": 1, "_v2_role": "hook", "search_query": "hook subject", "source_claim_ids": ["c1"]},
            {"id": 2, "_v2_role": "beat", "search_query": "mechanism", "source_claim_ids": ["c2"]},
            {"id": 3, "_v2_role": "payoff", "search_query": "proof", "source_claim_ids": ["c3"]},
        ]
    }
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "work"
        out = Path(td) / "out"
        work.mkdir(); out.mkdir()
        durations = {"s1.mp4": 3.2, "s2.mp4": 4.5, "s3.mp4": 2.3}
        for name in durations:
            (work / name).write_bytes(b"fake")
        R.legacy.WORK = str(work)
        R.legacy.OUT = str(out)
        R.legacy.ffprobe_dur = lambda path: durations[Path(path).name]
        try:
            payload = R._write_scene_timeline(manifest)
            saved = json.loads((out / "scene_timeline.json").read_text())
        finally:
            R.legacy.WORK, R.legacy.OUT, R.legacy.ffprobe_dur = old_work, old_out, old_probe

    rows = payload["scenes"]
    check(rows[0]["start_s"] == 0.0 and rows[0]["end_s"] == 3.2, "hook boundary uses measured rendered duration")
    check(rows[1]["start_s"] == 3.2 and rows[1]["end_s"] == 7.7, "middle scene begins exactly where prior rendered scene ends")
    check(rows[2]["start_s"] == 7.7 and rows[2]["end_s"] == 10.0, "payoff boundary is cumulative and exact")
    check(payload["measured_body_duration_s"] == 10.0, "timeline duration equals sum of rendered scenes")
    check(saved == payload, "persisted scene timeline is byte-semantically identical to returned evidence")
    check(rows[2]["role"] == "payoff" and rows[2]["source_claim_ids"] == ["c3"],
          "timeline preserves role and sealed claim identity for targeted repair")


def test_missing_scene_file_is_visible_not_fabricated():
    old_work, old_out, old_probe = R.legacy.WORK, R.legacy.OUT, R.legacy.ffprobe_dur
    manifest = {"scenes": [{"id": 1, "_v2_role": "hook", "source_claim_ids": ["c1"]}]}
    with tempfile.TemporaryDirectory() as td:
        R.legacy.WORK = str(Path(td) / "work")
        R.legacy.OUT = str(Path(td) / "out")
        Path(R.legacy.WORK).mkdir()
        R.legacy.ffprobe_dur = lambda path: 99.0
        try:
            payload = R._write_scene_timeline(manifest)
        finally:
            R.legacy.WORK, R.legacy.OUT, R.legacy.ffprobe_dur = old_work, old_out, old_probe
    row = payload["scenes"][0]
    check(row["duration_s"] == 0.0 and row["rendered_scene_file_present"] is False,
          "missing rendered scene is recorded as missing instead of inventing a duration")


if __name__ == "__main__":
    test_scene_timeline_uses_measured_rendered_scene_files()
    test_missing_scene_file_is_visible_not_fabricated()
    print("quality_science_render tests: PASS")
