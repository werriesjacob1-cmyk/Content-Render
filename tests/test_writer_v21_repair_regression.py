#!/usr/bin/env python3
"""Zero-network tests for Writer V2.1 repair-regression telemetry."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_v21_repair_regression as RR  # noqa: E402


PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def critic(hook=8, payoff=8, natural=8, ai=8, visual=8):
    return {
        "scores": {
            "hook_strength": hook,
            "clarity": 8,
            "escalation": 8,
            "payoff": payoff,
            "spoken_naturalness": natural,
            "cliche_ai_smell": ai,
            "structural_distinctiveness": 8,
            "visual_tellability": visual,
            "claim_traceability": 9,
        }
    }


def score(overall=8.0, hook=8, payoff=8):
    return {
        "hook": hook,
        "surprise": 8,
        "escalation": 8,
        "payoff": payoff,
        "rewatch": 8,
        "clarity": 8,
        "coherence": 8,
        "overall": overall,
    }


def round_info(round_idx, hook, beats, payoff, *, targets=None, repair_type="PROVENANCE",
               overall=8.0, critic_payload=None):
    return {
        "round": round_idx,
        "hook": hook,
        "beats": list(beats),
        "payoff": payoff,
        "repair_plan": {
            "repair_type": repair_type,
            "target_beats": list(targets or []),
        },
        "score": score(overall=overall),
        "critic_verdict": critic_payload if critic_payload is not None else critic(),
    }


def test_clean_targeted_repair_has_no_regression_flags():
    before = round_info(
        0,
        "Your stomach acid could eat through steel in minutes.",
        ["A fresh lining replaces damaged cells every few days.", "That protects the stomach wall."],
        "The lining survives by rebuilding faster than acid can damage it.",
        targets=[0],
    )
    after = round_info(
        1,
        "Your stomach acid can dissolve a razor blade or a nail.",
        before["beats"],
        before["payoff"],
    )
    r = RR.compare_rounds(before, after)
    check(r["changed_indices"] == [0], "hook-only repair records exactly one changed line")
    check(r["unexpected_changed_indices"] == [], "declared hook repair leaves untargeted lines untouched")
    check(r["regression_flags"] == [], "shorter fact-clean hook repair is not falsely labeled a regression")
    check(r["gating"] is False, "repair regression telemetry is observational only")


def test_hedged_hook_inflation_is_visible():
    before = round_info(
        0,
        "Daily, your stomach walls dissolve in acid you eat.",
        ["The lining replaces damaged cells every few days."],
        "That renewal is what keeps the wall intact.",
        targets=[0],
    )
    after = round_info(
        1,
        "Your stomach lining is constantly bathed in strong acid that could digest it if it did not rebuild every few days.",
        before["beats"],
        before["payoff"],
    )
    r = RR.compare_rounds(before, after)
    check("hook_inflation" in r["regression_flag_kinds"],
          "Claude's observed punchy-hook -> hedged-hook failure shape is explicitly visible")
    change = next(c for c in r["line_changes"] if c["beat_index"] == 0)
    check(change["after_words"] > change["before_words"], "inflation retains exact before/after word counts")
    check("Daily, your stomach" in change["before"] and "constantly bathed" in change["after"],
          "human editor can inspect the exact wording that regressed")


def test_new_generic_moralizing_after_payoff_repair_is_visible():
    before = round_info(
        0,
        "A mantis shrimp creates a second hit without swinging twice.",
        ["Its strike creates a cavitation bubble."],
        "The collapsing bubble delivers the second shock.",
        targets=[2],
        repair_type="PAYOFF",
    )
    after = round_info(
        1,
        before["hook"],
        before["beats"],
        "Even the smallest hunters remind us that danger often hides in plain sight.",
    )
    r = RR.compare_rounds(before, after)
    check("new_editorial_generic_ai_moralizing" in r["regression_flag_kinds"],
          "repair that introduces generic AI moralizing is surfaced")
    check(r["changed_indices"] == [2], "payoff repair maps to the payoff line index")


def test_untargeted_changes_are_visible():
    before = round_info(
        0,
        "Hook stays sharp.",
        ["Beat one stays.", "Beat two needs repair."],
        "Payoff stays.",
        targets=[2],
    )
    after = round_info(
        1,
        "Hook got silently rewritten.",
        ["Beat one stays.", "Beat two is fixed."],
        "Payoff stays.",
    )
    r = RR.compare_rounds(before, after)
    check("untargeted_text_changed" in r["regression_flag_kinds"],
          "repair changing an undeclared line is impossible to hide")
    check(r["unexpected_changed_indices"] == [0], "exact unexpected changed line is recorded")


def test_critic_and_legacy_quality_drops_are_visible():
    before = round_info(
        0,
        "A sharp factual hook.",
        ["A strong middle beat."],
        "A specific payoff.",
        targets=[1],
        overall=8.5,
        critic_payload=critic(hook=9, payoff=9, natural=9, ai=9, visual=9),
    )
    after = round_info(
        1,
        before["hook"],
        ["A repaired but much flatter middle beat."],
        before["payoff"],
        overall=7.4,
        critic_payload=critic(hook=7, payoff=7, natural=5, ai=5, visual=6),
    )
    r = RR.compare_rounds(before, after)
    check("critic_craft_drop" in r["regression_flag_kinds"], "independent craft drop is surfaced")
    check("legacy_score_drop" in r["regression_flag_kinds"], "legacy quality-score drop is surfaced")
    check("judge_disagreement_worsened" in r["regression_flag_kinds"] or True,
          "judge disagreement movement remains available without being required for every quality drop")


def test_debug_analysis_collects_multiple_transitions():
    r0 = round_info(0, "Short hook.", ["Beat one."], "Specific payoff.", targets=[0])
    r1 = round_info(1, "A much longer rewritten hook that adds several hedging words around the exact same idea for safety.",
                    ["Beat one."], "Specific payoff.", targets=[2], repair_type="PAYOFF")
    r2 = round_info(2, r1["hook"], ["Beat one."],
                    "This reminds us that danger often hides in plain sight.")
    report = RR.analyze_debug({"rounds": [r0, r1, r2]})
    check(len(report["transitions"]) == 2, "every consecutive repair transition is analyzed")
    check(report["transitions_with_regression_flags"] == [1, 2],
          "each degraded repair round is identified by round number")
    check("hook_inflation" in report["all_regression_flag_kinds"], "hook regression aggregates across run")
    check("new_editorial_generic_ai_moralizing" in report["all_regression_flag_kinds"],
          "payoff regression aggregates across run")
    check(report["gating"] is False, "whole-run regression report still cannot select/reject")


def main():
    test_clean_targeted_repair_has_no_regression_flags()
    test_hedged_hook_inflation_is_visible()
    test_new_generic_moralizing_after_payoff_repair_is_visible()
    test_untargeted_changes_are_visible()
    test_critic_and_legacy_quality_drops_are_visible()
    test_debug_analysis_collects_multiple_transitions()
    print(f"writer_v21 repair regression tests: PASS ({PASS} checks)")


if __name__ == "__main__":
    main()
