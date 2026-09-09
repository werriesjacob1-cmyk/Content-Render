#!/usr/bin/env python3
"""Resilient private flagship certification runner.

Wraps ``quality_certification_generate`` without changing unattended production.
The exact Writer V2.1 acceptance gates remain load-bearing.  The runner supports
both a small number of independent provider drafts and, when explicitly enabled,
one deterministic evidence-only seed.  The seed is only an INPUT candidate: it
must still pass the canonical Writer V2.1 traceability, semantic critic,
validate(), quality floor, evidence bridge, and visual-session preflight.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import quality_certification_generate as C
import quality_writer_evidence_seed as S
import quality_writer_provider_resilience as P


MAX_HARD_ATTEMPTS = 3


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)


def _attempt_summary(
    index: int,
    manifest,
    debug: dict[str, Any],
    candidate_kind: str = "provider_writer",
) -> dict[str, Any]:
    return {
        "attempt": index,
        "candidate_kind": candidate_kind,
        "accepted": bool(manifest and debug.get("accepted")),
        "error": debug.get("error"),
        "validate_err": debug.get("validate_err"),
        "treatment": debug.get("treatment"),
        "total_calls": debug.get("total_calls"),
        "semantic_retries_used": debug.get("semantic_retries_used"),
        "repair_rounds": debug.get("repair_rounds"),
        "rounds": debug.get("rounds") or [],
        "calls": debug.get("calls") or [],
        "deterministic_evidence_seed": bool(debug.get("deterministic_evidence_seed")),
    }


def _run_evidence_seed(original_generate, args, kwargs):
    """Inject one deterministic Writer-shaped seed into canonical V2.1 gates.

    Only the initial ``writer_v2_output`` call is replaced.  Critic and repair
    calls continue through the currently-active certification provider policy,
    so semantic verification remains independent and load-bearing.
    """
    fact = args[0] if args else kwargs.get("fact")
    if not fact:
        return None, None

    dossier = C.G.research_dossier(fact)
    inventory = C.W.build_claim_inventory(fact, dossier_facts=dossier, grounded=bool(dossier))
    seed = S.build_evidence_seed(fact, inventory)
    if not seed:
        return None, None

    current_structured_call = C.O.G._v2_structured_call
    injected = {"done": False}

    def seed_first_call(prompt, schema, label, calls):
        if label == "writer_v2_output" and not injected["done"]:
            injected["done"] = True
            return json.dumps(seed, ensure_ascii=False), "deterministic_evidence_seed"
        return current_structured_call(prompt, schema, label, calls)

    C.O.G._v2_structured_call = seed_first_call
    try:
        manifest, debug = original_generate(*args, **kwargs)
    finally:
        C.O.G._v2_structured_call = current_structured_call

    debug = dict(debug or {})
    debug["deterministic_evidence_seed"] = True
    debug["deterministic_seed_initial_call_injected"] = injected["done"]
    return manifest, debug


def run_bundle(
    topic: str,
    out_dir: str,
    max_attempts: int = 3,
    prefer_evidence_seed: bool = False,
) -> dict[str, Any]:
    attempts_limit = max(1, min(int(max_attempts), MAX_HARD_ATTEMPTS))
    original_generate = C.O.generate_candidate_v21
    attempt_evidence: list[dict[str, Any]] = []
    selected_topic_id = {"value": ""}

    def retrying_generate(*args, **kwargs):
        last_manifest = None
        last_debug: dict[str, Any] = {"accepted": False, "error": "no Writer attempt executed"}
        fact = args[0] if args else kwargs.get("fact")
        if isinstance(fact, dict):
            selected_topic_id["value"] = str(fact.get("id") or "").strip()

        if prefer_evidence_seed:
            print("[cert-writer] trying deterministic evidence-only seed through canonical V2.1 gates")
            seed_manifest, seed_debug = _run_evidence_seed(original_generate, args, kwargs)
            if seed_debug is not None:
                attempt_evidence.append(_attempt_summary(
                    len(attempt_evidence) + 1,
                    seed_manifest,
                    seed_debug,
                    candidate_kind="deterministic_evidence_seed",
                ))
                last_manifest, last_debug = seed_manifest, seed_debug
                if seed_manifest and seed_debug.get("accepted"):
                    seed_debug["certification_candidate_attempt"] = len(attempt_evidence)
                    seed_debug["certification_candidate_attempt_limit"] = attempts_limit + 1
                    return seed_manifest, seed_debug
                reason = seed_debug.get("error") or seed_debug.get("validate_err") or "seed did not clear all Writer gates"
                print(f"[cert-writer] evidence seed rejected: {reason}")
            else:
                print("[cert-writer] no evidence seed is defined for this exact topic/evidence state")

        for provider_idx in range(1, attempts_limit + 1):
            print(f"[cert-writer] provider candidate attempt {provider_idx}/{attempts_limit}")
            manifest, debug = original_generate(*args, **kwargs)
            debug = dict(debug or {})
            attempt_evidence.append(_attempt_summary(
                len(attempt_evidence) + 1,
                manifest,
                debug,
                candidate_kind="provider_writer",
            ))
            last_manifest, last_debug = manifest, debug
            if manifest and debug.get("accepted"):
                debug["certification_candidate_attempt"] = len(attempt_evidence)
                debug["certification_candidate_attempt_limit"] = attempts_limit + (1 if prefer_evidence_seed else 0)
                return manifest, debug
            reason = debug.get("error") or debug.get("validate_err") or "candidate did not clear all Writer gates"
            print(f"[cert-writer] provider attempt {provider_idx} rejected: {reason}")

        last_debug["accepted"] = False
        last_debug["certification_candidate_attempt"] = len(attempt_evidence)
        last_debug["certification_candidate_attempt_limit"] = attempts_limit + (1 if prefer_evidence_seed else 0)
        if not last_debug.get("error"):
            last_debug["error"] = (
                f"no accepted Writer candidate after {len(attempt_evidence)} bounded certification candidates"
            )
        return last_manifest if last_debug.get("accepted") else None, last_debug

    C.O.generate_candidate_v21 = retrying_generate
    out = Path(out_dir)
    try:
        with P.certification_provider_policy():
            result = C.build_bundle(topic, out_dir)
        result = dict(result)
        result["certification_candidate_attempts"] = len(attempt_evidence)
        result["evidence_seed_enabled"] = bool(prefer_evidence_seed)
        _write_json(out / "writer_attempts.json", {
            "topic_id": selected_topic_id["value"] or str(result.get("topic_id") or ""),
            "requested_topic": topic,
            "max_provider_attempts": attempts_limit,
            "evidence_seed_enabled": bool(prefer_evidence_seed),
            "attempt_count": len(attempt_evidence),
            "accepted": True,
            "attempts": attempt_evidence,
        })
        return result
    except Exception as exc:
        _write_json(out / "writer_attempts.json", {
            "topic_id": selected_topic_id["value"],
            "requested_topic": topic,
            "max_provider_attempts": attempts_limit,
            "evidence_seed_enabled": bool(prefer_evidence_seed),
            "attempt_count": len(attempt_evidence),
            "accepted": False,
            "attempts": attempt_evidence,
        })
        _write_json(out / "certification_failure.json", {
            "stage": "writer_v21_bundle",
            "topic_id": selected_topic_id["value"],
            "requested_topic": topic,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "attempt_count": len(attempt_evidence),
            "evidence_seed_enabled": bool(prefer_evidence_seed),
        })
        raise
    finally:
        C.O.generate_candidate_v21 = original_generate


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--topic", default="auto")
    p.add_argument("--out", default="artifacts/quality_certification")
    p.add_argument("--allow-provider-calls", action="store_true")
    p.add_argument("--prefer-evidence-seed", action="store_true")
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
        result = run_bundle(
            args.topic,
            args.out,
            max_attempts=args.max_writer_attempts,
            prefer_evidence_seed=args.prefer_evidence_seed,
        )
    except Exception as exc:
        print(f"CERTIFICATION GENERATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
