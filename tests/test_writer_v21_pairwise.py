#!/usr/bin/env python3
"""Zero-network checks for blind Writer V2.1 pairwise editorial judging."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_v21_pairwise as P


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def candidate(cid, hook, payoff, *, clean=True):
    return P.PairwiseCandidate(
        candidate_id=cid,
        hook=hook,
        beats=(
            "The first beat adds a specific mechanism.",
            "The second beat changes what the viewer expects.",
            "The third beat raises the consequence.",
        ),
        payoff=payoff,
        treatment="CASE_FILE",
        factual_clean=clean,
        validate_clean=clean,
        semantic_verified=clean,
    )


def test_blind_packet_is_deterministic_and_anonymous():
    old = candidate("round_0_original", "Your stomach replaces its lining constantly.", "That renewal is what keeps the acid contained.")
    new = candidate("round_1_repair", "Your stomach rebuilds the barrier its own acid attacks.", "The repair cycle is why your stomach does not digest itself.")
    packet1 = P.build_pairwise_packet(old, new, seed="same-seed")
    packet2 = P.build_pairwise_packet(old, new, seed="same-seed")
    check(packet1["aliases"] == packet2["aliases"], "same experiment seed gives stable blind order")
    prompt = P.build_pairwise_prompt(packet1).lower()
    check("round_0_original" not in prompt and "round_1_repair" not in prompt,
          "candidate ids never leak into judge prompt")
    check("candidate a" in prompt and "candidate b" in prompt,
          "judge sees only anonymous A/B scripts")
    # The instruction intentionally CONTAINS the phrase "which version is newer"
    # as a prohibition, so asserting that phrase is absent creates a false
    # negative. Test the real anonymity property instead: no chronology labels,
    # repair language, or round metadata are attached to either candidate.
    chronology_labels = (
        "candidate a is newer", "candidate b is newer",
        "candidate a is older", "candidate b is older",
        "original version", "repaired version", "new version", "old version",
        "previous round", "later round", "repair round",
    )
    check(not any(label in prompt for label in chronology_labels),
          "prompt never labels A/B as old/new/original/repaired or exposes round chronology")
    check("do not infer which version is newer" in prompt,
          "judge explicitly forbidden from chronology inference")
    check(packet1["gating"] is False, "pairwise packet is telemetry only")


def test_pairwise_requires_factual_and_semantic_cleanliness():
    good = candidate("good", "A clean hook.", "A clean payoff.")
    bad = candidate("bad", "A bad hook.", "A bad payoff.", clean=False)
    try:
        P.build_pairwise_packet(good, bad)
        raise AssertionError("unsafe candidate should not be pairwise judged")
    except ValueError as e:
        check("factual" in str(e), "pairwise judge cannot bypass factual/semantic gates")


def test_structured_verdict_validation_and_mapping():
    a = candidate("candidate_alpha", "A sharper hook.", "A specific payoff.")
    b = candidate("candidate_beta", "A slower hook.", "A generic payoff.")
    packet = P.build_pairwise_packet(a, b, seed="mapping")
    verdict = P.parse_pairwise_verdict({
        "winner": "A",
        "confidence": "HIGH",
        "criterion_winners": {name: "A" for name in P.PAIRWISE_CRITERIA},
        "decisive_reasons": ["A opens faster and lands a more specific payoff."],
        "losing_defects": ["B spends too long setting up."],
        "would_post_winner": True,
    })
    mapped = P.map_verdict_to_candidates(packet, verdict)
    check(mapped["winner_candidate_id"] == packet["aliases"]["A"],
          "blind alias maps back only after verdict")
    check(mapped["gating"] is False, "mapped pairwise result remains non-gating")


def test_invalid_verdicts_fail_closed():
    base = {
        "winner": "A",
        "confidence": "MEDIUM",
        "criterion_winners": {name: "A" for name in P.PAIRWISE_CRITERIA},
        "decisive_reasons": ["A is stronger."],
        "losing_defects": [],
        "would_post_winner": False,
    }
    bad = dict(base); bad["winner"] = "C"
    try:
        P.parse_pairwise_verdict(bad)
        raise AssertionError("invalid winner should fail")
    except P.PairwiseVerdictError:
        check(True, "invalid winner rejected")
    bad = dict(base); bad["criterion_winners"] = {"hook": "A"}
    try:
        P.parse_pairwise_verdict(bad)
        raise AssertionError("incomplete criteria should fail")
    except P.PairwiseVerdictError:
        check(True, "incomplete criterion coverage rejected")


def test_debug_plans_only_include_clean_consecutive_rounds():
    rounds = [
        {
            "round": 0,
            "hook": "A direct hook.",
            "beats": ["One new fact.", "A mechanism.", "A consequence."],
            "payoff": "A specific payoff.",
            "mechanical_hard_count": 0,
            "semantic_violation_count": 0,
            "semantic_verified": True,
            "validate_err": None,
        },
        {
            "round": 1,
            "hook": "A stronger direct hook.",
            "beats": ["One new fact.", "A clearer mechanism.", "A consequence."],
            "payoff": "A more specific payoff.",
            "mechanical_hard_count": 0,
            "semantic_violation_count": 0,
            "semantic_verified": True,
            "validate_err": None,
        },
        {
            "round": 2,
            "hook": "A hallucinated hook.",
            "beats": ["One new fact."],
            "payoff": "Bad.",
            "mechanical_hard_count": 1,
            "semantic_violation_count": 0,
            "semantic_verified": True,
            "validate_err": None,
        },
    ]
    plans = P.pairwise_plans_from_debug({"rounds": rounds})
    check(len(plans) == 1, "only clean-to-clean transition receives pairwise plan")
    check(plans[0]["from_round"] == 0 and plans[0]["to_round"] == 1,
          "pairwise plan preserves transition identity outside blind prompt")
    check("round" not in plans[0]["prompt"].lower(),
          "blind judge prompt never exposes repair-round metadata")


if __name__ == "__main__":
    test_blind_packet_is_deterministic_and_anonymous()
    test_pairwise_requires_factual_and_semantic_cleanliness()
    test_structured_verdict_validation_and_mapping()
    test_invalid_verdicts_fail_closed()
    test_debug_plans_only_include_clean_consecutive_rounds()
    print("writer_v21_pairwise tests: PASS")
