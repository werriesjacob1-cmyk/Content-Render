#!/usr/bin/env python3
"""Zero-network regressions for quality_science_motion.py."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_science_motion as QSM
import science_motion as SM


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _manifest(treatment="ONE_OBJECT_JOURNEY"):
    scenes = []
    lines = [
        "Your blood carries one oxygen molecule into a much larger journey.",
        "The molecule enters through the lungs and reaches the bloodstream.",
        "It begins its path attached to a red blood cell.",
        "The molecule changes location as the blood cell moves through circulation.",
        "It passes the narrow vessels before reaching living tissue.",
        "It finally reaches a cell that can use the oxygen.",
        "That small trip is part of how the whole body stays supplied.",
        "One molecule makes the hidden transport system easier to picture.",
    ]
    for i, line in enumerate(lines, 1):
        scenes.append({
            "id": i,
            "voiceover": line,
            "source_claim_ids": [f"claim_{i:03d}"],
            "_v2_role": "hook" if i == 1 else ("payoff" if i == 8 else "beat"),
        })
    return {"title": "Oxygen journey", "treatment": treatment, "scenes": scenes}


def _eclipse_manifest():
    # Mirrors the evidence-only fallback candidate's accepted-input shape.
    lines = [
        ("The Moon can cover the Sun almost perfectly during a total eclipse.", ["base_001"]),
        ("Start with scale: the Sun is about 400 times wider than the Moon.", ["base_001"]),
        ("Now jump to distance: the Sun is also about 400 times farther away.", ["base_001"]),
        ("Those two ratios make their disks look nearly the same size.", ["base_001"]),
        ("That apparent-size match is what makes total solar eclipses possible.", ["base_001"]),
        ("But the Moon drifts about 3.8 centimeters farther away every year.", ["base_002"]),
        ("In a few hundred million years, total eclipses will vanish from our sky.", ["base_002"]),
        ("The perfect total eclipse is a temporary feature of Earth.", ["base_001", "base_002"]),
    ]
    return {
        "title": "Why the Moon Fits the Sun So Perfectly",
        "treatment": "SCALE_REVEAL",
        "scenes": [
            {"id": i, "voiceover": line, "source_claim_ids": refs,
             "_v2_role": "hook" if i == 1 else ("payoff" if i == 8 else "beat")}
            for i, (line, refs) in enumerate(lines, 1)
        ],
    }


def test_journey_builds_one_late_nonspoiling_flow():
    m = _manifest()
    allowed = [f"claim_{i:03d}" for i in range(1, 9)]
    plans = QSM.plan_manifest(m, allowed)
    check(set(plans) == {"6"}, "journey graphic lands on destination beat, not before future steps")
    p = plans["6"]
    check(p.spec.kind == SM.MotionKind.PROCESS_FLOW, "journey uses deterministic process-flow renderer")
    check(p.source_scene_ids == ("3", "4", "5", "6"), "journey flow uses begin/transform/obstacle/destination beats")
    check(len(p.spec.flow_steps) == 4, "journey has four readable process steps")
    check(p.source_claim_ids == ("claim_003", "claim_004", "claim_005", "claim_006"),
          "motion provenance is exactly the displayed scenes' Writer claims")
    check(all(len(step.label) <= 38 for step in p.spec.flow_steps), "display labels stay compact")
    check(all(step.label.split()[0].lower() in m["scenes"][i]["voiceover"].lower()
              for step, i in zip(p.spec.flow_steps, (2, 3, 4, 5))),
          "labels are drawn from accepted V2.1 narration rather than invented copy")


def test_mechanism_and_system_are_explicitly_supported_but_arbitrary_treatments_are_not():
    allowed = [f"claim_{i:03d}" for i in range(1, 9)]
    mech = QSM.plan_manifest(_manifest("HIDDEN_MECHANISM"), allowed)
    system = QSM.plan_manifest(_manifest("INSIDE_THE_SYSTEM"), allowed)
    myth = QSM.plan_manifest(_manifest("MYTH_AUTOPSY"), allowed)
    check(set(mech) == {"6"} and len(mech["6"].spec.flow_steps) == 3,
          "hidden-mechanism graphics use only the frozen beneath/mechanism/consequence progression")
    check(set(system) == {"6"} and len(system["6"].spec.flow_steps) == 3,
          "inside-system graphics use only component/connection/interaction progression")
    check(myth == {}, "arbitrary narrative order is never misrepresented as a physical process")


def test_scale_reveal_uses_only_dimensionless_accepted_ratios():
    m = _eclipse_manifest()
    plans = QSM.plan_manifest(m, ["base_001", "base_002"])
    check(set(plans) == {"3"},
          "eclipse scale comparison lands on the second 400x reveal, after both ratios have been spoken")
    p = plans["3"]
    check(p.spec.kind == SM.MotionKind.SCALE_COMPARE,
          "SCALE_REVEAL uses the deterministic scale-comparison renderer")
    check(p.source_scene_ids == ("2", "3"),
          "comparison uses only the two accepted 400-times scale beats")
    check([item.value for item in p.spec.scale_items] == [400.0, 400.0],
          "equal 400x width/distance ratios render as equal scale values")
    check([item.display_value for item in p.spec.scale_items] == ["400 TIMES", "400 TIMES"],
          "display values are copied from accepted narration rather than reformulated")
    check([item.label for item in p.spec.scale_items] == ["WIDER THAN THE MOON", "FARTHER AWAY"],
          "bar labels stay concise while remaining literal substrings of accepted narration")
    check(p.source_claim_ids == ("base_001",),
          "scale comparison provenance is bound to the exact sealed central claim")
    graph = SM.compile_filtergraph(p.spec)
    check("400 TIMES" in graph and "SCALE COMPARISON" in graph,
          "existing deterministic FFmpeg backend can compile the eclipse comparison")


def test_scale_reveal_refuses_unsafe_or_underpowered_comparisons():
    m = _eclipse_manifest()
    m["scenes"][2]["voiceover"] = "The Sun is about 150 million kilometers away."
    check(QSM.plan_manifest(m, ["base_001", "base_002"]) == {},
          "one dimensionless ratio plus one unlike-unit measurement does not create a misleading bar chart")

    m = _eclipse_manifest()
    m["scenes"][2]["source_claim_ids"] = ["unsealed_999"]
    try:
        QSM.plan_manifest(m, ["base_001", "base_002"])
    except ValueError as exc:
        check("unsealed claim" in str(exc), "unsealed ratio evidence fails closed")
    else:
        raise AssertionError("unsealed scale-comparison claim should fail")


def test_missing_or_unsealed_evidence_never_generates_a_graphic():
    m = _manifest()
    allowed = [f"claim_{i:03d}" for i in range(1, 9)]
    m["scenes"][3]["source_claim_ids"] = []
    check(QSM.plan_manifest(m, allowed) == {}, "connective/uncited step disables deterministic factual graphic")

    m = _manifest()
    m["scenes"][4]["source_claim_ids"] = ["claim_not_sealed"]
    try:
        QSM.plan_manifest(m, allowed)
    except ValueError as exc:
        check("unsealed claim" in str(exc), "unknown claim ID fails closed")
    else:
        raise AssertionError("unsealed science-motion claim should fail")


def test_provenance_declares_zero_network_and_zero_ai():
    p = QSM.plan_manifest(_manifest(), [f"claim_{i:03d}" for i in range(1, 9)])["6"]
    provenance = p.provenance()
    check(provenance["deterministic"] is True, "science motion is explicitly deterministic")
    check(provenance["network_calls"] == 0 and provenance["ai_generation"] is False,
          "science motion provenance proves zero network and zero AI generation")
    check(provenance["labels_are_substrings_of_accepted_v21_narration"] is True,
          "provenance records the no-new-copy label contract")


if __name__ == "__main__":
    test_journey_builds_one_late_nonspoiling_flow()
    test_mechanism_and_system_are_explicitly_supported_but_arbitrary_treatments_are_not()
    test_scale_reveal_uses_only_dimensionless_accepted_ratios()
    test_scale_reveal_refuses_unsafe_or_underpowered_comparisons()
    test_missing_or_unsealed_evidence_never_generates_a_graphic()
    test_provenance_declares_zero_network_and_zero_ai()
    print("quality_science_motion tests: PASS")
