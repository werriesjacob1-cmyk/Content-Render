#!/usr/bin/env python3
"""Zero-network regressions for review_readiness.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asset_gateway as AG
import final_video_qa as FQ
import review_readiness as RR
import sound_brain as SB
import visual_director as VD


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def authentic_asset():
    return AG.nasa_svs_asset({
        "id": "svs:ready",
        "url": "https://svs.gsfc.nasa.gov/ready.mp4",
        "page_url": "https://svs.gsfc.nasa.gov/ready/",
        "desc": "NASA scientific visualization of the literal subject",
    }, ["literal subject"])


def qa(score=8.2):
    payload = {
        "overall_score": score,
        "scores": {
            "hook_visual": 8.0,
            "narration_visual_match": 8.0,
            "scientific_visual_integrity": 8.0,
            "visual_variety": 8.0,
            "pacing": 8.0,
            "caption_legibility": 8.0,
            "continuity": 8.0,
            "payoff_visual": 8.0,
            "ai_artifact_control": 8.0,
        },
        "critical_failures": [],
        "violations": [],
        "summary": "clean",
        "must_fix": [],
    }
    return FQ.parse_verdict(payload, "test", "test-model")


def ready_input(**overrides):
    data = dict(
        script_traceability_passed=True,
        scenes=(RR.SceneReviewRecord("1", authentic_asset(), ("claim_1",), True),),
        voice=RR.edge_baseline_selection(),
        final_qa=qa(),
    )
    data.update(overrides)
    return RR.ReadinessInput(**data)


def test_clean_video_only_advances_to_human_review():
    verdict = RR.evaluate(ready_input())
    check(verdict.eligible_for_human_review, "clean traceable video can advance to human review")
    check(verdict.human_review_required, "human review remains mandatory")
    check(not verdict.publish_allowed, "mechanical pass never authorizes publishing")


def test_experimental_voice_cannot_self_promote():
    v = RR.experimental_voice("eleven", "eleven_v3", "candidate-A", "won private bakeoff")
    verdict = RR.evaluate(ready_input(voice=v))
    check(not verdict.eligible_for_human_review, "Voice Lab challenger needs explicit production approval")
    check(any("experimental" in x for x in verdict.reasons), "voice blocker is explicit")


def test_generated_visual_requires_vision():
    gen = AG.generated_asset(
        "gen:1", VD.VisualClass.GENERATED_VIDEO, ["literal subject"],
        "https://generated.example/1", vision_verified=False,
    )
    verdict = RR.evaluate(ready_input(scenes=(RR.SceneReviewRecord("1", gen, ("claim_1",), True),)))
    check(not verdict.eligible_for_human_review, "unverified generated visual blocks review readiness")
    check(any("vision QA" in x for x in verdict.reasons), "generated-media blocker names vision QA")


def test_sound_budget_and_restraint_are_load_bearing():
    plan = SB.SoundPlan(30.0, (
        SB.SoundEvent("amb", SB.SoundKind.AMBIENCE, 0.0, 2.0, "quiet reef ambience"),
    ))
    ok = RR.evaluate(ready_input(sound_plan=plan, sound_max_credits=80))
    check(ok.eligible_for_human_review, "restrained sound plan at exact budget passes")
    over = RR.evaluate(ready_input(sound_plan=plan, sound_max_credits=79))
    check(not over.eligible_for_human_review, "sound plan over hard credit ceiling blocks readiness")


def test_repair_invalidates_previous_final_qa():
    verdict = RR.evaluate(ready_input(repaired_since_final_qa=True))
    check(not verdict.eligible_for_human_review, "post-QA repair forces final QA rerun")
    check(any("rerun" in x for x in verdict.reasons), "repair blocker explicitly requires rerun")


def test_final_qa_floor_is_reused_not_reinvented():
    verdict = RR.evaluate(ready_input(final_qa=qa(7.49)))
    check(not verdict.eligible_for_human_review, "existing 7.5 final-QA floor remains load-bearing")
    check(any("below 7.50" in x for x in verdict.reasons), "readiness gate surfaces final-QA floor reason")


def test_traceability_and_scene_provenance_are_required():
    no_trace = RR.evaluate(ready_input(script_traceability_passed=False))
    check(not no_trace.eligible_for_human_review, "failed script traceability blocks review readiness")
    missing_claim = RR.evaluate(ready_input(
        scenes=(RR.SceneReviewRecord("1", authentic_asset(), (), True),)
    ))
    check(not missing_claim.eligible_for_human_review, "high-factual-load visual needs source claim IDs")


if __name__ == "__main__":
    test_clean_video_only_advances_to_human_review()
    test_experimental_voice_cannot_self_promote()
    test_generated_visual_requires_vision()
    test_sound_budget_and_restraint_are_load_bearing()
    test_repair_invalidates_previous_final_qa()
    test_final_qa_floor_is_reused_not_reinvented()
    test_traceability_and_scene_provenance_are_required()
    print("review_readiness tests: PASS")
