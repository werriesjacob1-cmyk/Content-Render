#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_learning_ledger as L


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label)


def test_append_only_and_dedup():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "ledger.jsonl"
        rec = L.LearningRecord(attempt_id="a1", topic_id="venus_day", treatment="CASE_FILE")
        check(L.append_once(rec, path) is True, "first append succeeds")
        size1 = path.stat().st_size
        check(L.append_once(rec, path) is False, "duplicate attempt id is idempotent")
        check(path.stat().st_size == size1, "duplicate does not mutate append-only file")
        rows = L.read_records(path)
        check(len(rows) == 1 and rows[0].topic_id == "venus_day", "record round-trips")


def test_malformed_row_fails_closed_by_default():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "ledger.jsonl"
        path.write_text('{"schema":"content-render-learning-v1","attempt_id":"x"}\nnot-json\n', encoding="utf-8")
        try:
            L.read_records(path)
        except ValueError:
            pass
        else:
            raise AssertionError("strict read must reject corruption")
        check(len(L.read_records(path, strict=False)) == 0, "non-strict salvage never invents partial records")


def test_failed_pairs_and_compact_lessons_are_bounded():
    rows = [
        L.LearningRecord(
            attempt_id=f"a{i}", topic_id="shark", treatment="INSIDE_THE_SYSTEM",
            status="failed", failure_classes=("repetition", "length"), repair_types=("PROVENANCE",)
        ) for i in range(12)
    ]
    check(L.failed_pair_counts(rows)[("shark", "INSIDE_THE_SYSTEM")] == 12, "failed pair counter is exact")
    lessons = L.compact_lessons(rows, topic_id="shark", treatment="INSIDE_THE_SYSTEM", max_items=5)
    check(lessons["records_considered"] == 5, "compact lesson context is bounded")
    check(lessons["failure_counts"]["repetition"] == 5, "bounded lessons preserve relevant recurrence")


def test_writer_attempt_ingest_persists_treatment_and_failure_taxonomy():
    payload = {
        "attempts": [{
            "accepted": False,
            "candidate_kind": "provider_writer",
            "treatment": "TIMELINE_TRANSFORMATION",
            "error": "no accepted candidate",
            "calls": [{"provider": "gemini", "model": "gemini-2.5-pro"}],
            "rounds": [{
                "validate_err": "script word count 118 out of range",
                "mechanical_hard_count": 1,
                "semantic_violation_count": 2,
                "semantic_verified": True,
                "repair_plan": {"repair_type": "PROVENANCE"},
            }],
        }]
    }
    rows = L.records_from_writer_attempts("shark", payload, run_identity="run-5")
    rec = rows[0]
    check(rec.treatment == "TIMELINE_TRANSFORMATION", "treatment is durable")
    check(rec.provider == "gemini", "provider/model evidence is durable")
    check("length" in rec.failure_classes and "semantic" in rec.failure_classes, "failure taxonomy preserves causal signals")
    check(rec.repair_types == ("PROVENANCE",), "repair outcome is durable")


def test_human_verdict_schema_is_strict():
    good = L.LearningRecord(attempt_id="h1", topic_id="x", stage="human", status="certified", human_verdict="definitely_post")
    check(not good.validate(), "known human verdict accepted")
    bad = L.LearningRecord(attempt_id="h2", topic_id="x", stage="human", status="rejected", human_verdict="awesome")
    check(bool(bad.validate()), "free-form verdict cannot contaminate structured labels")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]:
        fn()
    print("quality_learning_ledger tests: PASS")
