#!/usr/bin/env python3
"""Zero-network tests for Writer V2.1 editorial/retention diagnostics."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_v21_editorial_diagnostics as E  # noqa: E402


PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def test_progressive_story_is_not_flagged_as_repetition():
    d = E.editorial_diagnostics(
        hook="A mantis shrimp punches hard enough to flash water into vapor.",
        beats=[
            "Its club accelerates so fast that pressure drops behind the strike.",
            "That pressure drop forms a cavitation bubble beside the shell.",
            "When the bubble collapses, it creates a second shock after the punch.",
        ],
        payoff="The shrimp effectively hits its target twice with a single swing.",
        scenes=[
            {"visual_intent": "mantis shrimp club macro strike"},
            {"visual_intent": "cavitation bubble forming underwater"},
            {"visual_intent": "bubble collapse shockwave shell"},
        ],
    )
    check("adjacent_repetition" not in d["warning_kinds"],
          "progressive mechanism beats do not look repetitive")
    check("payoff_restates_hook" not in d["warning_kinds"],
          "specific new payoff does not look like a hook restatement")
    check("generic_or_missing_visual_intent" not in d["warning_kinds"],
          "specific scientific visual subjects pass diagnostics")
    check(d["gating"] is False, "editorial diagnostics remain non-gating")


def test_rephrased_premise_is_flagged():
    d = E.editorial_diagnostics(
        hook="This star is unbelievably dense and incredibly heavy.",
        beats=[
            "The incredibly dense star is unbelievably heavy.",
            "This dense star remains incredibly heavy compared with normal stars.",
        ],
        payoff="The star is unbelievably dense and incredibly heavy.",
    )
    check("low_information_gain" in d["warning_kinds"],
          "rephrasing the premise instead of advancing is detected")
    check("adjacent_repetition" in d["warning_kinds"],
          "high adjacent lexical repetition is visible")
    check("payoff_restates_hook" in d["warning_kinds"],
          "payoff echoing hook is visible")


def test_generic_ai_moralizing_is_visible_not_banned():
    d = E.editorial_diagnostics(
        hook="A tiny predator can create a violent shockwave underwater.",
        beats=["Its strike forms a bubble that collapses almost instantly."],
        payoff="Even the smallest hunters remind us that danger often hides in plain sight.",
    )
    check("generic_ai_moralizing" in d["warning_kinds"],
          "known generic moralizing ending is flagged for editorial review")
    check(any("danger" in h["text"].lower() or "remind" in h["text"].lower()
              for h in d["generic_ai_moralizing_hits"]),
          "diagnostic preserves the exact weak phrase")
    check(d["gating"] is False, "moralizing warning cannot reject by itself")


def test_spoken_rhythm_warnings():
    long_line = "This sentence keeps adding extra written clauses because it sounds like a report instead of something a narrator would naturally say while a viewer is scrolling through a short video tonight."
    d = E.editorial_diagnostics(
        hook="One small fact changes how this works.",
        beats=[long_line, "Another short beat now adds something new."],
        payoff="That is the actual mechanism.",
    )
    check("spoken_sentence_too_long" in d["warning_kinds"],
          "very long written-sounding line is flagged")

    mono = E.editorial_diagnostics(
        hook="Octopus hearts move blood through gills.",
        beats=[
            "Two hearts move blood through gills.",
            "One heart moves blood through body.",
            "Swimming changes how that heart works.",
        ],
        payoff="Movement changes how circulation works inside.",
    )
    check("monotone_sentence_rhythm" in mono["warning_kinds"],
          "near-identical line lengths expose templated cadence")


def test_generic_visual_wallpaper_is_flagged():
    d = E.editorial_diagnostics(
        hook="A protein changes shape when a molecule binds.",
        beats=["The binding pocket closes around the molecule."],
        payoff="That shape change is what switches the protein on.",
        scenes=[
            {"visual_intent": "science animation"},
            {"visual_intent": "science animation"},
        ],
    )
    check("generic_or_missing_visual_intent" in d["warning_kinds"],
          "generic science wallpaper is detected")
    check("visual_subject_repetition" in d["warning_kinds"],
          "repeated visual subject across adjacent scenes is detected")


def test_human_review_questions_are_explicit():
    d = E.editorial_diagnostics(hook="A", beats=[], payoff="B")
    check(len(d["human_review_questions"]) >= 5,
          "diagnostic keeps human stomach-test questions explicit")
    check(any("first 1–2 seconds" in q for q in d["human_review_questions"]),
          "cold-viewer opening is explicitly reviewed")
    check(any("payoff" in q.lower() for q in d["human_review_questions"]),
          "payoff closure is explicitly reviewed")


def main():
    test_progressive_story_is_not_flagged_as_repetition()
    test_rephrased_premise_is_flagged()
    test_generic_ai_moralizing_is_visible_not_banned()
    test_spoken_rhythm_warnings()
    test_generic_visual_wallpaper_is_flagged()
    test_human_review_questions_are_explicit()
    print(f"writer_v21 editorial diagnostics tests: PASS ({PASS} checks)")


if __name__ == "__main__":
    main()
