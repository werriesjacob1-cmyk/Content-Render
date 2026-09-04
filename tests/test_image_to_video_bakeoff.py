#!/usr/bin/env python3
"""Zero-network tests for image_to_video_bakeoff.py."""
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import image_to_video_bakeoff as I


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_current_endpoints_and_request_shapes():
    names = I.parse_models("kling3_standard,grok_imagine,seedance25")
    check(names == ["kling3_standard", "grok_imagine", "seedance25"], "three current I2V lanes parse")
    check(I.MODEL_SPECS["kling3_standard"]["model"] == "fal-ai/kling-video/v3/standard/image-to-video", "Kling 3 Standard I2V endpoint pinned")
    check(I.MODEL_SPECS["grok_imagine"]["model"] == "xai/grok-imagine-video/image-to-video", "Grok Imagine I2V endpoint pinned")
    check(I.MODEL_SPECS["seedance25"]["model"] == "bytedance/seedance-2.5/image-to-video", "Seedance 2.5 I2V endpoint pinned")

    image = "https://example.com/verified.png"
    prompt = "Subtle physically plausible movement, preserve exact subject anatomy."
    k = I.MODEL_SPECS["kling3_standard"]["arguments"](image, prompt, 6)
    check(k["start_image_url"] == image and k["generate_audio"] is False, "Kling starts from verified still and disables native audio")
    check(k["duration"] == "6", "Kling duration uses current string enum")
    g = I.MODEL_SPECS["grok_imagine"]["arguments"](image, prompt, 6)
    check(g["image_url"] == image and g["resolution"] == "720p", "Grok uses verified image at bounded 720p")
    s = I.MODEL_SPECS["seedance25"]["arguments"](image, prompt, 6)
    check(s["image_url"] == image and s["aspect_ratio"] == "9:16", "Seedance requests native vertical animation")


def test_decimal_budget_is_conservative_without_false_cent_bug():
    cheap = ["kling3_standard", "grok_imagine"]
    estimate = I.estimate_cost(cheap, 6)
    check(estimate == Decimal("0.9260"), "6s Kling+Grok estimate is exactly $0.9260")
    check(I.enforce_budget(cheap, 6, "0.9260") == Decimal("0.9260"), "exact budget boundary passes")
    try:
        I.enforce_budget(cheap, 6, "0.9259")
        raise AssertionError("one ten-thousandth under should fail")
    except ValueError as exc:
        check("exceeds hard budget" in str(exc), "under-budget ceiling fails before provider calls")
    check(I.estimate_cost(["seedance25"], 6) == Decimal("2.8380"), "Seedance expensive challenger cost remains visible")


def test_plan_requires_verified_still_and_reverification():
    plan = I.build_plan(
        ["kling3_standard"],
        "https://example.com/verified.png",
        "Slow orbit; preserve molecular geometry; no text.",
        6,
        "0.51",
    )
    check(plan["input_still_must_be_vision_verified"] is True, "I2V contract requires verified input still")
    check(plan["output_video_vision_verified"] is False, "animated output starts unverified")
    check(plan["production_eligible"] is False, "I2V plan never self-promotes output")
    try:
        I.build_plan(["kling3_standard"], "/tmp/local.png", "move", 6, "1.00")
        raise AssertionError("local path should not pass FAL hosted-image contract")
    except ValueError as exc:
        check("hosted image URL" in str(exc), "I2V requires provider-accessible verified still URL")


if __name__ == "__main__":
    test_current_endpoints_and_request_shapes()
    test_decimal_budget_is_conservative_without_false_cent_bug()
    test_plan_requires_verified_still_and_reverification()
    print("image_to_video_bakeoff tests: PASS")
