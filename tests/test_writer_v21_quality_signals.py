#!/usr/bin/env python3
"""Zero-network tests for Writer V2.1 score/critic disagreement telemetry."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_v21_quality_signals as Q  # noqa: E402


PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def critic(**overrides):
    scores = {
        "hook_strength": 8,
        "clarity": 8,
        "escalation": 8,
        "payoff": 8,
        "spoken_naturalness": 8,
        "cliche_ai_smell": 8,
        "structural_distinctiveness": 8,
        "visual_tellability": 8,
        "claim_traceability": 9,
    }
    scores.update(overrides)
    return {"scores": scores}


def legacy(**overrides):
    score = {
        "hook": 8,
        "surprise": 8,
        "escalation": 8,
        "payoff": 8,
        "rewatch": 8,
        "clarity": 8,
        "coherence": 8,
        "overall": 8,
    }
    score.update(overrides)
    return score


def test_low_disagreement():
    report = Q.quality_signal_report(legacy(), critic())
    check(report["available"] is True, "matched rubrics produce an available comparison")
    check(report["disagreement_band"] == "LOW", "matching judges are labeled low disagreement")
    check(report["mean_abs_mapped_delta"] == 0.0, "exact match has zero mapped disagreement")
    check(report["gating"] is False, "telemetry cannot become an acceptance gate")


def test_severe_disagreement_exposes_exact_dimension():
    report = Q.quality_signal_report(
        legacy(hook=2, payoff=3, overall=5.3),
        critic(hook_strength=8, payoff=8),
    )
    check(report["disagreement_band"] == "SEVERE", "large self-score/critic divergence is surfaced")
    check(report["mapped_dimensions"]["hook"]["abs_delta"] == 6.0,
          "hook disagreement remains inspectable, not hidden in one average")
    check(report["mapped_dimensions"]["payoff"]["abs_delta"] == 5.0,
          "payoff disagreement remains inspectable")


def test_critic_craft_warning_is_human_quality_specific():
    report = Q.quality_signal_report(
        legacy(),
        critic(spoken_naturalness=4, cliche_ai_smell=3, visual_tellability=5),
    )
    check(report["critic_dimensions_below_6"] == [
        "cliche_ai_smell", "spoken_naturalness", "visual_tellability"
    ], "critic exposes low human-naturalness/AI-smell/visual-tellability dimensions")


def test_missing_signal_is_unavailable_not_zero():
    report = Q.quality_signal_report(None, None)
    check(report["available"] is False and report["disagreement_band"] == "UNAVAILABLE",
          "missing judges do not look like perfect agreement")
    check(report["legacy_overall"] is None and report["critic_craft_avg"] is None,
          "missing signals stay explicit")


def test_selection_conflict_is_telemetry_only():
    candidates = [
        {"round": 0, "hard_violations": [], "validate_err": None, "score": 8.4, "critic_avg": 6.5},
        {"round": 1, "hard_violations": [], "validate_err": None, "score": 8.0, "critic_avg": 8.7},
    ]
    report = Q.selection_signal_report(candidates)
    check(report["winner_disagreement"] is True, "legacy winner vs critic winner conflict is visible")
    check(report["legacy_winner_round"] == 0 and report["critic_winner_round"] == 1,
          "conflicting winner rounds are exact")
    check(report["gating"] is False, "winner conflict does not silently change selection")


def test_ineligible_candidate_never_enters_selection_telemetry():
    candidates = [
        {"round": 0, "hard_violations": ["semantic outage"], "validate_err": None, "score": 9.5, "critic_avg": 9.5},
        {"round": 1, "hard_violations": [], "validate_err": None, "score": 8.0, "critic_avg": 8.0},
    ]
    report = Q.selection_signal_report(candidates)
    check(report["eligible_candidate_count"] == 1, "factually/unverifiably dirty round is excluded from selection analysis")
    check(report["legacy_winner_round"] == 1, "only genuinely eligible round can be a diagnostic winner")


def test_debug_analysis_matches_live_round_shape():
    debug = {
        "rounds": [
            {
                "round": 0,
                "mechanical_hard_count": 0,
                "semantic_violation_count": 0,
                "semantic_verified": True,
                "validate_err": None,
                "score_clears_floor": True,
                "score": legacy(hook=8, payoff=8, overall=8.1),
                "critic_avg": 6.7,
                "critic_verdict": critic(hook_strength=5, payoff=5),
            },
            {
                "round": 1,
                "mechanical_hard_count": 0,
                "semantic_violation_count": 0,
                "semantic_verified": True,
                "validate_err": None,
                "score_clears_floor": True,
                "score": legacy(hook=7, payoff=7, overall=7.9),
                "critic_avg": 8.6,
                "critic_verdict": critic(hook_strength=8, payoff=9),
            },
        ]
    }
    report = Q.analyze_debug(debug)
    check(report["rounds"][0]["disagreement_band"] in {"MODERATE", "SEVERE"},
          "a stomach-lining-style score/critic conflict is surfaced per round")
    check(report["selection"]["winner_disagreement"] is True,
          "debug-level analysis shows when score winner and critic winner differ")
    check(report["gating"] is False, "debug analysis remains observational")


def main():
    test_low_disagreement()
    test_severe_disagreement_exposes_exact_dimension()
    test_critic_craft_warning_is_human_quality_specific()
    test_missing_signal_is_unavailable_not_zero()
    test_selection_conflict_is_telemetry_only()
    test_ineligible_candidate_never_enters_selection_telemetry()
    test_debug_analysis_matches_live_round_shape()
    print(f"writer_v21 quality signal tests: PASS ({PASS} checks)")


if __name__ == "__main__":
    main()
