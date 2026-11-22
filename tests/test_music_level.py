#!/usr/bin/env python3
"""Music bed level: the value, the override, and the measuring tool. Zero network."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GROQ_API_KEY", "x")

import main as M
import measure_mix_balance as B
import profiles


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


class Var:
    def __init__(self, value):
        self.value, self.old = value, os.environ.get("MUSIC_VOL")

    def __enter__(self):
        os.environ.pop("MUSIC_VOL", None)
        if self.value is not None:
            os.environ["MUSIC_VOL"] = self.value

    def __exit__(self, *a):
        os.environ.pop("MUSIC_VOL", None)
        if self.old is not None:
            os.environ["MUSIC_VOL"] = self.old


def test_1_science_bed_was_lowered_from_the_too_loud_value():
    v = profiles.PROFILES["science"]["music_vol"]
    check(v == 0.08, f"science music_vol is 0.08 (was 0.14, reported too loud) -- got {v}")
    drop = 20 * __import__("math").log10(v / 0.14)
    check(-6.0 < drop < -4.0, f"that is a ~5 dB reduction ({drop:.1f} dB), what the measurement called for")


def test_2_override_is_used_only_when_sane():
    saved = M.PROFILE["music_vol"]
    try:
        M.PROFILE["music_vol"] = 0.08
        for raw, want in ((None, 0.08), ("", 0.08), ("  ", 0.08), ("0.05", 0.05), (" 0.2 ", 0.2),
                          ("0.5", 0.5), ("abc", 0.08), ("0", 0.08), ("-0.1", 0.08),
                          ("0.51", 0.08), ("5", 0.08), ("nan", 0.08), ("inf", 0.08)):
            with Var(raw):
                check(M._music_vol() == want, f"MUSIC_VOL={raw!r} -> {want}")
    finally:
        M.PROFILE["music_vol"] = saved


def test_3_override_reaches_the_actual_ffmpeg_filter_and_vibe_still_scales_it():
    saved, vibe = M.PROFILE["music_vol"], M.CURRENT_VIBE
    try:
        M.PROFILE["music_vol"] = 0.08
        M.CURRENT_VIBE = "awe"
        with Var("0.05"):
            check(M._vibe_music_filter() == "volume=0.0500", "the filter uses the override")
        with Var(None):
            check(M._vibe_music_filter() == "volume=0.0800", "no override -> the profile's 0.08")
        M.CURRENT_VIBE = "peaceful"
        with Var("0.10"):
            check(M._vibe_music_filter().startswith("volume=0.0850"),
                  "the vibe multiplier (0.85 for peaceful) still applies on top of the override")
    finally:
        M.PROFILE["music_vol"], M.CURRENT_VIBE = saved, vibe


def test_4_render_workflow_passes_the_variable_to_the_render_step():
    text = (ROOT / ".github/workflows/render.yml").read_text(encoding="utf-8")
    render = text.split("- name: Render\n", 1)[1].split("\n      - name:", 1)[0]
    check("MUSIC_VOL: ${{ vars.MUSIC_VOL }}" in render, "the Render step receives vars.MUSIC_VOL")


def test_5_measuring_tool_distinguishes_a_loud_bed_from_a_quiet_one():
    # 40 windows: 30% loud speech at -12, 70% bed-only.
    def mix(bed_db):
        return [-12.0] * 12 + [bed_db] * 28
    loud = B.mix_balance(mix(-22.0))      # 10 dB apart, like the 2026-11-21 render
    ok = B.mix_balance(mix(-30.0))        # 18 dB apart
    border = B.mix_balance(mix(-26.0))    # 14 dB apart
    check(loud["verdict"].startswith("TOO LOUD") and loud["separation_db"] == 10.0,
          f"a 10 dB separation is flagged TOO LOUD ({loud})")
    check(border["verdict"].startswith("BORDERLINE"), "14 dB is BORDERLINE")
    check(ok["verdict"].startswith("OK"), "18 dB is OK")
    try:
        B.mix_balance([-12.0] * 3)
        check(False, "should refuse tiny clips")
    except ValueError:
        check(True, "a clip too short to judge is refused, not guessed at")


def test_6_window_levels_are_correct_dbfs():
    import array
    sr = 16000
    half_scale = array.array("h", [16384] * sr)           # 0.5 of full scale -> -6.02 dBFS
    lv = B.window_levels_db(half_scale, sr)
    check(len(lv) == 4 and abs(lv[0] - (-6.02)) < 0.05, f"half-scale square is ~-6.02 dBFS ({lv[0]:.2f})")
    check(B.window_levels_db(array.array("h", [0] * sr), sr)[0] == -99.0, "silence is floored, not -inf")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("music level tests: PASS")
