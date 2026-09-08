#!/usr/bin/env python3
"""Offline analyzer for real Writer V2.1 rejection artifacts.

Input is one or more ``writer_attempts.json`` files downloaded from private
quality-certification artifacts. The tool makes ZERO provider/network calls and
never edits the inputs. It turns historical rounds into a compact failure matrix
so Writer/prompt/repair changes are driven by observed failure families instead
of anecdotes.

Example:
    python writer_replay.py run2/writer_attempts.json run3/writer_attempts.json \
        run4/writer_attempts.json run5/writer_attempts.json
    python writer_replay.py --json ...
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
from typing import Any, Iterable


VALIDATE_CATEGORIES = (
    "total_length",
    "scene_length",
    "hook_question_conflict",
    "repetition",
    "formal_connector",
    "spoken_flow",
    "headline_restatement",
    "missing_key_terms",
    "hook_length",
    "other",
    "none",
)


def classify_validate_error(error: str | None) -> str:
    if not error:
        return "none"
    text = str(error).lower()
    if "script word count" in text:
        return "total_length"
    if "voiceover too long" in text:
        return "scene_length"
    if "phrased as a question" in text:
        return "hook_question_conflict"
    if "too similar" in text or "restated in" in text:
        return "repetition"
    if "formal connector 'thus'" in text or 'formal connector "thus"' in text:
        return "formal_connector"
    if "stacks a second named" in text:
        return "spoken_flow"
    if "hook_headline" in text and "nearly identical" in text:
        return "headline_restatement"
    if "mandatory key terms" in text:
        return "missing_key_terms"
    if "hook length" in text:
        return "hook_length"
    return "other"


def iter_rounds(payload: dict[str, Any], source: str = "") -> Iterable[dict[str, Any]]:
    for attempt_index, attempt in enumerate(payload.get("attempts") or [], 1):
        treatment = attempt.get("treatment") or "UNKNOWN"
        for row in attempt.get("rounds") or []:
            plan = row.get("repair_plan") or {}
            yield {
                "source": source,
                "attempt": attempt_index,
                "round": row.get("round"),
                "treatment": treatment,
                "validate_err": row.get("validate_err"),
                "validate_category": classify_validate_error(row.get("validate_err")),
                "mechanical_hard_count": int(row.get("mechanical_hard_count") or 0),
                "semantic_violation_count": int(row.get("semantic_violation_count") or 0),
                "semantic_verified": row.get("semantic_verified") is True,
                "repair_type": plan.get("repair_type") or "NONE",
            }


def summarize_payloads(named_payloads: Iterable[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    attempts = 0
    accepted_attempts = 0
    for source, payload in named_payloads:
        payload_attempts = payload.get("attempts") or []
        attempts += len(payload_attempts)
        accepted_attempts += sum(1 for a in payload_attempts if a.get("accepted") is True)
        rows.extend(iter_rounds(payload, source))

    validate_counts = collections.Counter(r["validate_category"] for r in rows)
    repair_counts = collections.Counter(r["repair_type"] for r in rows)
    treatment_counts = collections.Counter(r["treatment"] for r in rows)
    by_treatment: dict[str, dict[str, int]] = {}
    for treatment in sorted(treatment_counts):
        by_treatment[treatment] = dict(sorted(collections.Counter(
            r["validate_category"] for r in rows if r["treatment"] == treatment
        ).items()))

    tier1_clean = [
        r for r in rows
        if r["mechanical_hard_count"] == 0
        and r["semantic_violation_count"] == 0
        and r["semantic_verified"]
    ]
    length_rounds = validate_counts["total_length"] + validate_counts["scene_length"]
    rounds = len(rows)
    return {
        "attempts": attempts,
        "accepted_attempts": accepted_attempts,
        "rounds": rounds,
        "validate_categories": dict(sorted(validate_counts.items())),
        "repair_types": dict(sorted(repair_counts.items())),
        "treatments": dict(sorted(treatment_counts.items())),
        "by_treatment": by_treatment,
        "length_constraint_rounds": length_rounds,
        "length_constraint_share": round(length_rounds / rounds, 4) if rounds else 0.0,
        "tier1_clean_rounds": len(tier1_clean),
        "tier1_clean_share": round(len(tier1_clean) / rounds, 4) if rounds else 0.0,
        "tier1_clean_validate_categories": dict(sorted(collections.Counter(
            r["validate_category"] for r in tier1_clean
        ).items())),
    }


def load_payload(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or not isinstance(payload.get("attempts"), list):
        raise ValueError(f"{path}: expected writer_attempts object with attempts[]")
    return payload


def render_text(summary: dict[str, Any]) -> str:
    lines = [
        "Writer V2.1 offline rejection replay",
        f"attempts={summary['attempts']} accepted={summary['accepted_attempts']} rounds={summary['rounds']}",
        f"length_constraint_rounds={summary['length_constraint_rounds']} "
        f"({summary['length_constraint_share']:.1%})",
        f"tier1_clean_rounds={summary['tier1_clean_rounds']} "
        f"({summary['tier1_clean_share']:.1%})",
        "validate_categories=" + json.dumps(summary["validate_categories"], sort_keys=True),
        "repair_types=" + json.dumps(summary["repair_types"], sort_keys=True),
        "treatments=" + json.dumps(summary["treatments"], sort_keys=True),
    ]
    for treatment, counts in summary["by_treatment"].items():
        lines.append(f"treatment[{treatment}]=" + json.dumps(counts, sort_keys=True))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="writer_attempts.json artifact files")
    ap.add_argument("--json", action="store_true", help="emit machine-readable summary")
    args = ap.parse_args()
    named = [(Path(p).name, load_payload(p)) for p in args.paths]
    summary = summarize_payloads(named)
    print(json.dumps(summary, indent=2, sort_keys=True) if args.json else render_text(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
