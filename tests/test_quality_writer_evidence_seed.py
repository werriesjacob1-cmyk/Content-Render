#!/usr/bin/env python3
"""Zero-network regressions for deterministic private-certification seeds."""
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


def eclipse_fact():
    return {
        "id": "eclipse_coincidence",
        "domain": "space",
        "fact": "The Sun is about 400 times wider than the Moon and also about 400 times farther away, which is the only reason they look the same size and we get perfect eclipses.",
        "angle": "a cosmic coincidence you never noticed",
        "key_terms": ["400 times", "same size", "total eclipse"],
        "whatif": "What if the Moon were slightly closer or farther? The perfect match, 400 times smaller but 400 times nearer, would break, and total eclipses would simply never happen.",
        "wow": "The Moon drifts about 3.8 centimetres farther away every year, so in a few hundred million years total eclipses will vanish from the sky forever.",
        "queries": ["solar eclipse", "moon sky", "sun corona eclipse"],
    }


def _assert_seed_shape(seed, inventory, label):
    check(seed is not None, f"{label} curated evidence produces deterministic seed")
    check(seed["hook"].endswith(".") and not seed["hook"].endswith("?"),
          f"{label} seed hook is a direct statement")
    check(8 <= len(seed["hook"].split()) <= 14,
          f"{label} seed hook obeys canonical 8-14 word range")
    check(len(seed["beats"]) == 6 and seed["beats"][0]["voiceover"].endswith("?"),
          f"{label} seed preserves six-beat shape and early curiosity question")
    spoken = [seed["hook"]] + [b["voiceover"] for b in seed["beats"]] + [seed["payoff"]]
    total_words = sum(len(x.split()) for x in spoken)
    check(68 <= total_words <= 108, f"{label} seed spoken length is inside SHORT hard range")
    known = {c["claim_id"] for c in inventory["claims"]}
    cited = set(seed["hook_source_claim_ids"] + seed["payoff_source_claim_ids"])
    for beat in seed["beats"]:
        cited.update(beat["source_claim_ids"])
    check(cited and cited <= known, f"every {label} seed citation points to exact current claim inventory")
    return spoken


def test_seed_is_bound_to_exact_curated_claims_and_writer_shape():
    fact = venus_fact()
    inventory = W.build_claim_inventory(fact, dossier_facts=[], grounded=False)
    seed = S.build_evidence_seed(fact, inventory)
    spoken = _assert_seed_shape(seed, inventory, "Venus")
    check("Venusian" not in " ".join(spoken),
          "Venus seed avoids unsupported demonym exposed by live flagship run")


def test_eclipse_seed_is_bound_to_exact_curated_claims_and_writer_shape():
    fact = eclipse_fact()
    inventory = W.build_claim_inventory(fact, dossier_facts=[], grounded=False)
    seed = S.build_evidence_seed(fact, inventory)
    spoken = _assert_seed_shape(seed, inventory, "eclipse")
    text = " ".join(spoken).lower()
    check("400" in text and "3.8" in text and "total eclipse" in text,
          "eclipse seed carries the central scale coincidence and temporary-eclipse payoff")
    check("few hundred million years" in text,
          "eclipse seed future-loss beat is tied to the curated wow evidence")


def test_seed_fails_closed_on_topic_or_evidence_drift():
    fact = venus_fact()
    inventory = W.build_claim_inventory(fact, dossier_facts=[], grounded=False)
    other = dict(fact, id="not_venus")
    check(S.build_evidence_seed(other, inventory) is None,
          "Venus seed cannot silently apply to another topic")

    changed = venus_fact()
    changed["wow"] = "Venus has an unusual rotation."
    changed_inventory = W.build_claim_inventory(changed, dossier_facts=[], grounded=False)
    check(S.build_evidence_seed(changed, changed_inventory) is None,
          "Venus seed refuses if required retrograde/west/east evidence changes")

    eclipse = eclipse_fact()
    eclipse_changed = dict(eclipse)
    eclipse_changed["wow"] = "The Moon slowly changes its orbit over time."
    eclipse_inventory = W.build_claim_inventory(eclipse_changed, dossier_facts=[], grounded=False)
    check(S.build_evidence_seed(eclipse_changed, eclipse_inventory) is None,
          "eclipse seed refuses if required 3.8cm/future-eclipse evidence changes")

    central_changed = eclipse_fact()
    central_changed["fact"] = "The Sun and Moon can appear similar in size during an eclipse."
    central_inventory = W.build_claim_inventory(central_changed, dossier_facts=[], grounded=False)
    check(S.build_evidence_seed(central_changed, central_inventory) is None,
          "eclipse seed refuses if the curated 400x geometry evidence changes")


if __name__ == "__main__":
    test_seed_is_bound_to_exact_curated_claims_and_writer_shape()
    test_eclipse_seed_is_bound_to_exact_curated_claims_and_writer_shape()
    test_seed_fails_closed_on_topic_or_evidence_drift()
    print("quality_writer_evidence_seed tests: PASS")
