#!/usr/bin/env python3
"""Zero-network adversarial tests for Writer V2.1 semantic fail-closed control."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_v21_semantic_gate as SG  # noqa: E402
import writer_v21_orchestrator as O  # noqa: E402


PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def supported(idx, verdict="SUPPORTED", prop=""):
    return {"beat_index": idx, "verdict": verdict, "unsupported_proposition": prop}


def complete_critic(num_beats=1, *, repair_type="NONE"):
    return {
        "scores": {
            "hook": 8,
            "central_idea": 8,
            "escalation": 8,
            "payoff": 8,
            "naturalness": 8,
            "cliche_ai_smell": 8,
            "distinctiveness": 8,
            "visual_tellability": 8,
            "claim_traceability": 8,
        },
        "claim_support": [supported(i) for i in range(num_beats + 2)],
        "repair_type": repair_type,
        "target_beats": [],
        "diagnosis": "clean",
        "must_preserve": [],
    }


def test_complete_coverage():
    ok, errors, covered = SG.validate_semantic_coverage(complete_critic(1), 1)
    check(ok is True, "complete hook+beat+payoff semantic coverage passes")
    check(errors == (), "complete coverage has no errors")
    check(covered == (0, 1, 2), "coverage records every spoken index")


def test_partial_coverage_fails():
    critic = complete_critic(1)
    critic["claim_support"] = [supported(0), supported(1)]
    ok, errors, covered = SG.validate_semantic_coverage(critic, 1)
    check(ok is False, "missing payoff semantic verdict fails closed")
    check(any("missing semantic verdict" in e and "2" in e for e in errors),
          "missing payoff index is diagnosed")
    check(covered == (0, 1), "partial coverage is visible diagnostically")


def test_duplicate_and_unknown_verdict_fail():
    critic = complete_critic(1)
    critic["claim_support"] = [supported(0), supported(1), supported(1), supported(2, "MAYBE")]
    ok, errors, _ = SG.validate_semantic_coverage(critic, 1)
    check(ok is False, "duplicate and unknown semantic verdict cannot pass")
    check(any("duplicate semantic verdict" in e for e in errors), "duplicate beat diagnosed")
    check(any("invalid semantic verdict" in e for e in errors), "unknown verdict diagnosed")


def test_live_dict_fallback_shape_can_still_be_verified():
    critic = complete_critic(1)
    critic["claim_support"] = {
        "0": {"verdict": "SUPPORTED", "unsupported_proposition": ""},
        "1": "SUPPORTED_PARAPHRASE",
        "2": {"verdict": "CONNECTIVE_OR_EDITORIAL", "unsupported_proposition": ""},
    }
    ok, errors, covered = SG.validate_semantic_coverage(critic, 1)
    check(ok is True, "live-observed dict fallback shape normalizes safely")
    check(errors == () and covered == (0, 1, 2), "fallback still requires complete coverage")


def test_missing_indices_are_never_invented_from_list_position():
    critic = complete_critic(1)
    critic["claim_support"] = [
        {"verdict": "SUPPORTED", "unsupported_proposition": ""},
        {"verdict": "SUPPORTED", "unsupported_proposition": ""},
        {"verdict": "SUPPORTED", "unsupported_proposition": ""},
    ]
    ok, errors, covered = SG.validate_semantic_coverage(critic, 1)
    check(ok is False, "list position can never manufacture missing semantic identities")
    check(sum("missing beat_index" in e for e in errors) == 3,
          "every identity-less row is explicitly diagnosed")
    check(covered == (), "identity-less supported rows cover nothing")


def test_one_missing_index_invalidates_otherwise_complete_list():
    critic = complete_critic(1)
    critic["claim_support"] = [supported(0), {"verdict": "SUPPORTED"}, supported(2)]
    ok, errors, covered = SG.validate_semantic_coverage(critic, 1)
    check(ok is False, "one missing identity invalidates the semantic payload")
    check(any("row 1 is missing beat_index" in e for e in errors), "missing row identity is diagnosed")
    check(covered == (0, 2), "valid neighboring identities do not repair the missing beat")


def test_boolean_float_and_string_list_indices_fail():
    for bad in (True, 1.0, "1"):
        critic = complete_critic(1)
        critic["claim_support"] = [supported(0), supported(bad), supported(2)]
        ok, errors, _ = SG.validate_semantic_coverage(critic, 1)
        check(ok is False, f"non-canonical list beat_index {bad!r} fails closed")
        check(any("not an integer" in e for e in errors), f"bad list beat_index {bad!r} is diagnosed")


def test_nonnumeric_fallback_key_and_mixed_garbage_fail():
    critic = complete_critic(1)
    critic["claim_support"] = {
        "0": "SUPPORTED",
        "beat-one": "SUPPORTED",
        "1": ["SUPPORTED"],
        "2": "SUPPORTED",
    }
    ok, errors, covered = SG.validate_semantic_coverage(critic, 1)
    check(ok is False, "fallback map with unknown key or malformed value fails as a whole")
    check(any("not an integer beat identity" in e for e in errors), "nonnumeric fallback key is diagnosed")
    check(any("value for beat_index 1 is malformed" in e for e in errors), "garbage fallback value is diagnosed")
    check(covered == (0, 2), "malformed rows are not silently converted into coverage")


def test_fallback_nested_identity_must_match_key():
    critic = complete_critic(1)
    critic["claim_support"] = {
        "0": "SUPPORTED",
        "1": {"beat_index": 2, "verdict": "SUPPORTED"},
        "2": "SUPPORTED",
    }
    ok, errors, covered = SG.validate_semantic_coverage(critic, 1)
    check(ok is False, "fallback key/nested identity disagreement fails closed")
    check(any("key/index disagreement" in e for e in errors), "identity disagreement is diagnosed")
    check(covered == (0, 2), "conflicting identity is not laundered into coverage")


def test_unsupported_requires_named_proposition():
    critic = complete_critic(1)
    critic["claim_support"][1] = supported(1, "UNSUPPORTED_ADDITION", "")
    ok, errors, _ = SG.validate_semantic_coverage(critic, 1)
    check(ok is False, "unsupported verdict with no proposition cannot be treated as actionable proof")
    check(any("missing unsupported_proposition" in e for e in errors),
          "missing unsupported proposition is explicit")


def test_bounded_retry_recovers_once():
    calls = {"n": 0}

    def call_once():
        calls["n"] += 1
        if calls["n"] == 1:
            return None, "provider 429"
        return complete_critic(1), None

    result = SG.critic_with_bounded_retry(num_beats=1, call_once=call_once, max_attempts=2)
    check(result.verified is True, "one bounded retry can recover semantic coverage")
    check(result.attempts == 2 and calls["n"] == 2, "retry count is exactly bounded")
    check(result.covered_indices == (0, 1, 2), "recovered critic covers full script")


def test_bounded_retry_exhaustion_fails_closed():
    calls = {"n": 0}

    def call_once():
        calls["n"] += 1
        return None, "quota exhausted"

    result = SG.critic_with_bounded_retry(num_beats=1, call_once=call_once, max_attempts=2)
    check(result.verified is False, "critic outage never becomes semantic-clean")
    check(result.attempts == 2 and calls["n"] == 2, "outage retry never exceeds the cap")
    check(bool(result.errors), "outage reason remains visible")


def _run_orchestrator(critic_payloads, *, clears_floor=True):
    """Run O.generate_candidate_v21 with every provider/LLM dependency mocked."""
    writer_out = {
        "title": "Three Hearts",
        "hook": "An octopus runs on three separate hearts.",
        "hook_source_claim_ids": ["base_001"],
        "beats": [{
            "voiceover": "Two of those hearts pump blood to the gills.",
            "visual_intent": "real octopus gills",
            "source_claim_ids": ["base_002"],
        }],
        "payoff": "Its circulation changes when it swims.",
        "payoff_source_claim_ids": ["base_002"],
    }
    inventory = {
        "claims": [
            {"claim_id": "base_001", "claim_text": "An octopus has three hearts."},
            {"claim_id": "base_002", "claim_text": "Two pump blood to the gills."},
        ],
        "provenance_note": "test",
    }
    manifest = {
        "hook": writer_out["hook"],
        "payoff": writer_out["payoff"],
        "scenes": [{"voiceover": writer_out["beats"][0]["voiceover"]}],
    }

    originals = {}
    patches = {
        (O.W, "select_treatment"): lambda *a, **k: "CASE_FILE",
        (O.G, "research_dossier"): lambda *a, **k: [],
        (O.W, "build_claim_inventory"): lambda *a, **k: inventory,
        (O.W, "build_writer_prompt_v2"): lambda *a, **k: "writer prompt",
        (O.G, "estimate_tokens"): lambda x: 10,
        (O.G, "_v2_parse_json_obj"): lambda raw: (json.loads(raw), None),
        (O.R, "check_traceability"): lambda *a, **k: [],
        (O.R, "hard_violations"): lambda x: [],
        (O.W, "assemble_manifest_v2"): lambda *a, **k: dict(manifest),
        (O.G, "validate"): lambda *a, **k: None,
        (O.G, "score_script"): lambda *a, **k: {
            "overall": 8.5,
            "hook": 8,
            "coherence": 8,
            "payoff": 8,
            "specificity": 8,
            "naturalness": 8,
        },
        (O.G, "_clears_quality_floor"): lambda score: bool(clears_floor),
        (O.R, "build_critic_prompt"): lambda *a, **k: "critic prompt",
        (O.R, "critic_average"): lambda v: 8.0 if v else None,
    }
    for (mod, name), value in patches.items():
        originals[(mod, name)] = getattr(mod, name)
        setattr(mod, name, value)

    queue = list(critic_payloads)
    invocations = []

    def fake_structured(prompt, schema, schema_name, calls):
        invocations.append(schema_name)
        calls.append({"provider": "fake", "model": "fake", "schema": schema_name})
        if schema_name == "writer_v2_output":
            return json.dumps(writer_out), True
        if schema_name == "critic_verdict":
            if not queue:
                return None, False
            item = queue.pop(0)
            if item is None:
                return None, False
            return json.dumps(item), True
        raise AssertionError(f"unexpected network call: {schema_name}")

    originals[(O.G, "_v2_structured_call")] = O.G._v2_structured_call
    O.G._v2_structured_call = fake_structured
    try:
        result = O.generate_candidate_v21(
            {"id": "octopus", "queries": ["octopus gills"]},
            recent_treatments=[],
        )
        return result, invocations
    finally:
        for (mod, name), value in originals.items():
            setattr(mod, name, value)


def test_orchestrator_critic_outage_cannot_accept():
    (manifest, debug), invocations = _run_orchestrator([None, None])
    check(manifest is None and debug["accepted"] is False,
          "mechanically clean high-score candidate cannot ship without semantic verification")
    check(debug["semantic_retries_used"] == 1, "only one global semantic retry is spent")
    check(invocations == ["writer_v2_output", "critic_verdict", "critic_verdict"],
          "outage path performs draft + critic + one retry, no fake provenance repair")
    check(debug.get("error") == "no candidate obtained complete semantic verification",
          "debug distinguishes verifier outage from script factual failure")


def test_orchestrator_identityless_supported_payload_cannot_accept():
    malformed = complete_critic(1)
    malformed["claim_support"] = [
        {"verdict": "SUPPORTED"},
        {"verdict": "SUPPORTED"},
        {"verdict": "SUPPORTED"},
    ]
    (manifest, debug), invocations = _run_orchestrator([malformed, malformed])
    check(manifest is None and debug["accepted"] is False,
          "perfect-score candidate cannot ship when critic omits semantic identities")
    check(debug.get("_semantic_verified") is not True,
          "malformed supported payload can never earn semantic verification")
    check(invocations.count("critic_verdict") == 2,
          "identityless payload consumes only the bounded semantic retry")


def test_orchestrator_partial_then_complete_retry_accepts():
    partial = complete_critic(1)
    partial["claim_support"] = [supported(0), supported(1)]
    full = complete_critic(1)
    (manifest, debug), invocations = _run_orchestrator([partial, full])
    check(manifest is not None and debug["accepted"] is True,
          "one malformed/partial critic response can recover to a genuinely verified candidate")
    check(manifest.get("_semantic_verified") is True, "accepted manifest carries semantic verification marker")
    check(invocations.count("critic_verdict") == 2, "recovery uses exactly one critic retry")


def test_orchestrator_quality_floor_still_load_bearing():
    (manifest, debug), invocations = _run_orchestrator([complete_critic(1)], clears_floor=False)
    check(manifest is None and debug["accepted"] is False,
          "semantic cleanliness cannot bypass the creative quality floor")
    check(invocations == ["writer_v2_output", "critic_verdict"],
          "clean semantic response does not waste retry budget on a quality-floor failure")


def main():
    test_complete_coverage()
    test_partial_coverage_fails()
    test_duplicate_and_unknown_verdict_fail()
    test_live_dict_fallback_shape_can_still_be_verified()
    test_missing_indices_are_never_invented_from_list_position()
    test_one_missing_index_invalidates_otherwise_complete_list()
    test_boolean_float_and_string_list_indices_fail()
    test_nonnumeric_fallback_key_and_mixed_garbage_fail()
    test_fallback_nested_identity_must_match_key()
    test_unsupported_requires_named_proposition()
    test_bounded_retry_recovers_once()
    test_bounded_retry_exhaustion_fails_closed()
    test_orchestrator_critic_outage_cannot_accept()
    test_orchestrator_identityless_supported_payload_cannot_accept()
    test_orchestrator_partial_then_complete_retry_accepts()
    test_orchestrator_quality_floor_still_load_bearing()
    print(f"writer_v21 semantic gate tests: PASS ({PASS} checks)")


if __name__ == "__main__":
    main()
