#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_story_selector as S


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label)


def base_fact(**overrides):
    fact = {
        "id": "x",
        "fact": "A measurable scientific effect happens for a specific reason.",
        "angle": "The mechanism changes what you expect.",
        "wow": "The result reveals a concrete consequence today.",
        "queries": ["specific scientific subject", "mechanism visualization"],
        "key_terms": ["mechanism"],
    }
    fact.update(overrides)
    return fact


def test_scale_topic_prefers_scale_reveal_when_evidence_shape_exists():
    fact = base_fact(
        id="scale",
        fact="This structure is 100 million times larger than the familiar reference.",
        angle="Its size and distance create a scale humans rarely picture.",
        wow="That scale touches the real world today.",
        key_terms=["100 million times", "scale"],
    )
    winner, evidence = S.choose_treatment(fact)
    check(winner == "SCALE_REVEAL", "scale evidence selects SCALE_REVEAL")
    check(evidence["winner"]["signal_hits"] >= 1, "winner is supported by lexical evidence")


def test_myth_treatment_is_penalized_without_myth_evidence():
    fact = base_fact(id="plain")
    rows = {r.treatment: r for r in S.rank_treatments(fact)}
    check(rows["MYTH_AUTOPSY"].structural_penalty > 0, "myth treatment requires actual myth evidence")


def test_failed_pair_is_demoted_without_banning_topic():
    fact = base_fact(
        id="shark",
        fact="A shark body system uses interacting tissues and organs inside the eye.",
        angle="Inside the system, one interaction affects the next component.",
        key_terms=["system", "interaction", "inside"],
    )
    before, _ = S.choose_treatment(fact)
    failed = {("shark", before): 4}
    after, evidence = S.choose_treatment(fact, failed_pair_counts=failed)
    check(after != before, "repeatedly failed exact topic-treatment pair is demoted")
    check(any(r["failed_pair_penalty"] > 0 for r in evidence["ranked"]), "failure penalty is visible in selection evidence")


def test_recent_treatment_penalty_preserves_variety():
    fact = base_fact(
        id="case",
        fact="Scientists discovered a mystery after an observation contradicted the accepted explanation.",
        angle="A clue showed the old explanation was wrong.",
        wow="The evidence revealed what actually happened.",
    )
    rows = {r.treatment: r for r in S.rank_treatments(fact, recent_treatments=["CASE_FILE"])}
    check(rows["CASE_FILE"].recent_penalty > 0, "recent treatment gets explicit diversity penalty")


def test_selector_is_deterministic_and_zero_randomness():
    fact = base_fact(id="deterministic")
    a = S.choose_treatment(fact)
    b = S.choose_treatment(fact)
    check(a == b, "same evidence produces byte-semantically stable selection")


def test_champion_challenger_evidence_records_legacy_hash_choice():
    fact = base_fact(id="champion")
    _, evidence = S.choose_treatment(fact)
    check(bool(evidence["legacy_hash_treatment"]), "legacy champion is recorded")
    check(len(evidence["ranked"]) == 8, "all eight treatments are evaluated")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]:
        fn()
    print("quality_story_selector tests: PASS")
