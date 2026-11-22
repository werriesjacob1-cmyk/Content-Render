#!/usr/bin/env python3
"""Zero-network checks for operator-supplied manifests and the spelled-number key-term fix.

A committed manifest under manifests/ bypasses script generation, so it must clear EXACTLY the
rules a generated script would: validate() against its real bank fact, the craft rules and the
claim ledger. This runs on every push so a manifest can never be rendered without passing them.
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("GROQ_API_KEY", "x")
os.environ["LENGTH_MODE"] = "long"

import craft_rules as C
import generate as G


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


BANK = {f["id"]: f for f in json.load(open(os.path.join(ROOT, "topic_bank.json")))["facts"]}


def test_every_committed_manifest_clears_the_live_rules():
    paths = sorted(glob.glob(os.path.join(ROOT, "manifests", "*.json")))
    check(paths, "there is at least one operator manifest")
    for p in paths:
        m = json.load(open(p))
        fact = BANK.get(m.get("fact_id"))
        check(fact is not None, f"{os.path.basename(p)} names a real bank fact ({m.get('fact_id')})")
        import copy
        err = G.validate(copy.deepcopy(m), "EXPLAIN", fact=fact)
        check(err is None, f"{os.path.basename(p)} passes validate() ({err})")
        check(C.check_script(m["hook"], [s["voiceover"] for s in m["scenes"]], fact) is None,
              f"{os.path.basename(p)} passes the craft rules")
        check(m["hook"] == m["scenes"][0]["voiceover"], "the hook is the first spoken line")
        import main as MM
        for s in m["scenes"]:
            v = s.get("visual")
            if v is None:
                continue
            check(isinstance(v, dict) and v.get("type") in MM.VISUAL_TYPES, f"scene visual type is one of {MM.VISUAL_TYPES}")
            if v["type"] == "gauge":
                check(all(k in v for k in ("label", "start", "end", "unit", "before", "after")), "a gauge names its label, range, unit and both states")
                check(isinstance(v["start"], (int, float)) and isinstance(v["end"], (int, float)), "gauge numbers are numeric")
            if v["type"] == "timer":
                check(3 <= int(v["seconds"]) <= 60, "timer seconds in range")
                check(str(int(v["seconds"])) in s["voiceover"], "the timer shows a duration the narration actually states")


# Words Kokoro reads with the wrong pronunciation (found on a real render: run 463 read the verb
# "live" as the adjective /laiv/, and final QA scored narration_flow 4/10). Extend as found.
KOKORO_MISREAD = ("live", "lead", "midair", "cloaca")  # "lead" (the pencil/metal noun) was read as "laid" in run 500


def test_no_manifest_uses_a_word_kokoro_misreads():
    import re
    for p in sorted(glob.glob(os.path.join(ROOT, "manifests", "*.json"))):
        m = json.load(open(p))
        for sc in m["scenes"]:
            for w in KOKORO_MISREAD:
                check(not re.search(rf"\b{w}\b", sc["voiceover"], re.I),
                      f"{os.path.basename(p)} scene {sc['id']} avoids {w!r} (Kokoro misreads it)")


def test_spelled_out_numbers_satisfy_a_numeric_key_term():
    k = G._key_term_present
    check(k("15 seconds", "you have fifteen seconds"), "'fifteen seconds' names '15 seconds' (run 456 died 8x on this)")
    check(k("25 seconds", "twenty-five seconds") and k("25 seconds", "twenty five seconds"), "compound spelled numbers match")
    check(k("1,000 times", "one thousand times"), "'one thousand' names '1,000'")
    check(not k("15 seconds", "fourteen seconds") and not k("15 seconds", "fifty seconds"), "a DIFFERENT number does not match")
    check(k("15 seconds", "about 15 seconds") and not k("15 seconds", "about a minute"), "digits still work; unrelated text does not")
    check(not k("potassium-40", "forty"), "a proper-noun key term is not satisfied by a number word")


def test_workflow_manifest_input_is_safe():
    wf = open(os.path.join(ROOT, ".github", "workflows", "render.yml")).read()
    check("use_manifest:" in wf, "render.yml has the use_manifest input")
    check("MANIFEST_SRC: ${{ github.event.inputs.use_manifest }}" in wf, "the path reaches the shell only through an env var")
    check("manifests/*.json) ;;" in wf and "path traversal" in wf, "the path is restricted to manifests/*.json, no traversal")
    check("github.event.inputs.use_manifest == ''" in wf, "script generation is skipped when a manifest is supplied")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
