#!/usr/bin/env python3
"""Zero-provider regressions for quality_postrender_review.py."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

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


def _timeline():
    return [
        {"scene_id": str(i + 1), "scene_index": i + 1,
         "role": "hook" if i == 0 else ("payoff" if i == 7 else "beat"),
         "start_s": i * 5.0, "end_s": (i + 1) * 5.0,
         "search_query": f"subject {i+1}", "source_claim_ids": [f"c{i+1}"]}
        for i in range(8)
    ]


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


def test_major_violations_become_bounded_scene_aware_repairs():
    plan = R.build_repair_targets(_verdict(), _packet(), _timeline())
    check(plan["mechanical_pass"] is False, "repair plan inherits failed mechanical gate")
    check(plan["scene_timeline_available"] is True, "repair planner consumes measured scene boundaries")
    check(len(plan["targets"]) == 2, "only major/critical violations become repair targets")
    middle, payoff = plan["targets"]
    check(middle["evidence_group"] == 2 and 15.0 <= middle["start_s"] < middle["end_s"] <= 25.0,
          "middle-third defect maps to bounded middle repair window")
    check(middle["affected_scene_ids"] == ["4", "5"],
          "middle defect maps to exact overlapping rendered scenes instead of whole video")
    check("re-resolve" in middle["recommended_action"], "visual mismatch receives visual-only re-resolution action")
    check(payoff["evidence_group"] == 3 and "8" in payoff["affected_scene_ids"],
          "late payoff defect includes exact rendered payoff scene")
    check("payoff visual" in payoff["recommended_action"], "payoff defect receives literal payoff-proof action")
    check(all(t["automatic_repair_authorized"] is False for t in plan["targets"]),
          "repair planning never silently authorizes edits")


def test_repair_contract_preserves_good_work():
    plan = R.build_repair_targets(_verdict(), _packet(), _timeline())
    for target in plan["targets"]:
        preserve = " ".join(target["preserve"])
        check("accepted Writer V2.1 narration" in preserve and "sealed source claim IDs" in preserve,
              "targeted repair explicitly preserves Writer/evidence contract")
    check("smallest failing scene/window" in plan["policy"], "repair policy prefers bounded fixes over full regeneration")


def test_scene_timeline_loader_fails_soft_but_preserves_valid_rows():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "timeline.json"
        p.write_text(json.dumps({"scenes": [
            {"scene_id": "1", "scene_index": 1, "start_s": 0, "end_s": 4.2, "role": "hook"},
            {"scene_id": "bad", "start_s": 8, "end_s": 7},
        ]}), encoding="utf-8")
        rows = R.load_scene_timeline(str(p))
    check(len(rows) == 1 and rows[0]["scene_id"] == "1", "timeline loader keeps valid measured scene and drops invalid row")
    check(R.load_scene_timeline("/definitely/missing.json") == [], "missing timeline fails soft to time-window-only repair planning")


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
    test_major_violations_become_bounded_scene_aware_repairs()
    test_repair_contract_preserves_good_work()
    test_scene_timeline_loader_fails_soft_but_preserves_valid_rows()
    test_context_uses_exact_spoken_manifest_and_scene_intents()
    print("quality_postrender_review tests: PASS")
