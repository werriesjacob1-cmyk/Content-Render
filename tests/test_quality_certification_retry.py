#!/usr/bin/env python3
"""Zero-network regressions for resilient private certification runner."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_certification_retry as R


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_retries_rejected_candidate_then_accepts_without_weakening_gate():
    original_build = R.C.build_bundle
    original_generate = R.C.O.generate_candidate_v21
    calls = {"n": 0}

    def fake_generate(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None, {
                "accepted": False,
                "treatment": "HIDDEN_MECHANISM",
                "validate_err": "hook below quality floor",
                "rounds": [{"semantic_verified": True}],
                "calls": [],
                "total_calls": 3,
            }
        return {"_semantic_verified": True}, {
            "accepted": True,
            "treatment": "HIDDEN_MECHANISM",
            "rounds": [{"semantic_verified": True}],
            "calls": [],
            "total_calls": 2,
        }

    def fake_build(topic, out_dir):
        manifest, debug = R.C.O.generate_candidate_v21({"id": "x"})
        if not manifest or not debug.get("accepted"):
            raise RuntimeError("Writer candidate rejected")
        return {"topic_id": "x", "accepted": True}

    R.C.O.generate_candidate_v21 = fake_generate
    R.C.build_bundle = fake_build
    try:
        with tempfile.TemporaryDirectory() as td:
            result = R.run_bundle("auto", td, max_attempts=3)
            evidence = json.loads((Path(td) / "writer_attempts.json").read_text())
    finally:
        R.C.build_bundle = original_build
        R.C.O.generate_candidate_v21 = original_generate

    check(calls["n"] == 2, "one rejected Writer candidate is followed by one fresh bounded attempt")
    check(result["accepted"] is True and result["certification_candidate_attempts"] == 2,
          "runner returns only after canonical Writer reports accepted")
    check(evidence["attempts"][0]["accepted"] is False and evidence["attempts"][1]["accepted"] is True,
          "attempt evidence preserves rejected and accepted outcomes separately")


def test_all_rejections_fail_closed_and_persist_debug():
    original_build = R.C.build_bundle
    original_generate = R.C.O.generate_candidate_v21
    calls = {"n": 0}

    def fake_generate(*args, **kwargs):
        calls["n"] += 1
        return None, {
            "accepted": False,
            "error": "no candidate obtained complete semantic verification",
            "rounds": [{"semantic_verified": False}],
            "calls": [],
            "total_calls": 2,
        }

    def fake_build(topic, out_dir):
        manifest, debug = R.C.O.generate_candidate_v21({"id": "x"})
        if not manifest or not debug.get("accepted"):
            raise RuntimeError(debug.get("error") or "rejected")
        return {"accepted": True}

    R.C.O.generate_candidate_v21 = fake_generate
    R.C.build_bundle = fake_build
    try:
        with tempfile.TemporaryDirectory() as td:
            try:
                R.run_bundle("auto", td, max_attempts=99)
                raised = False
            except RuntimeError:
                raised = True
            attempts = json.loads((Path(td) / "writer_attempts.json").read_text())
            failure = json.loads((Path(td) / "certification_failure.json").read_text())
    finally:
        R.C.build_bundle = original_build
        R.C.O.generate_candidate_v21 = original_generate

    check(raised, "three rejected candidates still fail certification closed")
    check(calls["n"] == R.MAX_HARD_ATTEMPTS,
          "operator value cannot exceed hard three-attempt ceiling")
    check(attempts["accepted"] is False and attempts["attempt_count"] == R.MAX_HARD_ATTEMPTS,
          "failure artifact retains every bounded Writer attempt")
    check(failure["stage"] == "writer_v21_bundle",
          "failure artifact identifies Writer stage instead of masquerading as render failure")


def test_live_guard_refuses_before_any_bundle_work():
    old = os.environ.pop("QUALITY_CERTIFICATION_LIVE", None)
    original = R.run_bundle
    called = {"n": 0}
    R.run_bundle = lambda *a, **k: called.__setitem__("n", called["n"] + 1)
    try:
        check(R.main(["--topic", "auto"]) == 2, "resilient runner refuses without two-part live acknowledgement")
        check(called["n"] == 0, "refusal happens before provider-capable bundle work")
    finally:
        R.run_bundle = original
        if old is not None:
            os.environ["QUALITY_CERTIFICATION_LIVE"] = old


if __name__ == "__main__":
    test_retries_rejected_candidate_then_accepts_without_weakening_gate()
    test_all_rejections_fail_closed_and_persist_debug()
    test_live_guard_refuses_before_any_bundle_work()
    print("quality_certification_retry tests: PASS")
