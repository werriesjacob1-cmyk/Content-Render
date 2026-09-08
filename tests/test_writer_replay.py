#!/usr/bin/env python3
"""Zero-provider tests for writer_replay.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_replay as WR


def _payload():
    # Minimal shapes copied from real Sep-8 flagship rejection families.
    return {
        "attempts": [
            {
                "accepted": False,
                "treatment": "INSIDE_THE_SYSTEM",
                "rounds": [
                    {
                        "round": 0,
                        "validate_err": "script word count 140 out of range (target 78-98, hard 68-108, mode short)",
                        "mechanical_hard_count": 1,
                        "semantic_violation_count": 0,
                        "semantic_verified": True,
                        "repair_plan": {"repair_type": "PROVENANCE"},
                    },
                    {
                        "round": 1,
                        "validate_err": "scene 5 voiceover too long (30 words, cap is 25)",
                        "mechanical_hard_count": 0,
                        "semantic_violation_count": 0,
                        "semantic_verified": True,
                        "repair_plan": {"repair_type": "STRUCTURAL"},
                    },
                ],
            },
            {
                "accepted": False,
                "treatment": "TIMELINE_TRANSFORMATION",
                "rounds": [
                    {
                        "round": 0,
                        "validate_err": "hook 'What happens when a day outlasts a year?' is phrased as a QUESTION",
                        "mechanical_hard_count": 6,
                        "semantic_violation_count": 4,
                        "semantic_verified": True,
                        "repair_plan": {"repair_type": "PROVENANCE"},
                    },
                    {
                        "round": 1,
                        "validate_err": "scenes 7 and 8 too similar (repetition)",
                        "mechanical_hard_count": 3,
                        "semantic_violation_count": 2,
                        "semantic_verified": True,
                        "repair_plan": {"repair_type": "PROVENANCE"},
                    },
                ],
            },
        ]
    }


def test_classifier_real_failure_families():
    assert WR.classify_validate_error("script word count 118 out of range") == "total_length"
    assert WR.classify_validate_error("scene 6 voiceover too long (31 words, cap is 25)") == "scene_length"
    assert WR.classify_validate_error("hook 'x?' is phrased as a QUESTION") == "hook_question_conflict"
    assert WR.classify_validate_error("scenes 7 and 8 too similar (repetition)") == "repetition"
    assert WR.classify_validate_error("scene 5 voiceover uses the formal connector 'Thus'") == "formal_connector"
    assert WR.classify_validate_error("only 0/3 mandatory key terms named") == "missing_key_terms"
    assert WR.classify_validate_error(None) == "none"


def test_summary_exposes_length_and_tier1_clean_rates():
    summary = WR.summarize_payloads([("fixture", _payload())])
    assert summary["attempts"] == 2
    assert summary["rounds"] == 4
    assert summary["length_constraint_rounds"] == 2
    assert summary["length_constraint_share"] == 0.5
    assert summary["tier1_clean_rounds"] == 1
    assert summary["repair_types"] == {"PROVENANCE": 3, "STRUCTURAL": 1}
    assert summary["treatments"] == {"INSIDE_THE_SYSTEM": 2, "TIMELINE_TRANSFORMATION": 2}


def test_bad_artifact_shape_fails_closed(tmp_path=None):
    # load_payload() is intentionally strict; malformed/non-attempt artifacts
    # must not silently count as zero failures.
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rounds": []}, f)
        try:
            WR.load_payload(path)
        except ValueError:
            return
        raise AssertionError("malformed artifact did not fail closed")


def run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = []
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures.append((fn.__name__, exc))
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"RESULT: {len(tests) - len(failures)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
