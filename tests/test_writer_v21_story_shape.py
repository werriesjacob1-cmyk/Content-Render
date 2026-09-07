#!/usr/bin/env python3
"""Zero-network checks for Writer V2.1 story-shape + first-8-second telemetry."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_v21_story_shape as S


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_feature_detection():
    check("question" in S.line_features("How could that happen?"), "question function detected")
    check("wrong_hypothesis" in S.line_features("Scientists first assumed the metal simply sank."), "wrong hypothesis detected")
    check("reversal" in S.line_features("But what actually happened was different."), "reversal detected")
    check("mechanism" in S.line_features("Pressure causes the bubble to collapse."), "mechanism detected")
    check("scale" in S.line_features("It is 1000 times heavier."), "scale detected")
    check("consequence" in S.line_features("That means the barrier prevents damage."), "consequence detected")


def test_same_story_grammar_scores_high_even_with_rewording():
    a = {
        "treatment": "CASE_FILE",
        "hook": "A strange signal appeared where nobody expected it.",
        "beats": [
            "Researchers measured the signal again.",
            "They first assumed the detector was wrong.",
            "But another clue reversed that explanation.",
            "The real mechanism came from pressure inside the system.",
            "That means the event matters beyond the original mystery.",
        ],
        "payoff": "The clue changed how the whole system is understood.",
    }
    b = {
        "treatment": "MYTH_AUTOPSY",
        "hook": "An odd reading showed up in the data.",
        "beats": [
            "The team observed the same reading twice.",
            "At first they believed the instrument had failed.",
            "Instead a new clue broke that idea.",
            "Pressure was the mechanism causing the effect.",
            "So the discovery changed the interpretation of the system.",
        ],
        "payoff": "The evidence forced a new way to see the system.",
    }
    report = S.compare_scripts(a, b)
    check(report["similarity"] >= 0.70, "reworded same grammar remains structurally similar")
    check(report["same_treatment_label"] is False, "different labels do not hide shape similarity")


def test_genuinely_different_shapes_score_lower():
    case_file = {
        "hook": "A strange observation started the mystery.",
        "beats": [
            "Researchers measured a clue.",
            "They assumed the obvious explanation.",
            "But the evidence broke that explanation.",
            "The real mechanism caused the effect.",
        ],
        "payoff": "That clue changed what the observation meant.",
    }
    journey = {
        "hook": "One molecule starts inside the ocean.",
        "beats": [
            "It travels through a membrane.",
            "Then it crosses into a cell.",
            "It eventually ends up inside another structure.",
            "That journey allows the process to continue.",
        ],
        "payoff": "One tiny path connects the entire system.",
    }
    report = S.compare_scripts(case_file, journey)
    check(report["similarity"] < 0.70, "different functional progression scores lower")


def test_portfolio_flags_high_similarity_pairs():
    base = {"hook": "How could this happen?", "beats": ["Evidence was measured.", "But the clue changed everything.", "The mechanism causes the result."], "payoff": "That means the mystery is solved."}
    near = {"hook": "Why did this happen?", "beats": ["Researchers measured evidence.", "But another clue changed the answer.", "The mechanism causes the outcome."], "payoff": "That means the mystery has an answer."}
    different = {"hook": "One particle begins its trip.", "beats": ["It travels through water.", "It crosses a barrier.", "It eventually ends up inside a cell."], "payoff": "The journey connects the whole process."}
    report = S.portfolio_diversity([base, near, different])
    check(report["pair_count"] == 3, "portfolio compares every unique pair")
    check(any(x["a_index"] == 0 and x["b_index"] == 1 for x in report["high_similarity_pairs"]), "near-duplicate narrative shapes surfaced")
    check(report["gating"] is False, "shape diversity remains telemetry")


def test_first_eight_seconds_catches_slow_hook():
    report = S.first_eight_seconds_audit(
        "This extremely long opening sentence spends far too much time explaining the premise before it gives the viewer any reason to care about what happens next.",
        ["Then a mechanism appears.", "But the result reverses what you expect."],
        words_per_second=2.5,
    )
    check("hook_consumes_more_than_3_seconds" in report["warnings"], "long hook is visible in first-8-second audit")
    check("no_full_escalation_beat_by_8_seconds" in report["warnings"], "slow opening can consume the full retention window")


def test_first_eight_seconds_rewards_fast_function_change_without_fake_score():
    report = S.first_eight_seconds_audit(
        "Your stomach rebuilds the wall its own acid attacks.",
        [
            "Zoom closer and the protective cells are constantly being replaced.",
            "But stop that renewal and the acid reaches living tissue.",
        ],
        words_per_second=3.0,
    )
    check(report["fully_heard_beats_after_hook"] >= 1, "fast opening reaches escalation before 8 seconds")
    check(report["opening_distinct_function_count"] >= 2, "opening contains more than one narrative function")
    check("virality" not in report and "success_probability" not in report, "diagnostic never invents viral probability")


def test_invalid_timing_assumptions_fail():
    try:
        S.first_eight_seconds_audit("Hook", ["Beat"], words_per_second=0)
        raise AssertionError("zero WPS should fail")
    except ValueError:
        check(True, "invalid WPS rejected")


if __name__ == "__main__":
    test_feature_detection()
    test_same_story_grammar_scores_high_even_with_rewording()
    test_genuinely_different_shapes_score_lower()
    test_portfolio_flags_high_similarity_pairs()
    test_first_eight_seconds_catches_slow_hook()
    test_first_eight_seconds_rewards_fast_function_change_without_fake_score()
    test_invalid_timing_assumptions_fail()
    print("writer_v21_story_shape tests: PASS")
