#!/usr/bin/env python3
"""Zero-network regressions for deterministic private-certification seed."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_writer_evidence_seed as S
import writer_v2 as W


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def venus_fact():
    return {
        "id": "venus_day",
        "domain": "space",
        "fact": "A day on Venus is longer than its year: one rotation takes 243 Earth days, while one trip around the Sun takes only 225.",
        "angle": "time itself works differently elsewhere",
        "key_terms": ["243 Earth days", "225 days", "retrograde"],
        "whatif": "What if you tried to live out a single year on Venus? You wouldn't even finish one day, because a Venus day of 243 Earth days outlasts its 225-day year.",
        "wow": "Venus also spins in retrograde, the opposite direction to almost every other planet, so the Sun there rises in the west and sets in the east.",
        "queries": ["planet venus surface", "planets orbiting sun", "space planet rotation"],
    }


def test_seed_is_bound_to_exact_curated_claims_and_writer_shape():
    fact = venus_fact()
    inventory = W.build_claim_inventory(fact, dossier_facts=[], grounded=False)
    seed = S.build_evidence_seed(fact, inventory)
    check(seed is not None, "current curated Venus evidence produces deterministic seed")
    check(seed["hook"].endswith(".") and not seed["hook"].endswith("?"),
          "seed hook is a direct statement")
    check(8 <= len(seed["hook"].split()) <= 14,
          "seed hook obeys canonical 8-14 word range")
    check(len(seed["beats"]) == 6 and seed["beats"][0]["voiceover"].endswith("?"),
          "seed preserves six-beat treatment shape and early curiosity question")
    spoken = [seed["hook"]] + [b["voiceover"] for b in seed["beats"]] + [seed["payoff"]]
    total_words = sum(len(x.split()) for x in spoken)
    check(68 <= total_words <= 108, "seed spoken length is inside SHORT hard range")
    known = {c["claim_id"] for c in inventory["claims"]}
    cited = set(seed["hook_source_claim_ids"] + seed["payoff_source_claim_ids"])
    for beat in seed["beats"]:
        cited.update(beat["source_claim_ids"])
    check(cited and cited <= known, "every seed citation points to exact current claim inventory")
    check("Venusian" not in " ".join(spoken),
          "seed avoids unsupported demonym exposed by live flagship run")


def test_seed_fails_closed_on_topic_or_evidence_drift():
    fact = venus_fact()
    inventory = W.build_claim_inventory(fact, dossier_facts=[], grounded=False)
    other = dict(fact, id="not_venus")
    check(S.build_evidence_seed(other, inventory) is None,
          "seed cannot silently apply to another topic")

    changed = venus_fact()
    changed["wow"] = "Venus has an unusual rotation."
    changed_inventory = W.build_claim_inventory(changed, dossier_facts=[], grounded=False)
    check(S.build_evidence_seed(changed, changed_inventory) is None,
          "seed refuses if required retrograde/west/east evidence changes")


if __name__ == "__main__":
    test_seed_is_bound_to_exact_curated_claims_and_writer_shape()
    test_seed_fails_closed_on_topic_or_evidence_drift()
    print("quality_writer_evidence_seed tests: PASS")
