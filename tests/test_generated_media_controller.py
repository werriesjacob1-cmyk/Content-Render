#!/usr/bin/env python3
"""Zero-network tests for generated_media_controller.py."""
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generated_media_controller as G
import quality_stack as Q
import visual_director as VD


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def spec():
    return VD.SceneSpec(
        scene_id="1",
        narration="The protein changes shape when the ligand binds.",
        scientific_subject="ligand-bound protein",
        must_show=("same protein before and after ligand binding",),
        mechanism="small conformational change after ligand binding",
        domain="molecular",
        authenticity_importance=8,
        forbidden_generic_substitutions=("generic glowing molecule",),
        generated_visual_allowed=True,
    )


def paid_policy():
    return Q.QualityPolicy(
        plan_only=False,
        allow_network=True,
        allow_paid=True,
        allow_generated_visuals=True,
    )


def test_lab_availability_does_not_equal_promotion():
    cfg = G.GeneratedMediaConfig()
    plan = G.build_strategy(spec(), cfg, paid_policy())
    check(not plan["eligible"], "empty promotion config cannot generate despite available model labs")
    check(any("no exact" in x for x in plan["blocked_reasons"]), "blocker requires explicit exact model promotion")

    cfg = G.GeneratedMediaConfig(
        still=G.PromotedModel("still", "gpt_image2", approved=False),
    )
    plan = G.build_strategy(spec(), cfg, paid_policy())
    check(not plan["eligible"], "known still alias remains blocked until explicitly promoted")
    check(any("not been explicitly promoted" in x for x in plan["blocked_reasons"]), "unapproved alias blocker is explicit")


def test_promoted_still_first_strategy_is_budgeted_and_unverified():
    cfg = G.GeneratedMediaConfig(
        still=G.PromotedModel("still", "gpt_image2", True, "blind bakeoff winner on scientific still prompt"),
        max_still_usd=Decimal("0.06"),
    )
    plan = G.build_strategy(spec(), cfg, paid_policy())
    check(plan["eligible"] and len(plan["steps"]) == 1, "promoted still can enter paid strategy")
    step = plan["steps"][0]
    check(step["lane"] == "still" and step["alias"] == "gpt_image2", "exact promoted alias is used")
    check(step["plan"]["estimated_cost_usd"] == 0.06, "still plan keeps hard cost guard")
    check(step["next_gate"].startswith("independent vision QA"), "still must pass independent vision before animation")
    check(plan["provider_calls_made"] == 0 and plan["production_eligible"] is False,
          "controller only plans; generated media never auto-promotes")


def test_verified_still_unlocks_separately_promoted_i2v():
    cfg = G.GeneratedMediaConfig(
        still=G.PromotedModel("still", "gpt_image2", True, "still bakeoff"),
        image_to_video=G.PromotedModel("image_to_video", "kling3_standard", True, "I2V bakeoff"),
        max_still_usd=Decimal("0.06"),
        max_i2v_usd=Decimal("0.504"),
    )
    before = G.build_strategy(spec(), cfg, paid_policy())
    check([x["lane"] for x in before["steps"]] == ["still"],
          "I2V does not appear before a verified hosted still is supplied")
    after = G.build_strategy(
        spec(), cfg, paid_policy(), verified_still_url="https://example.com/vision-passed.png", duration_s=6
    )
    check([x["lane"] for x in after["steps"]] == ["still", "image_to_video"],
          "verified still unlocks the separately promoted animation lane")
    i2v = after["steps"][1]
    check(i2v["plan"]["estimated_cost_usd"] == "0.5040", "I2V plan preserves exact Decimal cost")
    check("invalidates still-only approval" in i2v["next_gate"], "animation forces a second vision gate")


def test_policy_can_still_shut_everything_off():
    cfg = G.GeneratedMediaConfig(
        still=G.PromotedModel("still", "gpt_image2", True, "approved"),
    )
    blocked = G.build_strategy(spec(), cfg, Q.QualityPolicy())
    check(not blocked["eligible"], "safe default QualityPolicy blocks promoted paid model too")
    check(any("QualityPolicy" in x or "vision QA" in x for x in blocked["blocked_reasons"]),
          "policy/vision boundary explains why generation is blocked")


if __name__ == "__main__":
    test_lab_availability_does_not_equal_promotion()
    test_promoted_still_first_strategy_is_budgeted_and_unverified()
    test_verified_still_unlocks_separately_promoted_i2v()
    test_policy_can_still_shut_everything_off()
    print("generated_media_controller tests: PASS")
