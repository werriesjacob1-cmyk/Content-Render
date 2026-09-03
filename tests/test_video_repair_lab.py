#!/usr/bin/env python3
"""Zero-network tests for video_repair_lab.py."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import video_repair_lab as R


def check(cond, label):
    if not cond: raise AssertionError(label)
    print(f"PASS {label}")


def spec(duration=5.0):
    return R.RepairSpec(
        source_video_url="https://example.test/source.mp4",
        kind=R.RepairKind.BAKED_TEXT,
        instruction="Remove the garbled text in the upper-right corner.",
        preserve=("central mantis shrimp", "camera motion", "reef background"),
        must_not_change=("animal anatomy", "shell position"),
        start_time_s=1.0,
        duration_s=duration,
    )


def test_contracts():
    s=spec()
    check(not s.validate(), "valid repair spec passes")
    p=R.build_repair_prompt(s)
    check("MUST PRESERVE" in p and "MUST NOT CHANGE" in p, "repair prompt carries preservation contract")
    check("Do not add text" in p, "repair cannot decorate scene")
    ltx=R.MODEL_SPECS["ltx23_retake"]["arguments"](s)
    check(ltx["retake_mode"]=="replace_video", "LTX repair cannot overwrite audio")
    check(ltx["start_time"]==1.0 and ltx["duration"]==5.0, "LTX targets exact segment")
    luma=R.MODEL_SPECS["luma_ray32"]["arguments"](s)
    check(luma["edit_strength"]=="adhere_1", "Luma uses maximum preservation bias")
    check(luma["hdr"] is False and luma["exr_export"] is False, "repair avoids unnecessary expensive HDR paths")


def test_budget():
    models=R.parse_models(R.DEFAULT_MODELS)
    e=R.estimate_cost(models,spec())
    check(abs(e-1.22)<0.001, "5s two-model repair estimate is exact")
    check(R.enforce_budget(models,spec(),1.25)==e, "$1.25 hard ceiling admits expected run")
    try:
        R.enforce_budget(models,spec(),1.00); raise AssertionError("budget should fail")
    except ValueError as ex:
        check("exceeds hard budget" in str(ex), "under-budget plan fails before calls")
    check(abs(R.estimate_cost(models,spec(8.0))-2.24)<0.001, "8s plan uses LTX per-second + Luma 10s price")


def test_plan_never_promotes():
    plan=R.build_plan(["ltx23_retake"],spec(),1.0)
    check(plan["vision_verified"] is False and plan["production_eligible"] is False,
          "repair starts unverified and ineligible")
    stub=R.review_stub("ltx23_retake")
    check(stub["would_use_in_final"] is None and stub["vision_verified"] is False,
          "review template never fabricates success")


def test_invalid_inputs():
    bad=R.RepairSpec("file:///tmp/x.mp4",R.RepairKind.OTHER,"fix",("keep",),duration_s=5)
    check(any("HTTP" in x for x in bad.validate()), "non-remote source rejected")
    bad=R.RepairSpec("https://x/y.mp4",R.RepairKind.OTHER,"",("keep",),duration_s=5)
    check(any("instruction" in x for x in bad.validate()), "empty repair instruction rejected")
    bad=R.RepairSpec("https://x/y.mp4",R.RepairKind.OTHER,"fix",(),duration_s=5)
    check(any("preserve" in x for x in bad.validate()), "repair must declare what to preserve")


def test_result_parsing():
    check(R.extract_video_url({"video":{"url":"https://x/a.mp4"}})=="https://x/a.mp4",
          "direct repair result parsed")
    check(R.extract_video_url({"data":{"video":{"url":"https://x/b.mp4"}}})=="https://x/b.mp4",
          "wrapped repair result parsed")
    check(R.extract_video_url({}) is None, "missing video fails closed")


if __name__=="__main__":
    test_contracts(); test_budget(); test_plan_never_promotes(); test_invalid_inputs(); test_result_parsing()
    print("video_repair_lab tests: PASS")
