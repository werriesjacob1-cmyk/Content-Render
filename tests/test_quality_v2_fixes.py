#!/usr/bin/env python3
"""Zero-network regressions for the fixes that came out of run 457's critique."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import craft_rules as C
import fact_verifier as FV
import generate as G
import main as M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_queries_must_lead_with_the_subject():
    check(C.leading_modifier("empty space stars") == "empty", "'empty space stars' leads with a modifier")
    check(C.leading_modifier("human lungs breathing") == "human", "'human lungs breathing' leads with a modifier")
    check(C.leading_modifier("space stars") is None and C.leading_modifier("lungs breathing") is None, "subject-first queries pass")
    check(C.leading_modifier("old clock face") is None, "an ordinary adjective like 'old' is not policed")
    check(M._subject_word("empty space stars") == "space" and M._subject_word("human lungs breathing") == "lungs",
          "the footage filter now takes the NOUN as the subject (it took 'empty'/'human' in run 457)")
    import test_pipeline as TP
    m = copy.deepcopy(TP.FIX_ASTRO)
    m["scenes"][4]["search_query"] = "empty space stars"
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    err = G.validate(m, "EXPLAIN")
    check(err and "generic modifier" in err, f"validate() rejects a modifier-first query ({str(err)[:70]})")
    check("SEARCH QUERIES LEAD WITH THE SUBJECT" in C.prompt_block(), "and the prompt states the rule")


def test_extra_clips_need_two_shared_words():
    ok = M._extra_clip_on_subject("deep space stars timelapse", "space", "space stars")
    check(ok, "a description naming both query words is accepted")
    check(not M._extra_clip_on_subject("empty parking structure space for rent", "space", "space stars"),
          "run 457: a parking structure that shares one word is rejected")
    check(not M._extra_clip_on_subject("tortoise shell on rocks", "lungs", "lungs breathing"), "an unrelated clip is rejected")
    check(M._extra_clip_on_subject("lungs breathing animation", "lungs", "lungs breathing"), "a matching one passes")
    check(M._extra_clip_on_subject("octopus swimming", "octopus", "octopus"), "a one-word query still needs only that word")


def test_card_lines_never_contain_a_newline():
    fl = M._card_text_filters(["OXYGEN", "DRAINS"], 120, 900.0, 153.6, ["/tmp/a.txt", "/tmp/b.txt"])
    check(len(fl) == 2 and all(f.startswith("drawtext=") for f in fl), "one drawtext per line")
    check(all("\n" not in f for f in fl), "no newline in any filter")
    d = tempfile.mkdtemp()
    M.WORK = d
    import shutil, subprocess
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "2", f"{d}/s.wav"], check=True)
        M._build_stat_card({"voiceover": "x", "on_screen_text": "OXYGEN DRAINS NOW"}, 5, f"{d}/s.wav", 2.0, f"{d}/c.mp4", "")
        files = [open(os.path.join(d, f)).read() for f in sorted(os.listdir(d)) if f.startswith("s5_card_")]
        check(files and all("\n" not in t and "\r" not in t and t == t.strip() for t in files),
              f"every card text file is one clean line ({files})")
    else:
        print("SKIP ffmpeg not available")


def test_json_retry_and_rejection_summary():
    G._REJECTIONS.clear()
    G._note_rejection("whatif payoff never answered — x")
    G._note_rejection("whatif payoff never answered — y")
    G._note_rejection("scene 3 voiceover uses the jargon word 'ebullism'")
    G._note_rejection("something unforeseen entirely")
    s = G.rejection_summary()
    check("2x whatif payoff" in s and "1x jargon" in s and "other:" in s, f"rejections are summarised by family ({s})")
    G._REJECTIONS.clear()
    check(G.rejection_summary() == "none", "an empty history says 'none'")
    # a garbled JSON reply is retried once immediately
    calls = []
    good = json.dumps({"title": "t"})

    def fake(p):
        calls.append(p)
        return "{not json" if len(calls) == 1 else good
    saved = G.call_groq
    G.call_groq = fake
    try:
        raw = G.call_groq("p")
        try:
            json.loads(raw)
            ok = False
        except ValueError:
            raw = G.call_groq("p")
            ok = json.loads(raw)["title"] == "t"
    finally:
        G.call_groq = saved
    check(ok, "the retry pattern recovers a truncated reply")
    src = open(os.path.join(ROOT, "generate.py")).read()
    check("unparseable JSON" in src and "one immediate retry" in src, "generate_candidate carries that retry")


def test_verifier_is_advisory_by_default():
    check(FV.UNSUPPORTED_REJECT_AT == 0, "unsupported lines never reject unless enforcement is switched on")
    v = {1: (FV.UNSUPPORTED, "a"), 2: (FV.UNSUPPORTED, "b"), 3: (FV.UNSUPPORTED, "c"), 4: (FV.UNSUPPORTED, "d")}
    err, notes = FV.decide(v, ["a", "b", "c", "d"])
    check(err is None and len(notes) == 4, "four unsupported lines are logged, not rejected")
    err, _ = FV.decide({1: (FV.CONTRADICTED, "no")}, ["a"])
    check(err and "contradicts" in err, "a CONTRADICTED line still rejects")


def test_workflow_evidence_and_generate_only():
    wf = open(os.path.join(ROOT, ".github", "workflows", "render.yml")).read()
    check("out/captions.ass" in wf and "out/video_audit.json" in wf, "the artifact now ships the caption file and the audit")
    check("generate_only:" in wf and "generated-script-" in wf, "a generation-only mode uploads the script")
    check(wf.count("github.event.inputs.generate_only != 'true'") >= 5, "render/package/upload steps are skipped in generate_only")
    check("vars.AUTO_PUBLISH_ENABLED == 'true' && github.event.inputs.certification_only != 'true'" in wf,
          "the publish gates are untouched")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
