#!/usr/bin/env python3
"""Zero-network tests for capability_preflight.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import capability_preflight as C


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def no_bins(name):
    return None


def all_bins(name):
    return "/usr/bin/" + name


def test_empty_runner_reports_real_blockers_without_calls():
    report = C.summary({}, no_bins)
    check(report["provider_calls_made"] == 0, "preflight never calls a provider")
    check("nasa_svs" in report["ready"] and "pubchem" in report["ready"] and "rcsb_molecular" in report["ready"],
          "keyless authentic science sources remain available")
    check("qwen_asset_vision" in report["blocked"] and "gemini_asset_vision" in report["blocked"],
          "missing vision credentials are visible before generation")
    check("sound_brain" in report["blocked"] and "final_video_qa" in report["blocked"],
          "missing audio/QA requirements fail preflight")


def test_partially_configured_voice_is_labeled_partial():
    caps = C.inspect({}, lambda n: "/usr/bin/edge-tts" if n == "edge-tts" else None)
    check(caps["voice_lab"].status == "partial", "Edge-only runner can compare baseline but not full Voice Lab")
    check("CARTESIA_API_KEY for Sonic 3.6" in caps["voice_lab"].missing, "missing voice challenger credential is explicit")


def test_fully_keyed_runner_becomes_ready_except_runtime_grounding_check():
    env = {
        "YOU_API_KEY": "x", "GROQ_API_KEY": "x", "GEMINI_API_KEY": "x",
        "ELEVENLABS_API_KEY": "x", "CARTESIA_API_KEY": "x", "PEXELS_API_KEY": "x",
        "FAL_KEY": "x",
    }
    old = C.importlib.util.find_spec
    C.importlib.util.find_spec = lambda name: object() if name == "fal_client" else old(name)
    try:
        report = C.summary(env, all_bins)
    finally:
        C.importlib.util.find_spec = old
    for name in ("you_grounded_research", "still_model_lab", "image_to_video_lab", "fal_video_lab",
                 "qwen_asset_vision", "gemini_asset_vision", "voice_lab", "sound_brain", "final_video_qa"):
        check(name in report["ready"], f"fully configured runner marks {name} ready")
    check("compound_mini_research" in report["runtime_check"],
          "Compound key presence alone does not falsely certify load-bearing grounding")


if __name__ == "__main__":
    test_empty_runner_reports_real_blockers_without_calls()
    test_partially_configured_voice_is_labeled_partial()
    test_fully_keyed_runner_becomes_ready_except_runtime_grounding_check()
    print("capability_preflight tests: PASS")
