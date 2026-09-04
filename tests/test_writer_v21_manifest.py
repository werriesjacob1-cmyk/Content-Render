#!/usr/bin/env python3
"""Zero-network tests for the canonical Writer V2.1 spoken contract."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import narration as N  # noqa: E402
import writer_v2 as W  # noqa: E402
import writer_v21_orchestrator as O  # noqa: E402


PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def fixture():
    writer_out = {
        "title": "The Double Hit",
        "hook": "This shrimp can hit the same target twice at once.",
        "hook_source_claim_ids": ["base_001"],
        "beats": [
            {
                "voiceover": f"Beat {i} reveals a different part of the mechanism.",
                "visual_intent": f"mantis shrimp mechanism stage {i}",
                "source_claim_ids": [f"base_{i + 1:03d}"],
            }
            for i in range(1, 7)
        ],
        "payoff": "The second hit comes from the water, not the shrimp.",
        "payoff_source_claim_ids": ["base_008"],
    }
    fact = {
        "domain": "animals",
        "key_terms": ["mantis shrimp"],
        "queries": [
            "mantis shrimp strike macro",
            "cavitation bubble collapse underwater",
            "shockwave shell underwater",
        ],
    }
    return writer_out, fact


def manifest():
    writer_out, fact = fixture()
    return writer_out, fact, W.assemble_manifest_v2(writer_out, fact, "HIDDEN_MECHANISM")


def test_hook_beats_payoff_are_canonical_scenes():
    writer_out, _, m = manifest()
    check(len(m["scenes"]) == 8, "six treatment beats become hook + 6 beats + payoff = eight spoken scenes")
    check(m["scenes"][0]["voiceover"] == writer_out["hook"], "scene 1 is the certified hook")
    check(m["scenes"][0]["_v2_role"] == "hook", "scene 1 is role-labeled hook")
    check([s["voiceover"] for s in m["scenes"][1:-1]] == [b["voiceover"] for b in writer_out["beats"]],
          "every treatment beat is present exactly once in certified spoken order")
    check(m["scenes"][-1]["voiceover"] == writer_out["payoff"], "final scene is the certified payoff")
    check(m["scenes"][-1]["_v2_role"] == "payoff", "final scene is role-labeled payoff")
    check([s["id"] for s in m["scenes"]] == list(range(1, 9)), "scene IDs remain contiguous")
    check(m["_v2_spoken_scene_count"] == 8, "manifest records the certified spoken scene count")


def test_spoken_text_is_one_renderer_contract():
    writer_out, _, m = manifest()
    expected_units = [writer_out["hook"]] + [b["voiceover"] for b in writer_out["beats"]] + [writer_out["payoff"]]
    expected = " ".join(expected_units)
    check(N.spoken_text(m) == expected, "spoken_text contains exact certified spoken units in order")
    check(m["script"] == expected, "manifest script contains the same certified spoken units in order")
    check(N.spoken_text(m).startswith(writer_out["hook"]), "renderer narration starts with certified hook")
    check(N.spoken_text(m).endswith(writer_out["payoff"]), "renderer narration ends with certified payoff")


def test_spoken_text_preserves_legacy_terminal_punctuation_behavior():
    legacy = {"scenes": [
        {"voiceover": "Already punctuated?"},
        {"voiceover": "Needs a stop"},
        {"voiceover": "Pause:"},
    ]}
    check(N.spoken_text(legacy) == "Already punctuated? Needs a stop. Pause:",
          "legacy scene-only manifests keep main.py's exact terminal-punctuation normalization")


def test_top_level_endpoints_cannot_drift_from_spoken_scenes():
    _, _, m = manifest()
    bad_hook = {**m, "hook": "A different top-level hook."}
    try:
        N.spoken_text(bad_hook)
    except N.NarrationContractError:
        check(True, "top-level hook drift fails closed")
    else:
        check(False, "top-level hook drift must fail closed")

    bad_payoff = {**m, "payoff": "A different top-level payoff."}
    try:
        N.spoken_text(bad_payoff)
    except N.NarrationContractError:
        check(True, "top-level payoff drift fails closed")
    else:
        check(False, "top-level payoff drift must fail closed")


def test_old_broken_manifest_mutation_is_detected():
    """Regression mutation: restore the old beats-only scenes bug and prove TTS refuses it."""
    _, _, m = manifest()
    broken = dict(m)
    broken["scenes"] = [dict(s) for s in m["scenes"][1:-1]]
    # Keep the certified count marker: this is exactly the dangerous condition
    # where certified hook/payoff still exist top-level but disappear from what
    # main.py would synthesize if it read scenes blindly.
    try:
        N.spoken_text(broken)
    except N.NarrationContractError:
        check(True, "mutation dropping hook/payoff from scenes is caught before narration")
    else:
        check(False, "old broken beats-only manifest must never reach narration")


def test_claim_ids_move_with_exact_spoken_line():
    _, _, m = manifest()
    check(m["scenes"][0]["source_claim_ids"] == ["base_001"], "hook evidence lives on hook scene")
    check(m["scenes"][1]["source_claim_ids"] == ["base_002"], "first middle beat keeps its own evidence")
    check(m["scenes"][-1]["source_claim_ids"] == ["base_008"], "payoff evidence lives on payoff scene")
    check(m["hook_source_claim_ids"] == ["base_001"] and m["payoff_source_claim_ids"] == ["base_008"],
          "top-level evidence remains backward compatible")


def test_hook_and_payoff_get_distinct_visual_queries():
    _, _, m = manifest()
    check("mantis" in m["scenes"][0]["search_query"], "hook uses first curated proof/hero visual opportunity")
    check("shockwave" in m["scenes"][-1]["search_query"], "payoff uses last curated visual opportunity")
    check(m["scenes"][0]["search_query"] != m["scenes"][-1]["search_query"],
          "hook and payoff do not mechanically reuse wallpaper when multiple opportunities exist")


def test_single_query_does_not_force_same_payoff_visual():
    writer_out, fact = fixture()
    fact["queries"] = ["mantis shrimp strike macro"]
    m = W.assemble_manifest_v2(writer_out, fact, "HIDDEN_MECHANISM")
    check(m["scenes"][0]["search_query"] != m["scenes"][-1]["search_query"],
          "one curated query is not duplicated by force into both opening and payoff")


def test_orchestrator_uses_canonical_assembler_directly():
    check(O.W is W, "orchestrator imports the canonical writer_v2 module")
    check(O.W.assemble_manifest_v2 is W.assemble_manifest_v2,
          "orchestrator calls canonical assemble_manifest_v2 directly with no runtime substitution")


def main():
    test_hook_beats_payoff_are_canonical_scenes()
    test_spoken_text_is_one_renderer_contract()
    test_spoken_text_preserves_legacy_terminal_punctuation_behavior()
    test_top_level_endpoints_cannot_drift_from_spoken_scenes()
    test_old_broken_manifest_mutation_is_detected()
    test_claim_ids_move_with_exact_spoken_line()
    test_hook_and_payoff_get_distinct_visual_queries()
    test_single_query_does_not_force_same_payoff_visual()
    test_orchestrator_uses_canonical_assembler_directly()
    print(f"writer_v21 manifest tests: PASS ({PASS} checks)")


if __name__ == "__main__":
    main()
