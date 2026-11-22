#!/usr/bin/env python3
"""Deterministic audit of a FINISHED video (no LLM, no network).

Why: final QA samples 8 frames and asks an LLM. On run 455 it said 8/10 for a video
with an 11 s effective hold, an 8 s wrong-person still and ~2 s of near-black. A
measurement sees what sampling misses. This module is the ruler for every footage fix.

It decodes the video to a tiny grey frame series (4 fps, 36x64), then judges:
  * effective SHOT length: a shot ends only when consecutive frames differ a lot, so
    several "cuts" between near-identical clips count as ONE hold (the 11 s star/clock
    stretch);
  * near-black runs and merely-dim runs;
  * the fraction of the video spent inside long shots.

Thresholds are calibrated on ONE real video (run 455), so they are deliberately
conservative and exposed as constants. Hard failures are only the clear ones.

    python video_audit.py final.mp4 [--json out/video_audit.json] [--enforce]
"""
from __future__ import annotations

import json
import subprocess
import sys

FPS = 4
W, H = 36, 64
CUT_DIFF = 25.0            # mean |dY| (0-255) between frames: real cuts measured 35-92, in-shot motion <= 20
HOLD_HARD_S = 7.0          # effective shot longer than this = FAIL
HOLD_WARN_S = 4.5
LONG_SHOT_FRACTION_WARN = 0.45   # warn if more than this share of runtime is in shots > HOLD_WARN_S
BLACK_LUMA = 15.0          # near-black (run 455 had 6-9 for ~2 s)
BLACK_HARD_S = 1.5
DIM_LUMA = 35.0
DIM_WARN_S = 4.0


def extract_series(video, fps=FPS, w=W, h=H):
    """(luma_series, diff_series): mean grey level per frame and mean absolute
    difference to the previous frame (0 for the first)."""
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", video, "-vf", f"fps={fps},scale={w}:{h}:flags=area,format=gray",
         "-f", "rawvideo", "-"])
    n = len(raw) // (w * h)
    frames = [raw[i * w * h:(i + 1) * w * h] for i in range(n)]
    luma = [sum(f) / len(f) for f in frames]
    diff = [0.0] + [sum(abs(a - b) for a, b in zip(frames[i], frames[i - 1])) / (w * h) for i in range(1, n)]
    return luma, diff


def effective_shots(diff, fps=FPS, cut_diff=CUT_DIFF):
    """[(start_s, length_s)] — a new shot begins where a frame differs from the last
    by more than cut_diff. Pure."""
    n = len(diff)
    if n == 0:
        return []
    starts = [0] + [i for i in range(1, n) if diff[i] > cut_diff]
    ends = starts[1:] + [n]
    return [(round(s / fps, 2), round((e - s) / fps, 2)) for s, e in zip(starts, ends)]


def runs_below(series, floor, fps=FPS):
    """[(start_s, length_s)] of consecutive frames with value < floor. Pure."""
    out, start = [], None
    for i, v in enumerate(series + [floor + 1]):
        if v < floor and start is None:
            start = i
        elif v >= floor and start is not None:
            out.append((round(start / fps, 2), round((i - start) / fps, 2)))
            start = None
    return out


def audit_series(luma, diff, fps=FPS):
    shots = effective_shots(diff, fps)
    total = len(luma) / fps if luma else 0.0
    longest = max(shots, key=lambda s: s[1]) if shots else (0.0, 0.0)
    long_time = sum(l for _, l in shots if l > HOLD_WARN_S)
    black = runs_below(luma, BLACK_LUMA, fps)
    dim = runs_below(luma, DIM_LUMA, fps)
    black_max = max((l for _, l in black), default=0.0)
    dim_max = max((l for _, l in dim), default=0.0)
    frac = (long_time / total) if total else 0.0
    fails, warns = [], []
    if longest[1] > HOLD_HARD_S:
        fails.append(f"effective hold {longest[1]:.1f}s at {longest[0]:.1f}s (> {HOLD_HARD_S}s): the picture does not change")
    if black_max >= BLACK_HARD_S:
        fails.append(f"near-black for {black_max:.1f}s (luma < {BLACK_LUMA:.0f})")
    if frac > LONG_SHOT_FRACTION_WARN:
        warns.append(f"{frac * 100:.0f}% of the runtime is inside shots longer than {HOLD_WARN_S}s")
    if dim_max > DIM_WARN_S:
        warns.append(f"dim (luma < {DIM_LUMA:.0f}) for {dim_max:.1f}s")
    return {
        "duration_s": round(total, 2), "effective_shots": len(shots),
        "avg_shot_s": round(total / len(shots), 2) if shots else 0.0,
        "longest_hold_s": longest[1], "longest_hold_at_s": longest[0],
        "long_shot_fraction": round(frac, 3),
        "black_max_s": black_max, "dim_max_s": dim_max,
        "black_runs": black, "pass": not fails, "fails": fails, "warns": warns,
    }


def audit_video(video):
    luma, diff = extract_series(video)
    return audit_series(luma, diff)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(__doc__); return 2
    video = argv[0]
    rep = audit_video(video)
    if "--json" in argv:
        path = argv[argv.index("--json") + 1]
        with open(path, "w") as f:
            json.dump(rep, f, indent=1)
    print(json.dumps(rep, indent=1))
    return 0 if (rep["pass"] or "--enforce" not in argv) else 3


if __name__ == "__main__":
    sys.exit(main())
