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


def _unrelated_ratio_manifest():
    """Two sealed, dimensionless, entirely NON-comparable ratios.

    Both lines pass every provenance check the ratio planner can make, yet
    charting "4 times faster" against "100 times denser" on one axis would
    assert a comparison the evidence never makes.
    """
    lines = [
        ("Neutron stars break almost every intuition you have about matter.", ["base_001"]),
        ("Their surface material spins about 4 times faster than a kitchen blender.", ["base_001"]),
        ("Their core is roughly 100 times denser than an atomic nucleus.", ["base_002"]),
        ("Those two facts describe completely different physical quantities.", ["base_002"]),
        ("Speed and density share no axis, no unit, and no meaningful ratio.", ["base_002"]),
        ("A single teaspoon would still outweigh a mountain range.", ["base_002"]),
        ("Nothing about the spin rate predicts the density.", ["base_001"]),
        ("Two true numbers are not automatically two comparable numbers.", ["base_001", "base_002"]),
    ]
    return {
        "title": "Neutron star extremes",
        "treatment": "SCALE_REVEAL",
        "scenes": [
            {"id": i, "voiceover": line, "source_claim_ids": refs,
             "_v2_role": "hook" if i == 1 else ("payoff" if i == 8 else "beat")}
            for i, (line, refs) in enumerate(lines, 1)
        ],
    }


def test_production_never_charts_unrelated_sealed_ratios():
    # The adversarial case: every ratio is real, dimensionless and sealed, and
    # the old routing would still have drawn one bar chart out of them.
    m = _unrelated_ratio_manifest()
    check(QSM.plan_manifest(m, ["base_001", "base_002"]) == {},
          "unrelated sealed ratios (4x faster vs 100x denser) produce no comparison graphic")


def test_scale_reveal_production_routing_is_failed_closed():
    # Even the well-behaved eclipse case is refused: sealed provenance proves
    # each ratio is real, never that two ratios are comparable.
    m = _eclipse_manifest()
    check(QSM.plan_manifest(m, ["base_001", "base_002"]) == {},
          "SCALE_REVEAL emits no deterministic comparison without proof of semantic comparability")
    check(QSM.SCALE_REVEAL_PRODUCTION_ROUTING_ENABLED is False,
          "the SCALE_REVEAL lane is explicitly marked disabled rather than silently dropped")
    check(not hasattr(QSM, "_plan_dimensionless_scale"),
          "the unproven planner is not reachable under its old production name")
    source = (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "quality_science_motion.py"))
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    body = text.split("def plan_manifest(", 1)[1]
    check("_inert_plan_dimensionless_scale" not in body,
          "production planner contains no call into the inert ratio machinery")


def test_inert_ratio_planner_is_preserved_for_a_future_comparability_contract():
    # Exercises the NON-PRODUCTION helper directly, so the machinery a future
    # explicit comparability contract will build on stays regression-covered.
    m = _eclipse_manifest()
    plans = QSM._inert_plan_dimensionless_scale(m, {"base_001", "base_002"})
    p = plans["3"]
    check(p.spec.kind == SM.MotionKind.SCALE_COMPARE,
          "inert planner still produces the deterministic scale-comparison spec")
    check([item.value for item in p.spec.scale_items] == [400.0, 400.0],
          "equal 400x width/distance ratios still render as equal scale values")
    check([item.display_value for item in p.spec.scale_items] == ["400 TIMES", "400 TIMES"],
          "display values are still copied from accepted narration rather than reformulated")
    check([item.label for item in p.spec.scale_items] == ["WIDER THAN THE MOON", "FARTHER AWAY"],
          "bar labels remain literal substrings of accepted narration")
    graph = SM.compile_filtergraph(p.spec)
    check("400 TIMES" in graph and "SCALE COMPARISON" in graph,
          "deterministic FFmpeg backend still compiles the retained comparison spec")

    m = _eclipse_manifest()
    m["scenes"][2]["voiceover"] = "The Sun is about 150 million kilometers away."
    check(QSM._inert_plan_dimensionless_scale(m, {"base_001", "base_002"}) == {},
          "one dimensionless ratio plus one unlike-unit measurement is still refused")

    m = _eclipse_manifest()
    m["scenes"][2]["source_claim_ids"] = ["unsealed_999"]
    try:
        QSM._inert_plan_dimensionless_scale(m, {"base_001", "base_002"})
    except ValueError as exc:
        check("unsealed claim" in str(exc), "unsealed ratio evidence still fails closed")
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
    test_production_never_charts_unrelated_sealed_ratios()
    test_scale_reveal_production_routing_is_failed_closed()
    test_inert_ratio_planner_is_preserved_for_a_future_comparability_contract()
    test_missing_or_unsealed_evidence_never_generates_a_graphic()
    test_provenance_declares_zero_network_and_zero_ai()
    print("quality_science_motion tests: PASS")
