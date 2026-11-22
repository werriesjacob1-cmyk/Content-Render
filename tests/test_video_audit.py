#!/usr/bin/env python3
"""Zero-network regressions for video_audit.py.

The load-bearing test replays the REAL measurements of run 455 (the video that final
QA scored 8/10 despite an 11 s effective hold and ~2 s of near-black) and requires the
audit to FAIL it. A real-ffmpeg check (skipped without ffmpeg) proves the extractor
sees a synthetic hold and a black stretch."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import video_audit as V

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "video_audit", "run455_series.json")


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_known_bad_video_fails():
    d = json.load(open(FIX))
    r = V.audit_series(d["luma"], d["diff"], d["fps"])
    check(not r["pass"], "run 455 FAILS the audit")
    check(r["longest_hold_s"] >= 10.5 and abs(r["longest_hold_at_s"] - 14.25) < 0.6,
          f"the 11 s clock/star hold is found at ~14 s ({r['longest_hold_s']}s @ {r['longest_hold_at_s']}s)")
    check(r["black_max_s"] >= V.BLACK_HARD_S, f"the near-black run is found ({r['black_max_s']}s)")
    check(abs(r["long_shot_fraction"] - 0.71) < 0.05, f"matches the independently measured 71% in long shots ({r['long_shot_fraction']})")
    check(any("hold" in f for f in r["fails"]) and any("black" in f for f in r["fails"]), "both reasons are named")


def test_pure_helpers():
    check(V.runs_below([50, 10, 10, 50, 5], 15, 4) == [(0.25, 0.5), (1.0, 0.25)], "runs_below finds each dark run, incl. one at the end")
    diff = [0, 1, 1, 60, 1, 1, 1, 70, 2]
    check(V.effective_shots(diff, 4) == [(0.0, 0.75), (0.75, 1.0), (1.75, 0.5)], "a shot ends only on a real cut")
    check(V.effective_shots([], 4) == [], "empty series is safe")


def test_good_pacing_passes():
    n = 48 * V.FPS
    diff = [0.0] + [60.0 if i % 12 == 0 else 2.0 for i in range(1, n)]   # a cut every 3 s
    luma = [90.0] * n
    r = V.audit_series(luma, diff)
    check(r["pass"] and not r["warns"], f"3 s cuts, bright picture: clean pass ({r['fails']} {r['warns']})")


def test_threshold_edges():
    n = 20 * V.FPS
    diff = [0.0] + [2.0] * (n - 1)
    check(V.audit_series([90.0] * n, diff)["pass"] is False, "a 20 s single shot fails")
    diff2 = [0.0] + [60.0 if i % 24 == 0 else 2.0 for i in range(1, n)]     # 6 s shots: warn, not fail
    r = V.audit_series([90.0] * n, diff2)
    check(r["pass"] and r["warns"], "6 s shots warn but do not fail")
    black = [90.0] * 40 + [5.0] * 8 + [90.0] * 40     # 2 s black
    r = V.audit_series(black, [0.0] + [60.0 if i % 12 == 0 else 2.0 for i in range(1, len(black))])
    check(not r["pass"] and r["black_max_s"] == 2.0, "2 s of black fails")


def test_ffmpeg_extractor_sees_hold_and_black():
    if not shutil.which("ffmpeg"):
        print("SKIP ffmpeg not available"); return
    d = tempfile.mkdtemp()
    out = os.path.join(d, "t.mp4")
    ins = []
    for c, t in (("red", 2), ("blue", 9), ("black", 2), ("green", 2)):
        ins += ["-f", "lavfi", "-i", f"color=c={c}:s=270x480:d={t}:r=30"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", "[0][1][2][3]concat=n=4:v=1:a=0",
                    "-pix_fmt", "yuv420p", out], check=True)
    r = V.audit_video(out)
    check(abs(r["longest_hold_s"] - 9.0) < 0.6, f"a 9 s hold is measured ({r['longest_hold_s']}s)")
    check(r["black_max_s"] >= 1.5 and not r["pass"], "a 2 s black stretch is measured and fails")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
