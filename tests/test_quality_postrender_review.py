#!/usr/bin/env python3
"""Zero-provider regressions for quality_postrender_review.py."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import final_video_qa as FQ
import quality_postrender_review as R


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _packet():
    return FQ.SamplePacket(
        video_path="fake.mp4",
        duration_s=40.0,
        timestamps_s=(2.4, 6.8, 11.2, 15.6, 20.0, 24.4, 28.8, 33.2, 37.6),
        frame_paths=tuple(f"f{i}.jpg" for i in range(9)),
        sheet_paths=("s1.jpg", "s2.jpg", "s3.jpg"),
    )


def _verdict():
    return FQ.FinalQAVerdict(
        overall_score=6.9,
        hook_visual=8.0,
        narration_visual_match=5.5,
        scientific_visual_integrity=8.0,
        visual_variety=7.0,
        pacing=7.0,
        caption_legibility=8.0,
        continuity=7.0,
        payoff_visual=5.0,
        ai_artifact_control=9.0,
        critical_failures=(),
        violations=(
            FQ.QAViolation("narration_visual_match", "major", 2, "middle visuals drift from the spoken mechanism"),
            FQ.QAViolation("payoff_visual", "major", 3, "final reveal is spoken but not shown"),
            FQ.QAViolation("visual_variety", "minor", 1, "opening repeats one subject"),
        ),
        summary="Strong science, weak middle match and payoff proof.",
        must_fix=("replace middle mismatch", "show payoff literally"),
        provider="gemini",
        model="gemini-test",
    )


def test_major_violations_become_bounded_minimal_repairs():
    plan = R.build_repair_targets(_verdict(), _packet())
    check(plan["mechanical_pass"] is False, "repair plan inherits failed mechanical gate")
    check(len(plan["targets"]) == 2, "only major/critical violations become repair targets")
    middle, payoff = plan["targets"]
    check(middle["evidence_group"] == 2 and 15.0 <= middle["start_s"] < middle["end_s"] <= 25.0,
          "middle-third defect maps to bounded middle repair window")
    check("re-resolve" in middle["recommended_action"], "visual mismatch receives visual-only re-resolution action")
    check(payoff["evidence_group"] == 3 and "payoff visual" in payoff["recommended_action"],
          "payoff defect receives literal payoff-proof action")
    check(all(t["automatic_repair_authorized"] is False for t in plan["targets"]),
          "repair planning never silently authorizes edits")


def test_repair_contract_preserves_good_work():
    plan = R.build_repair_targets(_verdict(), _packet())
    for target in plan["targets"]:
        preserve = " ".join(target["preserve"])
        check("accepted Writer V2.1 narration" in preserve and "sealed source claim IDs" in preserve,
              "targeted repair explicitly preserves Writer/evidence contract")
    check("smallest failing window" in plan["policy"], "repair policy prefers bounded fixes over full regeneration")


def test_context_uses_exact_spoken_manifest_and_scene_intents():
    manifest = {
        "title": "Test",
        "hook": "A precise hook.",
        "scenes": [
            {"id": 1, "_v2_role": "hook", "voiceover": "A precise hook.", "search_query": "real subject"},
            {"id": 2, "_v2_role": "beat", "voiceover": "The mechanism moves.", "search_query": "mechanism close up"},
            {"id": 3, "_v2_role": "payoff", "voiceover": "Now the payoff lands.", "search_query": "proof visual"},
        ],
        "payoff": "Now the payoff lands.",
        "_v2_spoken_scene_count": 3,
    }
    ctx = R.context_from_manifest(manifest)
    check(ctx.narration == "A precise hook. The mechanism moves. Now the payoff lands.",
          "holistic reviewer judges the canonical spoken scene sequence")
    check(len(ctx.scene_intents) == 3 and "mechanism close up" in ctx.scene_intents[1],
          "review context carries literal scene intents alongside narration")


if __name__ == "__main__":
    test_major_violations_become_bounded_minimal_repairs()
    test_repair_contract_preserves_good_work()
    test_context_uses_exact_spoken_manifest_and_scene_intents()
    print("quality_postrender_review tests: PASS")
