#!/usr/bin/env python3
"""Zero-network regressions for the claim ledger, the fact verifier and the timer card."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import claim_ledger as L
import fact_verifier as FV
import generate as G
import main as M


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


LINES = ["Your body would not explode in space.", "You stay conscious for about 15 seconds.",
         "Animals survive two minutes flatlined."]


def test_ledger_flags_pure_restatement_only():
    ok = ["Venus has a day longer than its year.", "One spin takes 243 Earth days.",
          "The trip around the Sun takes only 225 days."]
    check(L.lint(ok) is None, "scenes that each add a claim pass")
    bad = ok + ["A day on Venus is longer than its year, one spin around."]
    check("adds almost nothing new" in (L.lint(bad) or ""), "a scene that re-says earlier words is rejected")
    check(L.lint(["Hook line about volcanoes erupting.", "Yes. Right.", "Wow so true."]) is None,
          "short transition lines are exempt")
    led = L.build_ledger(["It takes 15 seconds.", "At 1,200 beats a minute it races."])
    check(led[0]["numbers"] == ["15"] and led[1]["numbers"] == ["1,200"], "numbers are recorded per scene")
    check(all("novel_fraction" in e for e in led), "each entry says how much is new")


def test_verifier_parse_and_decide():
    reply = 'noise {"lines":[{"n":1,"verdict":"supported","why":"in source"},' \
            '{"n":2,"verdict":"SUPPORTED","why":"x"},{"n":3,"verdict":"UNSUPPORTED","why":"source says vacuum exposure"}]} tail'
    v = FV.parse(reply, 3)
    check(v[1][0] == FV.SUPPORTED and v[3][0] == FV.UNSUPPORTED, "verdicts parsed, case-insensitive, noise ignored")
    err, notes = FV.decide(v, LINES)
    check(err is None and len(notes) == 1 and "flatlined" in notes[0], "ONE unsupported line is logged, not rejected")
    two = dict(v); two[2] = (FV.UNSUPPORTED, "no 15 s in source")
    err, _ = FV.decide(two, LINES)
    check(err and "2 lines" in err, "two unsupported lines reject the script")
    con = dict(v); con[1] = (FV.CONTRADICTED, "source says it would not explode")
    err, _ = FV.decide(con, LINES)
    check(err and "contradicts" in err and "line 1" in err, "a contradicted line rejects at once")
    check(FV.parse("not json", 3) == {} and FV.parse(None, 3) == {}, "garbage parses to nothing")
    check(FV.parse('{"lines":[{"n":9,"verdict":"SUPPORTED"},{"n":1,"verdict":"MAYBE"}]}', 3) == {},
          "out-of-range lines and unknown verdicts are ignored")
    p = FV.build_prompt("SRC TEXT", LINES)
    check("SRC TEXT" in p and "1. Your body" in p and "flatlined" in p, "the prompt carries the source, the numbered lines and the example failure word")


def _manifest():
    return {"scenes": [{"voiceover": t} for t in LINES]}


def test_verify_claims_wiring_and_fail_open():
    fact = {"fact": "You stay conscious about 15 seconds in vacuum.", "wow": "Animals survived ~90 s of exposure."}
    saved = G.call_groq
    try:
        G.call_groq = lambda p: json.dumps({"lines": [{"n": 1, "verdict": "SUPPORTED", "why": ""},
                                                       {"n": 2, "verdict": "SUPPORTED", "why": ""},
                                                       {"n": 3, "verdict": "CONTRADICTED", "why": "exposure, not flatlined"}]})
        err = G.verify_claims(_manifest(), fact, "dossier text")
        check(err and "flatlined" in err.lower() or (err and "contradicts" in err), f"the run-455 style line is rejected ({err})")
        G.call_groq = lambda p: "this is not json at all"
        check(G.verify_claims(_manifest(), fact, "d") is None, "a garbled checker fails OPEN")
        G.call_groq = lambda p: (_ for _ in ()).throw(RuntimeError("down"))
        check(G.verify_claims(_manifest(), fact, "d") is None, "a down checker fails OPEN")
        G.call_groq = lambda p: json.dumps({"scenes": []})
        check(G.verify_claims(_manifest(), fact, "d") is None, "a reply that is a manifest, not verdicts, is ignored")
        os.environ["FACT_VERIFY"] = "0"
        called = []
        G.call_groq = lambda p: called.append(p) or "{}"
        check(G.verify_claims(_manifest(), fact, "d") is None and not called, "FACT_VERIFY=0 makes no call")
    finally:
        G.call_groq = saved
        os.environ.pop("FACT_VERIFY", None)
    check(G.verify_claims(_manifest(), {}, None) is None, "no source material -> nothing to check against")


def test_validate_stores_ledger_and_applies_lint():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import copy
    import test_pipeline as TP
    m = copy.deepcopy(TP.FIX_ASTRO)
    check(G.validate(m, "EXPLAIN") is None and len(m.get("claim_ledger", [])) == len(m["scenes"]),
          "a valid script gets a claim ledger written into its manifest")
    m = copy.deepcopy(TP.FIX_ASTRO)
    m["scenes"][5]["voiceover"] = "A single day on Venus is longer than its whole year there."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    err = G.validate(m, "EXPLAIN")
    check(err is not None, f"a scene that only restates earlier scenes is rejected ({str(err)[:90]})")


def test_countdown_detection_and_card():
    check(M._countdown_seconds({"voiceover": "pass out in only 15 seconds"}) == 15, "stated duration found")
    check(M._countdown_seconds({"voiceover": "two minutes"}) is None, "no digits -> none")
    check(M._countdown_seconds({"voiceover": "a 2 second blink"}) is None, "below 3 s is not a countdown")
    check(M._countdown_seconds({"voiceover": "about 90 seconds"}) is None, "above 60 s is not a countdown")
    check(M._countdown_seconds({"voiceover": "x", "on_screen_text": "15 SECONDS"}) == 15, "the on-screen label counts too")
    if not shutil.which("ffmpeg"):
        print("SKIP ffmpeg not available"); return
    d = tempfile.mkdtemp()
    M.WORK = d
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "4", f"{d}/s.wav"], check=True)
    M._build_timer_card({"voiceover": "x"}, 4, f"{d}/s.wav", 4.0, f"{d}/t.mp4", 15)

    def fr(t):
        return subprocess.check_output(["ffmpeg", "-v", "error", "-ss", str(t), "-i", f"{d}/t.mp4", "-frames:v", "1",
                                        "-vf", "scale=54:96,format=gray", "-f", "rawvideo", "-"])
    a, b, c = fr(0.2), fr(1.5), fr(3.6)
    dif = lambda x, y: sum(abs(p - q) for p, q in zip(x, y)) / len(x)
    check(dif(a, b) > 0.5 and dif(b, c) > 0.5, "the timer card's number really changes over time")
    check(abs(M.ffprobe_dur(f"{d}/t.mp4") - 4.0) < 0.15, "and it is exactly the requested length")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
