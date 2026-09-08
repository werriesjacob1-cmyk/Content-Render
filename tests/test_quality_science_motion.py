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
    test_missing_or_unsealed_evidence_never_generates_a_graphic()
    test_provenance_declares_zero_network_and_zero_ai()
    print("quality_science_motion tests: PASS")
