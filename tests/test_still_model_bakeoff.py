#!/usr/bin/env python3
"""Zero-network tests for still_model_bakeoff.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import still_model_bakeoff as S  # noqa: E402


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_current_registry():
    names = S.parse_models(S.DEFAULT_MODELS)
    check(names == [
        "seedream5_pro", "gpt_image2", "nano_banana2", "qwen_image3", "ideogram4"
    ], "default registry contains five current still families")
    check(len({S.MODEL_SPECS[n]["model"] for n in names}) == 5,
          "all still aliases point at distinct endpoints")
    check(S.MODEL_SPECS["seedream5_pro"]["model"] ==
          "bytedance/seedream/v5/pro/text-to-image",
          "Seedream 5 Pro endpoint current")
    check(S.MODEL_SPECS["gpt_image2"]["model"] == "openai/gpt-image-2",
          "GPT Image 2 endpoint current")
    check(S.MODEL_SPECS["nano_banana2"]["model"] == "fal-ai/nano-banana-2",
          "Nano Banana 2 endpoint current")
    check(S.MODEL_SPECS["qwen_image3"]["model"] ==
          "alibaba/qwen-image-3/text-to-image",
          "Qwen Image 3 endpoint current")
    check(S.MODEL_SPECS["ideogram4"]["model"] == "ideogram/v4",
          "Ideogram 4 endpoint current")


def test_science_safe_request_shapes():
    prompt = "Accurate vertical scientific illustration of a mantis shrimp appendage."
    reqs = {n: S.MODEL_SPECS[n]["arguments"](prompt) for n in S.parse_models(S.DEFAULT_MODELS)}
    check(reqs["nano_banana2"]["aspect_ratio"] == "9:16",
          "Nano Banana requests native vertical")
    check(reqs["nano_banana2"]["resolution"] == "2K",
          "Nano Banana uses review-worthy resolution")
    check(reqs["nano_banana2"]["enable_web_search"] is False,
          "image model cannot silently add web-derived content")
    check(reqs["qwen_image3"]["image_size"] == {"width": 1152, "height": 2048},
          "Qwen uses true 9:16 2K-class canvas")
    check(reqs["qwen_image3"]["enable_prompt_expansion"] is False,
          "Qwen cannot silently rewrite science prompt")
    check(reqs["ideogram4"]["expansion_model"] == "None",
          "Ideogram prompt expansion disabled for fair science comparison")
    check(reqs["ideogram4"]["enable_safety_checker"] is True,
          "Ideogram safety checker remains enabled")
    check(reqs["seedream5_pro"]["enable_safety_checker"] is True,
          "Seedream safety checker remains enabled")
    check(reqs["gpt_image2"]["quality"] == "medium",
          "GPT Image 2 lab request avoids unnecessary high-quality spend")


def test_budget_guard():
    models = S.parse_models(S.DEFAULT_MODELS)
    estimate = S.estimate_cost(models)
    check(0.30 < estimate < 0.40,
          f"full five-model still lab is cents, not dollars ({estimate:.4f} USD)")
    check(abs(S.enforce_budget(models, 0.50) - estimate) < 1e-9,
          "$0.50 ceiling accepts current five-model plan")
    try:
        S.enforce_budget(models, 0.25)
        raise AssertionError("underfunded still plan should fail")
    except ValueError as e:
        check("exceeds hard budget" in str(e),
              "underfunded still run aborts before provider calls")

    try:
        S.enforce_budget(models, float("nan"))
        raise AssertionError("NaN budget should fail")
    except ValueError:
        check(True, "non-finite budget rejected")


def test_plan_never_marks_generated_asset_usable():
    models = S.parse_models("qwen_image3,nano_banana2")
    plan = S.build_plan(models, "accurate scientific subject, vertical", 1.0)
    check(plan["production_eligible"] is False,
          "generation plan is never production-eligible by itself")
    check("vision QA" in plan["reason"],
          "plan records independent vision requirement")
    stub = S.review_stub("qwen_image3")
    check(stub["vision_verified"] is False and stub["would_use_in_final"] is None,
          "review template begins unverified with no fabricated winner")


def test_prompt_and_alias_guards():
    try:
        S.parse_models("made_up_model")
        raise AssertionError("unknown model should fail")
    except ValueError:
        check(True, "unknown still model alias rejected")
    try:
        S.build_plan(["qwen_image3"], "", 1.0)
        raise AssertionError("empty prompt should fail")
    except ValueError:
        check(True, "empty science prompt rejected")
    try:
        S.build_plan(["qwen_image3"], "x" * 5001, 1.0)
        raise AssertionError("oversized prompt should fail")
    except ValueError:
        check(True, "prompt capped at strictest model limit")


def test_fal_result_parsing():
    check(S.extract_image_url({"images": [{"url": "https://x/a.png"}]}) ==
          "https://x/a.png", "common FAL image response parsed")
    check(S.extract_image_url({"data": {"images": [{"url": "https://x/b.jpg"}]}}) ==
          "https://x/b.jpg", "wrapped FAL image response parsed")
    check(S.extract_image_url({"images": []}) is None,
          "empty image response fails closed")


if __name__ == "__main__":
    test_current_registry()
    test_science_safe_request_shapes()
    test_budget_guard()
    test_plan_never_marks_generated_asset_usable()
    test_prompt_and_alias_guards()
    test_fal_result_parsing()
    print("still_model_bakeoff tests: PASS")
