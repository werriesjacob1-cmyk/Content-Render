#!/usr/bin/env python3
"""Capture private-certification evidence into the durable learning ledger.

Designed to run with ``if: always()`` after Writer/render/QA steps. It is local,
provider-free, idempotent per GitHub run identity, and intentionally writes only
to the configured ledger path (typically a restored Actions cache file).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

import quality_learning_ledger as L


def _read_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(obj, Mapping):
        raise ValueError(f"{path}: expected object")
    return obj


def capture(cert_dir: str, ledger_path: str, run_identity: str) -> dict[str, Any]:
    root = Path(cert_dir)
    attempts = _read_json(root / "writer_attempts.json")
    if not attempts:
        return {"written": 0, "reason": "writer_attempts.json absent"}
    topic_id = str(attempts.get("topic_id") or "").strip()
    if not topic_id:
        failure = _read_json(root / "certification_failure.json") or {}
        topic_id = str(failure.get("topic_id") or "").strip()
    if not topic_id:
        raise ValueError("cannot persist learning without resolved topic_id")

    rows = L.records_from_writer_attempts(topic_id, attempts, run_identity=run_identity)
    written = 0
    for row in rows:
        if L.append_once(row, ledger_path):
            written += 1

    # Add stage-level render/QA evidence when present. These records use stable
    # IDs keyed to the same run so repeated capture is idempotent.
    manifest = _read_json(root / "manifest.json")
    treatment = ""
    if manifest:
        treatment = str(manifest.get("treatment") or manifest.get("_v2_treatment") or "").strip()
    if not treatment and rows:
        treatment = rows[-1].treatment

    render_dir = root / "render"
    audio = _read_json(render_dir / "audio_qa_report.json")
    holistic = _read_json(render_dir / "holistic_qa_report.json")
    if (render_dir / "final.mp4").is_file():
        rec = L.LearningRecord(
            attempt_id=L.stable_attempt_id(run_identity, topic_id, "render"),
            topic_id=topic_id,
            treatment=treatment,
            stage="render",
            status="rendered",
            metadata={"final_mp4_present": True},
        )
        written += int(L.append_once(rec, ledger_path))
    if audio:
        passed = bool(audio.get("pass") or audio.get("passed") or audio.get("mechanical_pass"))
        rec = L.LearningRecord(
            attempt_id=L.stable_attempt_id(run_identity, topic_id, "audio_qa"),
            topic_id=topic_id,
            treatment=treatment,
            stage="qa",
            status="certified" if passed else "failed",
            failure_classes=() if passed else ("audio_qa",),
            metadata={"qa_kind": "audio", "report": dict(audio)},
        )
        written += int(L.append_once(rec, ledger_path))
    if holistic:
        passed = bool(holistic.get("mechanical_pass"))
        failures = []
        for v in holistic.get("violations") or []:
            if isinstance(v, Mapping):
                cat = str(v.get("category") or "holistic_qa").strip()
                if cat:
                    failures.append(cat)
        rec = L.LearningRecord(
            attempt_id=L.stable_attempt_id(run_identity, topic_id, "holistic_qa"),
            topic_id=topic_id,
            treatment=treatment,
            stage="qa",
            status="certified" if passed else "failed",
            failure_classes=tuple(failures) if failures else (() if passed else ("holistic_qa",)),
            metadata={"qa_kind": "holistic", "provider": holistic.get("provider"), "model": holistic.get("model")},
        )
        written += int(L.append_once(rec, ledger_path))

    return {
        "written": written,
        "topic_id": topic_id,
        "treatment": treatment,
        "ledger_path": str(ledger_path),
        "record_count": len(L.read_records(ledger_path, strict=True)),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cert-dir", default="artifacts/quality_certification")
    ap.add_argument("--ledger", default=os.getenv("CONTENT_RENDER_LEARNING_LEDGER", "state/quality_learning.jsonl"))
    ap.add_argument("--run-identity", default=os.getenv("GITHUB_RUN_ID", "local"))
    args = ap.parse_args(argv)
    try:
        result = capture(args.cert_dir, args.ledger, args.run_identity)
    except Exception as exc:
        print(f"LEARNING CAPTURE FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
