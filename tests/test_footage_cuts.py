#!/usr/bin/env python3
"""Zero-network regressions for the footage-cut rules.

User complaints these pin: unrelated stock padded into a scene (night road,
lumberjack, brick wall), the same clip cycled back in as a fake cut, and one
hazy shot held for ~7 s. All decisions are pure functions; nothing here touches
the network or ffmpeg.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import main as M


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_variants_never_a_single_word():
    for q in ("honey fungus mushrooms forest", "pond turtle swimming", "octopus", "dark", "the a of", ""):
        v = M._variant_queries(q)
        multi = [x for x in v if x != q]
        check(all(len(x.split()) >= 2 for x in multi), f"{q!r}: no single-word variant ({v})")
    check(M._variant_queries("honey fungus mushrooms forest")[0] == "honey fungus mushrooms forest",
          "the full phrase is always tried first")
    check(all(x.lower().startswith("honey") for x in M._variant_queries("honey fungus mushrooms forest")),
          "every variant keeps the subject word")
    check(M._variant_queries("octopus") == ["octopus"], "a one-word query has no variants (hold the clip instead)")


def test_extra_scene_clips_never_searches_a_bare_word_or_takes_unrelated_stock():
    seen = []
    saved = (M._gather_candidates, M._download, M._clip_too_dark)
    pool = [{"id": 1, "url": "u1", "desc": "honey fungus mushrooms on a log"},
            {"id": 2, "url": "u2", "desc": "night road with car lights"},          # unrelated
            {"id": 3, "url": "u3", "desc": "lumberjack cutting a tree"}]          # unrelated
    M._gather_candidates = lambda q: (seen.append(q), pool)[1]
    got = []
    M._download = lambda url, dest: got.append(url) or open(dest, "wb").write(b"x")
    M._clip_too_dark = lambda p: False
    try:
        import tempfile
        d = tempfile.mkdtemp()
        paths = M._extra_scene_clips({"search_query": "honey fungus mushrooms forest"}, 3, set(),
                                     os.path.join(d, "s1_sub"))
    finally:
        M._gather_candidates, M._download, M._clip_too_dark = saved
    check(seen and all(len(q.split()) >= 2 for q in seen), f"no bare single-word query was searched ({seen})")
    check(got == ["u1"], f"only the on-subject candidate was downloaded ({got})")
    check(len(paths) == 1, "asked for 3 extras, got 1: it is not padded with unrelated stock")


def test_no_subject_means_no_extras():
    check(M._extra_clip_on_subject("anything at all", "") is False, "no subject word -> no extra clip allowed")
    check(M._extra_clip_on_subject("honey fungus on bark", "fungus") is True, "subject named -> allowed")
    check(M._extra_clip_on_subject("night road", "fungus") is False, "subject absent -> rejected")


def _sum(cuts):
    return round(sum(c[2] for c in cuts), 3)


def test_cut_plan_covers_the_scene_exactly():
    for plan, srcs in (([1.75] * 4, [8.0, 6.0]), ([2.0, 2.0, 2.0], [12.0]), ([1.9] * 3, [1.0]),
                       ([3.5, 3.5], [20.0, 20.0, 20.0]), ([1.9], [5.0]), ([1.9] * 4, []), ([2.0] * 5, [9.0] * 5)):
        cuts = M._cut_plan(plan, srcs)
        check(_sum(cuts) == round(sum(plan), 3), f"plan {plan} over {srcs}: cuts sum to the scene length")


def test_a_clip_is_never_revisited_and_pace_is_kept_when_footage_allows():
    cuts = M._cut_plan([1.9] * 4, [10.0, 10.0, 10.0, 10.0])
    check([c[0] for c in cuts] == [0, 1, 2, 3] and all(c[1] == 0.0 for c in cuts),
          "enough clips -> the fast planned pace, each clip once, always from its start")
    for plan, srcs in (([1.9] * 4, [30.0]), ([1.9] * 4, [10.0, 10.0]), ([2.0] * 3, [12.0])):
        used = [c[0] for c in M._cut_plan(plan, srcs) if c[0] is not None]
        check(len(used) == len(set(used)), f"{srcs}: no source appears twice (no same-clip 'cuts')")


def test_hold_cap_and_cards_replace_long_holds():
    one = M._cut_plan(M._subclip_plan(7.0, 1.9, 6), [10.0])            # run-455 scene 7 shape: one 8 s still
    check(one[0][0] == 0 and one[0][2] == M.HOLD_CAP_S, f"the single source is held only to the cap ({one})")
    check(all(c[0] is None for c in one[1:]) and one[1:], "the rest of the scene is filler cards, not a longer hold")
    check(M._longest_hold(one) <= M.CARD_MAX_S, f"nothing passes {M.CARD_MAX_S}s ({M._longest_hold(one)}s)")
    check(_sum(one) == 7.0, "the scene is still covered exactly (audio sync preserved)")
    sliver = M._cut_plan([1.9, 1.9], [10.0])                           # 3.8 s: a sliver over the cap is not worth a card
    check(len(sliver) == 1 and sliver[0][2] == 3.8, f"a 3.8 s scene on one clip just runs ({sliver})")
    two = M._cut_plan([1.9] * 4, [5.0, 5.0])
    check(all(c[2] <= M.HOLD_CAP_S + 1e-9 for c in two), f"two clips for 7.6 s share the time under the cap ({two})")
    check(M._cut_plan([1.9] * 4, []) and all(c[0] is None for c in M._cut_plan([1.9] * 4, [])),
          "no footage at all -> cards only")


def test_safe_window_avoids_black():
    fps = 4
    series = [5.0] * 8 + [80.0] * 40                      # 2 s black head, then bright
    check(M._safe_window(series, fps, 0.0, 3.0) == 2.0, "a black head is skipped")
    check(M._safe_window([5.0] * 40, fps, 0.0, 3.0) is None, "an all-black clip has no safe window")
    check(M._safe_window([80.0] * 40, fps, 0.0, 3.0) == 0.0, "a bright clip starts where asked")
    check(M._safe_window([], fps, 1.0, 3.0) == 1.0, "no series (probe failed) -> do not block the shot")
    mid = [80.0] * 12 + [5.0] * 8 + [80.0] * 40
    off = M._safe_window(mid, fps, 0.0, 4.0)
    check(off is not None and off >= 5.0, f"a black stretch in the middle is stepped over ({off})")
    check(M._safe_window([80.0] * 6, fps, 0.0, 3.0) == 0.0 and M._safe_window([5.0] * 6, fps, 0.0, 3.0) is None,
          "a short clip that loops is judged as a whole")


def test_still_must_name_the_subject():
    check(M._still_matches_query("File:Astronaut spacewalk ISS.jpg", "astronaut spacewalk"), "a matching title is accepted")
    check(not M._still_matches_query("Nicole Stott speaks to an audience astronaut lecture", "astronaut spacewalk"),
          "run 455: an astronaut LECTURE is not an 'astronaut spacewalk'")
    check(M._still_matches_query("octopus", "octopus"), "a one-word query needs that word")
    check(not M._still_matches_query("a beach", "octopus"), "and rejects a label without it")
    check(M._still_matches_query("anything", ""), "no query words -> no filter")


def test_gather_stills_distinct_and_titled():
    saved = (M._inaturalist_image, M._openverse_image, M._wikimedia_image, M._frame_stats)
    calls = []
    imgs = iter(["a.jpg", "b.jpg", "c.jpg"])
    M._inaturalist_image = lambda q, dest: False
    def ov(q, dest, skip=None):
        calls.append(q); u = next(imgs, None)
        if u is None: return False
        skip.add(u); open(dest, "wb").write(b"x"); return True
    M._openverse_image = ov
    M._wikimedia_image = lambda q, dest, skip=None: False
    M._frame_stats = lambda p: (80.0, 50.0)
    try:
        d = tempfile.mkdtemp()
        paths, provs = M._gather_stills("honey fungus mushrooms forest", 3, os.path.join(d, "s"))
    finally:
        M._inaturalist_image, M._openverse_image, M._wikimedia_image, M._frame_stats = saved
    check(len(paths) == 3 and len(set(paths)) == 3, "three distinct stills are gathered")
    check(all(len(q.split()) >= 2 for q in calls), f"searched with subject phrases, never a bare word ({calls})")
    M._frame_stats = lambda p: (5.0, 50.0)
    M._openverse_image = ov; imgs = iter(["a.jpg"])
    try:
        paths2, _ = M._gather_stills("honey fungus", 1, os.path.join(d, "t"))
    finally:
        M._frame_stats = saved[3]
    check(paths2 == [], "a near-black still is refused")


def test_scene_renders_with_real_ffmpeg():
    import shutil, subprocess
    if not shutil.which("ffmpeg"):
        print("SKIP ffmpeg not available"); return
    import video_audit
    W = tempfile.mkdtemp()
    M.WORK = M.OUT = W
    ins = []
    for c in ("red", "green", "blue", "yellow", "white"):
        ins += ["-f", "lavfi", "-i", f"color=c={c}:s=540x960:d=2:r=30"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", "[0][1][2][3][4]concat=n=5:v=1:a=0",
                    "-pix_fmt", "yuv420p", f"{W}/A.mp4"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "7.0",
                    "-q:a", "5", f"{W}/seg.mp3"], check=True)
    saved = (M.fetch_clip, M._extra_scene_clips, M._clip_luma)
    M.fetch_clip = lambda q, dest, **k: (shutil.copy(f"{W}/A.mp4", dest), (True, 9))[1]
    M._extra_scene_clips = lambda scene, need, ex, prefix: []
    M._clip_luma = lambda p: (120, 20)
    try:
        sc = {"voiceover": "It takes 15 seconds.", "search_query": "honey fungus mushrooms", "motion": "zoom_in",
              "_n_scenes": 8, "on_screen_text": "15 SECONDS"}
        out = M.build_scene(sc, 3, f"{W}/seg.mp3", 7.0)
    finally:
        M.fetch_clip, M._extra_scene_clips, M._clip_luma = saved
    check(abs(M.ffprobe_dur(out) - 7.0) < 0.15, f"the scene is exactly its narration length ({M.ffprobe_dur(out):.2f}s)")
    r = video_audit.audit_video(out)
    check(r["longest_hold_s"] <= M.CARD_MAX_S + 0.3, f"a one-clip 7 s scene no longer sits on one shot ({r['longest_hold_s']}s)")
    check(r["effective_shots"] >= 2, "the picture really changes (clip, then card)")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
