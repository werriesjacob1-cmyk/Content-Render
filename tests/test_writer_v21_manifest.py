#!/usr/bin/env python3
"""Zero-network tests for Writer V2.1 hook/beat/payoff render assembly."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_v2 as W  # noqa: E402
import writer_v21_manifest as M  # noqa: E402
import writer_v21_orchestrator as O  # noqa: E402
import writer_v21_runtime as RT  # noqa: E402


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


def test_hook_and_payoff_are_real_scenes():
    writer_out, fact = fixture()
    m = M.assemble_manifest_v21(writer_out, fact, "HIDDEN_MECHANISM")
    check(len(m["scenes"]) == 8, "six treatment beats become hook + 6 beats + payoff = eight spoken scenes")
    check(m["scenes"][0]["voiceover"] == writer_out["hook"], "scene 1 is the actual spoken hook")
    check(m["scenes"][0]["_v2_role"] == "hook", "opening scene is role-labeled for downstream diagnostics")
    check(m["scenes"][-1]["voiceover"] == writer_out["payoff"], "final scene is the actual spoken payoff")
    check(m["scenes"][-1]["_v2_role"] == "payoff", "final scene is role-labeled for downstream diagnostics")
    check([s["id"] for s in m["scenes"]] == list(range(1, 9)), "scene IDs remain contiguous after insertion")


def test_spoken_script_matches_renderer_scene_contract():
    writer_out, fact = fixture()
    m = M.assemble_manifest_v21(writer_out, fact, "HIDDEN_MECHANISM")
    expected = " ".join(s["voiceover"] for s in m["scenes"])
    check(m["script"] == expected, "manifest script is exactly every spoken scene in order")
    check(m["script"].startswith(writer_out["hook"]), "renderable script starts with the hook")
    check(m["script"].endswith(writer_out["payoff"]), "renderable script ends with the payoff")
    check(writer_out["hook"] in m["script"] and writer_out["payoff"] in m["script"],
          "neither optimized endpoint can disappear from narration")


def test_claim_ids_move_with_exact_spoken_line():
    writer_out, fact = fixture()
    m = M.assemble_manifest_v21(writer_out, fact, "HIDDEN_MECHANISM")
    check(m["scenes"][0]["source_claim_ids"] == ["base_001"], "hook evidence lives on hook scene")
    check(m["scenes"][1]["source_claim_ids"] == ["base_002"], "first middle beat keeps its own evidence")
    check(m["scenes"][-1]["source_claim_ids"] == ["base_008"], "payoff evidence lives on payoff scene")
    check(m["hook_source_claim_ids"] == ["base_001"] and m["payoff_source_claim_ids"] == ["base_008"],
          "top-level evidence remains backward compatible")


def test_hook_and_payoff_get_distinct_visual_queries():
    writer_out, fact = fixture()
    m = M.assemble_manifest_v21(writer_out, fact, "HIDDEN_MECHANISM")
    check("mantis" in m["scenes"][0]["search_query"], "hook uses the first curated proof/hero visual opportunity")
    check("shockwave" in m["scenes"][-1]["search_query"], "payoff uses the last curated visual opportunity")
    check(m["scenes"][0]["search_query"] != m["scenes"][-1]["search_query"],
          "hook and payoff do not mechanically reuse one wallpaper shot when multiple opportunities exist")


def test_single_query_does_not_force_same_payoff_visual():
    writer_out, fact = fixture()
    fact["queries"] = ["mantis shrimp strike macro"]
    m = M.assemble_manifest_v21(writer_out, fact, "HIDDEN_MECHANISM")
    check(m["scenes"][0]["search_query"] != m["scenes"][-1]["search_query"],
          "one curated query is not duplicated by force into both opening and payoff")


def test_runtime_substitution_is_scoped_and_restored():
    original_orchestrator = O.generate_candidate_v21
    original_assemble = O.W.assemble_manifest_v2
    observed = {"inside": False}

    def fake_orchestrator(*args, **kwargs):
        observed["inside"] = O.W.assemble_manifest_v2 is M.assemble_manifest_v21
        return {"ok": True}, {"accepted": True}

    O.generate_candidate_v21 = fake_orchestrator
    try:
        m, debug = RT.generate_candidate_v21({"id": "x"})
    finally:
        O.generate_candidate_v21 = original_orchestrator

    check(observed["inside"] is True, "experimental runtime uses corrected assembly during candidate generation")
    check(O.W.assemble_manifest_v2 is original_assemble, "original Claude assembly function is restored after the call")
    check(m == {"ok": True} and debug["manifest_assembly"].endswith("assemble_manifest_v21"),
          "runtime records the active assembly path for diagnostics")


def main():
    test_hook_and_payoff_are_real_scenes()
    test_spoken_script_matches_renderer_scene_contract()
    test_claim_ids_move_with_exact_spoken_line()
    test_hook_and_payoff_get_distinct_visual_queries()
    test_single_query_does_not_force_same_payoff_visual()
    test_runtime_substitution_is_scoped_and_restored()
    print(f"writer_v21 manifest tests: PASS ({PASS} checks)")


if __name__ == "__main__":
    main()
