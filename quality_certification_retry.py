#!/usr/bin/env python3
"""Resilient private flagship certification runner.

Wraps ``quality_certification_generate`` without changing unattended production.
The exact Writer V2.1 acceptance gates remain load-bearing; this runner merely
allows a small number of independent drafts when a valid-but-weak candidate or
provider-contended repair round fails to clear them.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import quality_certification_generate as C
import quality_writer_provider_resilience as P


MAX_HARD_ATTEMPTS = 3


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)


def _attempt_summary(index: int, manifest, debug: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempt": index,
        "accepted": bool(manifest and debug.get("accepted")),
        "error": debug.get("error"),
        "validate_err": debug.get("validate_err"),
        "treatment": debug.get("treatment"),
        "total_calls": debug.get("total_calls"),
        "semantic_retries_used": debug.get("semantic_retries_used"),
        "repair_rounds": debug.get("repair_rounds"),
        "rounds": debug.get("rounds") or [],
        "calls": debug.get("calls") or [],
    }


def run_bundle(topic: str, out_dir: str, max_attempts: int = 3) -> dict[str, Any]:
    attempts_limit = max(1, min(int(max_attempts), MAX_HARD_ATTEMPTS))
    original_generate = C.O.generate_candidate_v21
    attempt_evidence: list[dict[str, Any]] = []

    def retrying_generate(*args, **kwargs):
        last_manifest = None
        last_debug: dict[str, Any] = {"accepted": False, "error": "no Writer attempt executed"}
        for idx in range(1, attempts_limit + 1):
            print(f"[cert-writer] candidate attempt {idx}/{attempts_limit}")
            manifest, debug = original_generate(*args, **kwargs)
            debug = dict(debug or {})
            attempt_evidence.append(_attempt_summary(idx, manifest, debug))
            last_manifest, last_debug = manifest, debug
            if manifest and debug.get("accepted"):
                debug["certification_candidate_attempt"] = idx
                debug["certification_candidate_attempt_limit"] = attempts_limit
                return manifest, debug
            reason = debug.get("error") or debug.get("validate_err") or "candidate did not clear all Writer gates"
            print(f"[cert-writer] attempt {idx} rejected: {reason}")
        last_debug["accepted"] = False
        last_debug["certification_candidate_attempt"] = attempts_limit
        last_debug["certification_candidate_attempt_limit"] = attempts_limit
        if not last_debug.get("error"):
            last_debug["error"] = f"no accepted Writer candidate after {attempts_limit} bounded attempts"
        return last_manifest if last_debug.get("accepted") else None, last_debug

    C.O.generate_candidate_v21 = retrying_generate
    out = Path(out_dir)
    try:
        with P.certification_provider_policy():
            result = C.build_bundle(topic, out_dir)
        result = dict(result)
        result["certification_candidate_attempts"] = len(attempt_evidence)
        _write_json(out / "writer_attempts.json", {
            "max_attempts": attempts_limit,
            "attempt_count": len(attempt_evidence),
            "accepted": True,
            "attempts": attempt_evidence,
        })
        return result
    except Exception as exc:
        _write_json(out / "writer_attempts.json", {
            "max_attempts": attempts_limit,
            "attempt_count": len(attempt_evidence),
            "accepted": False,
            "attempts": attempt_evidence,
        })
        _write_json(out / "certification_failure.json", {
            "stage": "writer_v21_bundle",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "attempt_count": len(attempt_evidence),
        })
        raise
    finally:
        C.O.generate_candidate_v21 = original_generate


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--topic", default="auto")
    p.add_argument("--out", default="artifacts/quality_certification")
    p.add_argument("--allow-provider-calls", action="store_true")
    p.add_argument(
        "--max-writer-attempts",
        type=int,
        default=int(os.getenv("QUALITY_CERTIFICATION_WRITER_ATTEMPTS", "3")),
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.allow_provider_calls or os.getenv("QUALITY_CERTIFICATION_LIVE", "") != C.LIVE_ACK:
        print(
            "REFUSING: resilient certification requires BOTH --allow-provider-calls and "
            f"QUALITY_CERTIFICATION_LIVE={C.LIVE_ACK}",
            file=sys.stderr,
        )
        return 2
    try:
        result = run_bundle(args.topic, args.out, max_attempts=args.max_writer_attempts)
    except Exception as exc:
        print(f"CERTIFICATION GENERATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
