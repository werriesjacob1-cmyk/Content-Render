#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_learning_capture as C
import quality_learning_ledger as L


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label)


def test_capture_failed_private_writer_attempt_is_durable_and_idempotent():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "cert"; root.mkdir()
        ledger = Path(td) / "state" / "learning.jsonl"
        attempts = {
            "topic_id": "greenland_shark",
            "attempts": [{
                "accepted": False, "candidate_kind": "provider_writer",
                "treatment": "INSIDE_THE_SYSTEM", "error": "no accepted candidate",
                "calls": [{"provider": "gemini", "model": "gemini-test"}],
                "rounds": [{
                    "validate_err": "scenes 3 and 4 too similar (repetition)",
                    "mechanical_hard_count": 1, "semantic_violation_count": 1,
                    "semantic_verified": True,
                    "repair_plan": {"repair_type": "PROVENANCE"},
                }],
            }],
        }
        (root / "writer_attempts.json").write_text(json.dumps(attempts), encoding="utf-8")
        first = C.capture(str(root), str(ledger), "run-5")
        second = C.capture(str(root), str(ledger), "run-5")
        rows = L.read_records(ledger)
        check(first["written"] == 1 and second["written"] == 0, "capture is run-idempotent")
        check(len(rows) == 1 and rows[0].topic_id == "greenland_shark", "failed private topic survives")
        check(rows[0].treatment == "INSIDE_THE_SYSTEM", "failed treatment survives")
        check("repetition" in rows[0].failure_classes, "failure class survives for selector learning")


def test_capture_requires_resolved_topic_instead_of_guessing():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); (root / "writer_attempts.json").write_text(json.dumps({"attempts": []}), encoding="utf-8")
        try:
            C.capture(str(root), str(root / "learning.jsonl"), "run-x")
        except ValueError:
            pass
        else:
            raise AssertionError("missing resolved topic must fail closed")
    check(True, "capture never invents topic identity")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]:
        fn()
    print("quality_learning_capture tests: PASS")
