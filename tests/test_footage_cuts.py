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
                       ([3.5, 3.5], [20.0, 20.0, 20.0]), ([1.9], [5.0])):
        cuts = M._cut_plan(plan, srcs)
        check(_sum(cuts) == round(sum(plan), 3), f"plan {plan} over {srcs}: cuts sum to the scene length")


def test_cut_plan_every_clip_gets_a_turn_then_new_inpoints_only():
    cuts = M._cut_plan([2.0] * 4, [10.0, 10.0])
    check([c[0] for c in cuts[:2]] == [0, 1], "each distinct clip is used before any is revisited")
    seen = {}
    for si, off, d in cuts:
        for (o2, d2) in seen.get(si, []):
            check(off >= o2 + d2 - 1e-6, f"clip {si}: window {off}-{off + d} does not re-show {o2}-{o2 + d2}")
        seen.setdefault(si, []).append((off, d))
    check(all(off + d <= 10.05 for _, off, d in cuts), "every window lies inside real footage")


def test_cut_plan_holds_instead_of_padding_when_footage_runs_out():
    cuts = M._cut_plan([1.9] * 4, [2.0])                     # one 2 s clip for a 7.6 s scene
    check(len(cuts) == 1 and cuts[0][0] == 0 and cuts[0][1] == 0.0, f"one clip, one hold ({cuts})")
    check(_sum(cuts) == 7.6, "the hold still covers the whole scene (audio sync preserved)")
    cuts = M._cut_plan([1.9] * 4, [2.0, 2.0])
    check(len(cuts) == 2 and {c[0] for c in cuts} == {0, 1}, f"two clips -> two cuts, never a cycled repeat ({cuts})")
    check(all(c[0] in (0, 1) for c in cuts), "only real source indexes are ever used")


def test_hold_cap_met_when_footage_exists_and_reported_when_not():
    ok = M._cut_plan([1.9] * 4, [30.0])                      # a long clip: new in-points, short holds
    check(M._longest_hold(ok) <= M.HOLD_CAP_S, f"longest hold {M._longest_hold(ok)}s <= cap {M.HOLD_CAP_S}s")
    check(len(ok) == 4, "a long single clip is cut at new in-points, not held")
    starved = M._cut_plan([1.9] * 4, [1.5])
    check(M._longest_hold(starved) > M.HOLD_CAP_S, "a starved scene is the ONLY case allowed over the cap (and is logged)")
    final = M._cut_plan(M._subclip_plan(7.0, 1.9, 6), [9.0, 9.0])   # a 7 s final scene
    check(M._longest_hold(final) <= M.HOLD_CAP_S, f"a 7 s final scene is cut, not held ({final})")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
