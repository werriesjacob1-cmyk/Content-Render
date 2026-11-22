#!/usr/bin/env python3
"""Zero-network regressions for the curiosity gate and the operator fact pin."""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import curiosity_gate as C
import generate as G


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


BANK = json.load(open(os.path.join(C.ROOT, "topic_bank.json")))["facts"]


def test_scores_rank_mechanism_and_violation_above_magnitude():
    good = {"fact": "You would not freeze solid in space; the vacuum boils the water in your body "
                    "because pressure drops, yet you stay conscious.", "whatif": "What if you were flung out?"}
    mag = {"fact": "The Antarctic ice sheet is the largest single mass of ice on Earth, covering over 14 million square kilometres."}
    gs, gn = C.score_fact(good)
    ms, mn = C.score_fact(mag)
    check(gs >= C.KEEP_AT_LEAST and gs > ms, f"mechanism + violation outranks magnitude ({gs} vs {ms})")
    check("MAGNITUDE-ONLY" in mn and C.verdict(ms, mn) == "reject", "a magnitude-only fact is rejected, with the reason named")
    check(C.verdict(2, ["mechanism x1"]) == "weak", "a low score alone is NOT a rejection (heuristic cannot see every mechanism)")


def test_real_bank_known_good_premises_are_never_rejected():
    ids = {r["id"]: r for r in C.rank(BANK)}
    for fid in ("atoms_empty", "birthday_paradox", "flavor_is_mostly_smell", "liver_regrows",
                "petrichor_rain_smell", "human_vacuum", "glass_solid", "water_expands_ice"):
        check(ids[fid]["verdict"] != "reject", f"{fid} survives the gate")
    rej = [i for i, r in ids.items() if r["verdict"] == "reject"]
    check(len(rej) <= 0.05 * len(BANK), f"the gate is conservative ({len(rej)} of {len(BANK)} rejected)")
    check(ids["human_vacuum"]["verdict"] == "keep", "the strongest premise ranks as keep")


def test_selectable_bank_applies_gate_fail_open():
    keep = [f for f in BANK if f["id"] not in C.rejected_ids()]
    check(len(G.selectable_bank(BANK, quarantined=set())) == len(keep), "gate rejects are removed from selection")
    os.environ["CURIOSITY_GATE"] = "0"
    try:
        check(len(G.selectable_bank(BANK, quarantined=set())) == len(BANK), "CURIOSITY_GATE=0 restores the full bank")
    finally:
        os.environ.pop("CURIOSITY_GATE", None)
    d = tempfile.mkdtemp()
    bad = os.path.join(d, "s.json"); open(bad, "w").write("{not json")
    check(C.rejected_ids(bad) == set() and C.rejected_ids(os.path.join(d, "none.json")) == set(),
          "a corrupt or missing score file rejects nothing")


def test_committed_scores_match_the_scorer():
    committed = {r["id"]: r["score"] for r in json.load(open(C.SCORES_PATH))["scores"]}
    fresh = {r["id"]: r["score"] for r in C.rank(BANK)}
    check(committed == fresh, "curiosity_scores.json is current (re-run: python curiosity_gate.py --write)")


def test_forced_fact_pin():
    check(G.pick_forced_fact("human_vacuum", BANK)["id"] == "human_vacuum", "a valid id is pinned")
    check(G.pick_forced_fact("", BANK) is None and G.pick_forced_fact(None, BANK) is None, "empty pin = normal selection")
    check(G.pick_forced_fact("no_such_fact", BANK) is None, "an unknown id falls back to normal selection")
    rej = sorted(C.rejected_ids())[0]
    check(G.pick_forced_fact(rej, BANK)["id"] == rej, "a deliberate pin is honoured even for a gate-rejected fact")
    wf = open(os.path.join(C.ROOT, ".github", "workflows", "render.yml")).read()
    check("fact_id:" in wf and "FORCE_FACT_ID: ${{ github.event.inputs.fact_id || '' }}" in wf,
          "render.yml passes the input through an env var (never interpolated into shell)")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
