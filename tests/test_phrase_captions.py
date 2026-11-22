#!/usr/bin/env python3
"""Zero-network regressions for phrase captions + the caption-sync contract.

No ffmpeg, no audio, no model: build_ass is fed synthetic word timings and the
resulting ASS text is inspected. The measurement tool's pure helpers are tested
with known offsets so a real run's numbers can be trusted.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import main as M
import measure_caption_sync as MS


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


SENT = ("The biggest living thing on Earth is a fungus you have walked over. "
        "So is it one animal, or thousands of separate ones? "
        "Genetic tests say every thread shares exactly the same DNA.")


def _timings(text=SENT, start=0.2, per=0.28, pause_after_period=0.4):
    out, t = [], start
    for w in text.split():
        out.append((w, round(t, 3), round(t + per, 3)))
        t += per + (pause_after_period if w[-1] in ".?!" else 0.0)
    return out


def test_groups_cover_every_word_and_respect_limits():
    wt = _timings()
    groups = M._phrase_groups(wt)
    flat = [w for g in groups for w, _, _ in g]
    check(flat == [w for w, _, _ in wt], "every word kept, in order (word-for-word coverage)")
    check(all(1 <= len(g) <= M.CAPTION_PHRASE_MAX_WORDS for g in groups), "no phrase over 3 words")
    check(all(len(" ".join(w for w, _, _ in g)) <= M.CAPTION_PHRASE_MAX_CHARS + 6 for g in groups),
          "no phrase far over the character budget")
    fn = M._CAPTION_FUNCTION_WORDS
    bad = [g for g in groups if len(g) > 1 and M._bare(g[-1][0]).lower() in fn
           and not M._PHRASE_BREAK_RE.search(g[-1][0])]
    check(len(bad) <= 1, f"phrases (almost) never end on a function word ({len(bad)} did)")
    # a phrase never spans a sentence end: no group has punctuation in its middle
    check(all(not M._PHRASE_BREAK_RE.search(w) for g in groups for w, _, _ in g[:-1]),
          "a phrase never runs across punctuation or a clause break")


def test_pause_breaks_a_phrase():
    wt = [("one", 0.0, 0.2), ("two", 0.25, 0.45), ("three", 1.5, 1.7), ("four", 1.75, 1.95)]
    check([len(g) for g in M._phrase_groups(wt)] == [2, 2], "a long spoken pause starts a new phrase")


def test_emphasis_and_size():
    check(M._emphasis_indexes(["THE", "BIGGEST", "LIVING"], keyword_tokens=set()) == [1],
          "longest content word is emphasised")
    check(M._emphasis_indexes(["HONEY", "FUNGUS", "GROWS"], keyword_tokens={"FUNGUS"}) .count(1) == 1,
          "the video keyword is emphasised first")
    check(len(M._emphasis_indexes(["A", "BIGGEST", "243", "ORGANISM"], keyword_tokens=set())) <= 2,
          "at most 2 emphasised words")
    check(len(M._emphasis_indexes(["BIGGEST", "ORGANISM"], keyword_tokens={"BIGGEST", "ORGANISM"})) == 1,
          "a two-word phrase gets at most one")
    base = int(M.PROFILE.get("cap_size", 120))
    for t in ("HI", "THE BIGGEST LIVING", "SCIENTISTS STILL ARGUE NOW", "W" * 22):
        fs = M._phrase_font_size(t)
        check(M.CAPTION_MIN_FS <= fs <= base, f"font size {fs} within [{M.CAPTION_MIN_FS},{base}] for {t[:12]!r}")
        if len(t) > 3 and fs > M.CAPTION_MIN_FS:
            check(0.36 * len(t) * fs <= M.CAPTION_SAFE_W + 1, f"estimated width of {t[:12]!r} fits the safe width")


def test_events_abut_light_one_word_and_start_at_zero():
    g = M._phrase_groups(_timings())[0]
    ev = M._phrase_events(g, next_start=None, at_zero=True)
    check(len(ev) == len(g), "one event per word of the phrase")
    parsed = MS.parse_ass("\n".join(ev))
    check(parsed[0][0] == 0.0, "the first event starts at t=0 (hook on screen from frame 0)")
    check("\\fad" not in ev[0] and "\\t(" not in ev[0], "no fade-in on the t=0 event (it would blank frame 0)")
    check(all(abs(parsed[i][1] - parsed[i + 1][0]) < 0.011 for i in range(len(parsed) - 1)),
          "events abut: no flicker gap inside a phrase")
    accent = M.PROFILE["cap_accent"]
    check(all(e.count(accent) == 1 for e in ev), "exactly one word is lit per event")
    check([MS._NAME_RE.fullmatch(e.split(",", 5)[4]).group(1) for e in ev] == [str(i) for i in range(len(g))],
          "the Name field names the active word")
    later = M._phrase_events(g, next_start=5.0, at_zero=False)
    check("\\fad" in later[0], "a phrase that does not start at 0 keeps its fade/pop-in")


def _build(headline="", style=None, scenes=None, actual=None, timings=None):
    saved = (M.CAPTION_STYLE, list(M.WORD_TIMINGS))
    M.WORD_TIMINGS[:] = timings or _timings()
    if style:
        M.CAPTION_STYLE = style
    try:
        sc = scenes or [{"voiceover": " ".join(SENT.split()[:12])}, {"voiceover": " ".join(SENT.split()[12:])}]
        n1 = len(sc[0]["voiceover"].split())
        segs = [("s1.mp3", M.WORD_TIMINGS[n1 - 1][2] + 0.1), ("s2.mp3", 8.0)]
        act = actual or [segs[0][1], 8.0]
        with tempfile.NamedTemporaryFile("w+", suffix=".ass", delete=False) as f:
            path = f.name
        M.build_ass(sc, segs, act, path, headline=headline)
        txt = open(path).read()
        os.unlink(path)
        return txt, MS.parse_ass(txt)
    finally:
        M.CAPTION_STYLE, M.WORD_TIMINGS[:] = saved[0], saved[1]


def test_build_ass_layers_safe_zone_and_single_caption_track():
    txt, ev = _build()
    check(len(ev) >= len(SENT.split()), "at least one event per spoken word")
    check(ev[0][0] == 0.0, "frame 0 carries the hook text")
    srt = sorted(ev)
    check(all(srt[i][1] <= srt[i + 1][0] + 0.011 for i in range(len(srt) - 1)),
          "no two caption events overlap (no double caption)")
    check(not re.search(r"\\an8", txt), "no separate top headline layer alongside the captions")
    ys = [int(y) for y in re.findall(r"\\pos\(540,(\d+)\)", txt)]
    check(ys and all(230 <= y <= 1440 for y in ys), f"captions sit inside the platform safe zone (y={set(ys)})")
    check(len(re.findall(r"Dialogue:", txt)) == len(ev), "every Dialogue line parses")


def test_word_style_still_available():
    txt, ev = _build(style="word")
    check(len(ev) <= len(SENT.split()) and "Pop,w" not in txt, "CAPTION_STYLE=word restores one event per word")


def test_sync_contract_word_start_plus_shift_plus_delay():
    """Each caption's ACTIVE word appears at: word start + that scene's cut-rounding shift
    + CAPTION_DELAY_S. This pins the mapping the real-audio measurement validated."""
    timings = _timings()
    n1 = 12
    seg1 = timings[n1 - 1][2] + 0.1
    shift = 0.23                                  # the real fixture showed up to 0.23s of drift
    txt, ev = _build(actual=[seg1 + shift, 8.0], timings=timings)
    by_word = {}
    for st, _, key, _ in ev:
        by_word.setdefault(key, st)
    for i in (n1 + 1, n1 + 3):                    # words in scene 2
        w = re.sub(r"[^a-z0-9]", "", timings[i][0].lower())
        exp = timings[i][1] + shift + M.CAPTION_DELAY_S
        check(abs(by_word[w] - exp) < 0.03, f"scene-2 word {w!r}: caption at {by_word[w]:.2f}s, expected {exp:.2f}s")


def test_measure_helpers():
    ass = ("Dialogue: 0,0:00:00.10,0:00:00.40,Pop,w1,0,0,0,,{\\pos(1,1)}A {\\c&H1&}BIG{\\fscx100} DOG\n"
           "Dialogue: 0,0:00:00.40,0:00:00.90,Pop,,0,0,0,,{\\pos(1,1)}RAN\n")
    ev = MS.parse_ass(ass)
    check(ev[0][2] == "big" and ev[1][2] == "ran", "active word read from Name field, else first word")
    heard = [("A", 0.0, 0.1), ("big", 0.05, 0.3), ("dog", 0.3, 0.4), ("ran", 0.30, 0.5)]
    pairs = MS.match_events(ev, heard)
    rep = MS.summarize(pairs, len(ev))
    check(rep["matched"] == 2 and abs(rep["median_s"] - 0.075) < 0.001, f"offsets computed correctly ({rep})")
    check(MS.summarize([(0.0, 0.5, "x")], 1)["lead_gt_0.10s"] == 1, "a caption BEFORE the voice is counted as a lead")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
