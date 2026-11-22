#!/usr/bin/env python3
"""Zero-network regressions for the director layer (shot list, mood, punch-in, sound bed).

Pure decisions are tested directly. The two ffmpeg-backed checks (punch-in is really
centred, bed levels sit where intended) run only when ffmpeg exists."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")
os.environ.pop("DIRECTOR_SHOTLIST", None)

import director as D
import main as M


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_shot_filter_and_parse():
    check(D.shot_is_filmable("honey fungus mushrooms"), "a concrete 3-word shot is filmable")
    for bad in ("mystery", "the power of connection", "one two three four five six", "complex system"):
        check(not D.shot_is_filmable(bad), f"{bad!r} is rejected (abstract / wrong length)")
    reply = json.dumps({"scenes": [
        {"n": 1, "shots": [{"query": "honey fungus mushrooms", "reason": "names the organism"},
                           {"query": "Honey Fungus Mushrooms", "reason": "dup"},
                           {"query": "hidden mystery", "reason": "abstract"},
                           {"query": "oregon forest floor", "reason": "the place"},
                           {"query": "mushroom cluster log", "reason": "close up"},
                           {"query": "fungal threads soil", "reason": "fourth, over the cap"}]},
        {"n": 9, "shots": [{"query": "out of range", "reason": "x"}]},
        {"n": 2, "shots": [{"query": "power", "reason": "abstract only"}]}]})
    out = D.parse_shotlist("noise " + reply + " noise", 3)
    check(list(out) == [0], f"only the valid scene survives ({list(out)})")
    check([s["query"] for s in out[0]] == ["honey fungus mushrooms", "oregon forest floor", "mushroom cluster log"],
          "duplicates/abstract dropped, capped at 3 shots")
    check(D.parse_shotlist("not json", 3) == {} and D.parse_shotlist(None, 3) == {}, "garbage never raises")


def test_apply_and_wiring():
    scenes = [{"voiceover": "a", "search_query": "old q"}, {"voiceover": "b", "search_query": "keep me"}]
    n = D.apply_shotlist(scenes, {0: [{"query": "honey fungus", "reason": "r"}, {"query": "oregon forest", "reason": "r"}]})
    check(n == 1 and scenes[0]["search_query"] == "honey fungus" and scenes[1]["search_query"] == "keep me",
          "first shot becomes the search_query (so the relevance judge gates it); others untouched")
    check(D.shot_queries(scenes[0]) == ["oregon forest"] and D.shot_queries(scenes[1]) == [], "extra shots exposed")
    check(M.DIRECTOR_SHOTLIST is False, "the shot-list step is OFF by default")

    m = {"scenes": [{"voiceover": "Why does it grow?", "search_query": "q"}]}
    saved = M._groq_chat
    try:
        M._groq_chat = lambda *a, **k: json.dumps({"scenes": [{"n": 1, "shots": [
            {"query": "honey fungus mushrooms", "reason": "r"}, {"query": "forest floor moss", "reason": "r"}]}]})
        M._run_director(m)
        check(m["scenes"][0]["search_query"] == "honey fungus mushrooms", "_run_director applies a valid reply")
        m2 = {"scenes": [{"voiceover": "x", "search_query": "keep"}]}
        M._groq_chat = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        M._run_director(m2)
        check(m2["scenes"][0]["search_query"] == "keep", "an LLM failure leaves the manifest untouched")
        M._groq_chat = lambda *a, **k: None
        M._run_director(m2)
        check(m2["scenes"][0]["search_query"] == "keep", "an empty reply leaves the manifest untouched")
    finally:
        M._groq_chat = saved


def test_extra_clips_prefer_directed_shots_and_gate_on_their_own_subject():
    seen = []
    saved = (M._gather_candidates, M._download, M._clip_too_dark)
    M._gather_candidates = lambda q: (seen.append(q), [
        {"id": 7, "url": "u7", "desc": "microscope view of dna strand"},
        {"id": 8, "url": "u8", "desc": "night road"}])[1]
    M._download = lambda url, dest: open(dest, "wb").write(b"x")
    M._clip_too_dark = lambda p: False
    try:
        scene = {"search_query": "honey fungus", "shots": [{"query": "honey fungus", "reason": "a"},
                                                           {"query": "microscope dna strand", "reason": "b"}]}
        paths = M._extra_scene_clips(scene, 2, set(), os.path.join(tempfile.mkdtemp(), "x"))
    finally:
        M._gather_candidates, M._download, M._clip_too_dark = saved
    check(seen[0] == "microscope dna strand", f"directed shots are searched first ({seen})")
    check(len(paths) == 1, "the off-subject candidate is still refused")


def test_mood_and_keyword():
    check([D.scene_mood(i, 8, "") for i in (0, 3, 7)] == ["hook", "build", "payoff"], "hook / build / payoff by position")
    check(D.scene_mood(4, 8, "So why does it grow?") == "turn", "a question scene is a turn")
    for mood in D.MOODS:
        f = D.mood_filter(mood)
        sat = re.findall(r"saturation=([\d.]+)", f)
        check(all(float(x) <= 1.10 for x in sat), f"mood {mood!r} stays a mild nudge ({f!r})")
    check(D.mood_filter("nonsense") == "", "unknown mood adds nothing")
    words = [("It", 0.0, 0.2), ("grows", 0.2, 0.6), ("FUNGUS,", 0.9, 1.3)]
    check(D.keyword_time(words, ["fungus"]) == 0.9, "key word time found despite case/punctuation")
    check(D.keyword_time(words, ["whale"]) is None and D.keyword_time(words, []) is None, "no keyword -> no punch")


def test_scene_fields_use_scene_local_time():
    m = {"keyword": "honey fungus", "scenes": [{"voiceover": "It is big"}, {"voiceover": "The fungus grows"}]}
    wt = [("It", 0.1, 0.2), ("is", 0.2, 0.3), ("big", 0.3, 0.6),
          ("The", 2.1, 2.2), ("fungus", 2.3, 2.7), ("grows", 2.7, 3.0)]
    saved = M.WORD_TIMINGS[:]
    M.WORD_TIMINGS[:] = wt
    try:
        M._set_scene_director_fields(m, [("a", 2.0), ("b", 1.5)])
    finally:
        M.WORD_TIMINGS[:] = saved
    check(m["scenes"][0]["_n_scenes"] == 2 and "_punch_t" not in m["scenes"][0], "no keyword in scene 1 -> no punch")
    check(abs(m["scenes"][1]["_punch_t"] - 0.3) < 1e-6, f"punch time is relative to the scene start ({m['scenes'][1].get('_punch_t')})")
    M.WORD_TIMINGS[:] = []
    m2 = {"keyword": "fungus", "scenes": [{"voiceover": "the fungus"}]}
    M._set_scene_director_fields(m2, [("a", 1.0)])
    check("_punch_t" not in m2["scenes"][0], "without real word timings there is no punch-in")


def test_punch_and_sound_plan_pure():
    f = D.punch_in_filter(1.5)
    check(f.startswith(",scale=") and "eval=frame" in f and "crop=1080:1920:x=" in f, "punch-in scales per frame and crops centred")
    check("\\," in f and D.punch_in_filter(None) == "" and D.punch_in_filter(-1) == "", "commas escaped; None/negative -> nothing")
    check(D.PUNCH_AMOUNT <= 0.06, "the punch is subtle (<=6%)")
    plan = D.sound_plan(36.0, 30.0)
    kinds = [k for k, _, _ in plan]
    check(kinds == ["room", "riser", "impact"], f"room + riser + impact ({kinds})")
    riser = plan[1]
    check(abs(riser[1] + riser[2] - 30.0) < 1e-6 and plan[2][1] == 30.0, "the riser ENDS where the reveal starts; impact lands on it")
    check([k for k, _, _ in D.sound_plan(36.0, None)] == ["room"] and [k for k, _, _ in D.sound_plan(36.0, 1.0)] == ["room"],
          "no/too-early payoff -> room tone only")
    check(not M.SFX_CUTS, "cut whooshes stay OFF")


def _ffmpeg():
    return shutil.which("ffmpeg") is not None


def test_ffmpeg_punch_is_centred():
    if not _ffmpeg():
        print("SKIP ffmpeg not available"); return
    vf = "drawbox=x=0:y=0:w=1080:h=1920:color=white:t=20" + D.punch_in_filter(1.0) + ",format=rgb24"
    b = subprocess.check_output(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=2:r=30",
                                 "-vf", vf, "-f", "rawvideo", "-"])
    fs = 1080 * 1920 * 3

    def px(n, x, y):
        o = n * fs + (y * 1080 + x) * 3
        return tuple(b[o:o + 3])

    check(px(0, 5, 5) == (255, 255, 255), "no zoom before the key word")
    check(px(30, 5, 5)[0] < 10 and px(30, 1074, 1914)[0] < 10, "at the peak BOTH opposite corners are cropped: the zoom is centred")


def test_ffmpeg_bed_levels():
    if not _ffmpeg():
        print("SKIP ffmpeg not available"); return
    d = tempfile.mkdtemp()
    M.WORK = d
    bed = M._make_sound_bed(36.0, 30.0, os.path.join(d, "bed.wav"))
    check(bed is not None, "the sound bed builds")

    def lvl(ss, t):
        o = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-ss", str(ss), "-t", str(t), "-i", bed,
                            "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
        return float(re.search(r"mean_volume: (-?[\d.]+)", o).group(1)), float(re.search(r"max_volume: (-?[\d.]+)", o).group(1))

    room, riser, imp = lvl(0, 5), lvl(28.6, 1.4), lvl(30.0, 0.9)
    check(room[0] < -40, f"room tone is very quiet (mean {room[0]} dB)")
    check(-30 < riser[1] < -12 and -30 < imp[1] < -12, f"riser/impact are audible but far under narration (peaks {riser[1]}, {imp[1]} dB)")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
