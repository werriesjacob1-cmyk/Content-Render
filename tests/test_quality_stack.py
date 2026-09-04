#!/usr/bin/env python3
"""Zero-network integration regressions for quality_stack.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_stack as Q
import visual_director as VD
import vision_gateway as VG


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_registry_is_complete_and_safe():
    Q.assert_safe_defaults()
    status = Q.integration_status()
    required = {
        "you_grounded_research", "compound_mini_research", "visual_director",
        "nasa_svs", "pubchem", "rcsb_molecular", "existing_real_footage",
        "science_motion", "still_model_lab", "fal_video_lab", "qwen_asset_vision",
        "gemini_asset_vision", "voice_lab", "sound_brain", "video_repair",
        "final_video_qa", "writer_v2",
    }
    check(required <= set(status), "registry contains every current quality lane")
    missing = [m for m in Q.required_module_names() if not __import__(m)]
    check(not missing, "all non-writer integration modules import successfully")
    check(status["writer_v2"]["module_present"] in {True, False}, "writer V2 slot is optional until Claude lands it")
    check(not any("publish" in x or "publer" in x or "release" in x for x in status),
          "quality registry contains no publishing path")


def test_visual_priority_is_reality_first():
    molecular = Q.tools_for_visual_class(VD.VisualClass.MOLECULAR_RENDER)
    names = [x["tool"] for x in molecular]
    check(names[:3] == ["rcsb_molecular", "pubchem", "science_motion"],
          "molecular scenes try authentic structure/deterministic visuals before AI")

    generated = Q.tools_for_visual_class(VD.VisualClass.GENERATED_VIDEO)
    check(generated[0]["tool"] == "fal_video_lab", "generated-video route uses guarded model lab")
    check(any(x["tool"] == "qwen_asset_vision" for x in generated),
          "generated video requires independent Qwen vision lane")
    check(not generated[0]["permitted_now"], "generated video is disabled by zero-spend default policy")


def test_plan_only_end_to_end_contract():
    manifest = {
        "title": "Protein switch",
        "scenes": [
            {
                "id": 1,
                "voiceover": "This protein changes shape when a ligand binds.",
                "search_query": "protein ligand binding molecular structure",
                "motion_required": True,
            },
            {
                "id": 2,
                "voiceover": "That shape change exposes a new binding surface.",
                "search_query": "protein conformational change binding surface",
            },
        ],
    }
    plan = Q.build_quality_plan(manifest)
    check(plan["provider_calls_made"] == 0, "planning makes zero provider calls")
    check(plan["publishing_enabled"] is False, "integration plan cannot publish")
    check(plan["policy"]["plan_only"] is True, "plan-only is the default execution mode")
    check(len(plan["scenes"]) == 2, "visual director produced a scene contract for every beat")
    all_provider_rows = [p for s in plan["scenes"] for r in s["routes"] for p in r["provider_sequence"]]
    check(all(not row["permitted_now"] for row in all_provider_rows if row["requires_network"] or row["may_cost_money"]),
          "network/paid providers are blocked by default")


def test_vision_gateway_fails_closed_without_key():
    old = os.environ.pop("GROQ_API_KEY", None)
    try:
        check(VG.qwen_asset_verdict("real mantis shrimp", [b"fakejpeg"]) is None,
              "Qwen asset verifier does not run or approve without a key")
    finally:
        if old is not None:
            os.environ["GROQ_API_KEY"] = old
    bad = VG.VisionVerdict(9, True, False, False, False, False, "broken anatomy")
    check(not bad.production_eligible, "high score cannot override anatomy failure")
    good = VG.VisionVerdict(8, True, True, False, False, False, "clean literal match")
    check(good.production_eligible, "clean independently verified asset can become eligible")


if __name__ == "__main__":
    test_registry_is_complete_and_safe()
    test_visual_priority_is_reality_first()
    test_plan_only_end_to_end_contract()
    test_vision_gateway_fails_closed_without_key()
    print("quality_stack tests: PASS")
