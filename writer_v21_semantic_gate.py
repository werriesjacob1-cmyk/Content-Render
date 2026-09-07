"""Fail-closed semantic coverage primitives for Writer V2.1.

The mechanical traceability layer cannot catch every unsupported proposition: a
hallucination can be written entirely with ordinary words, no number, unit, or
proper noun. Writer V2.1 therefore relies on the independent critic's
``claim_support`` verdict for EVERY spoken line. This module makes that coverage
load-bearing instead of treating a missing/malformed critic response as
"zero semantic violations".

Pure/testable except for the caller-supplied ``call_once`` function.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import writer_v2_repair as R


VALID_SEMANTIC_VERDICTS = {
    "SUPPORTED",
    "SUPPORTED_PARAPHRASE",
    "UNSUPPORTED_ADDITION",
    "CONTRADICTED",
    "CONNECTIVE_OR_EDITORIAL",
}


@dataclass(frozen=True)
class SemanticCoverageResult:
    verified: bool
    verdict: Mapping[str, Any] | None
    violations: tuple[Any, ...]
    attempts: int
    errors: tuple[str, ...]
    covered_indices: tuple[int, ...] = ()


class SemanticCoverageFailure:
    """Truthy sentinel placed in candidate hard_violations when coverage fails.

    ``select_best_candidate`` only needs a non-empty hard_violations list to
    disqualify a candidate. Keeping outage/failure distinct from a fabricated
    TraceabilityViolation avoids falsely claiming the script itself contained a
    factual error when the actual failure was inability to verify it.
    """

    def __init__(self, reason: str):
        self.reason = str(reason or "semantic critic unavailable")

    def __repr__(self) -> str:
        return f"SemanticCoverageFailure({self.reason!r})"


def _mapping_index(key: Any) -> int | None:
    """Return an explicitly encoded fallback-map index, never an inferred one."""
    if type(key) is int:  # bool is intentionally rejected; bool subclasses int.
        return key
    if isinstance(key, str):
        text = key.strip()
        if text and (text.isdigit() or (text.startswith("-") and text[1:].isdigit())):
            return int(text)
    return None


def _canonical_claim_support(raw: Any) -> tuple[list[Mapping[str, Any]], tuple[str, ...]]:
    """Strictly canonicalize only the two supported critic payload shapes.

    Structured output is a list of objects and MUST carry an explicit integer
    ``beat_index`` on every row. The live-observed non-structured fallback is a
    mapping keyed by beat index; that key is itself the explicit identity, so a
    value may be a verdict string or a verdict object. Nothing here derives an
    identity from list position, silently drops malformed entries, or repairs a
    mixed payload into apparent semantic coverage.
    """
    rows: list[Mapping[str, Any]] = []
    errors: list[str] = []

    if isinstance(raw, list):
        for pos, item in enumerate(raw):
            if not isinstance(item, Mapping):
                errors.append(f"claim_support row {pos} is not an object")
                continue
            if "beat_index" not in item:
                errors.append(f"claim_support row {pos} is missing beat_index")
                continue
            idx = item.get("beat_index")
            if type(idx) is not int:
                errors.append(f"claim_support row {pos} beat_index is not an integer")
                continue
            if "verdict" not in item:
                errors.append(f"claim_support row {pos} is missing verdict")
                continue
            rows.append(dict(item))
        return rows, tuple(errors)

    if isinstance(raw, Mapping):
        for key, value in raw.items():
            idx = _mapping_index(key)
            if idx is None:
                errors.append(f"claim_support key {key!r} is not an integer beat identity")
                continue

            if isinstance(value, str):
                rows.append({
                    "beat_index": idx,
                    "verdict": value,
                    "unsupported_proposition": "",
                })
                continue

            if not isinstance(value, Mapping):
                errors.append(f"claim_support value for beat_index {idx} is malformed")
                continue
            if "verdict" not in value:
                errors.append(f"claim_support value for beat_index {idx} is missing verdict")
                continue
            if "beat_index" in value:
                nested_idx = value.get("beat_index")
                if type(nested_idx) is not int:
                    errors.append(f"claim_support value for beat_index {idx} has non-integer nested beat_index")
                    continue
                if nested_idx != idx:
                    errors.append(
                        f"claim_support key/index disagreement: key {idx}, nested beat_index {nested_idx}"
                    )
                    continue
            row = dict(value)
            row["beat_index"] = idx
            rows.append(row)
        return rows, tuple(errors)

    return [], ("claim_support missing or not a supported list/object shape",)


def validate_semantic_coverage(
    critic_verdict: Mapping[str, Any] | None,
    num_beats: int,
) -> tuple[bool, tuple[str, ...], tuple[int, ...]]:
    """Require exactly one valid semantic verdict for hook, every beat, payoff.

    Hook is index 0, story beats are 1..N, payoff is N+1. Only two payload
    shapes are accepted: structured list rows with explicit integer identities,
    and the live-observed fallback mapping whose keys explicitly carry those
    identities. Missing, duplicate, out-of-range, unknown-verdict, malformed,
    mixed, or silently repairable rows fail closed.
    """
    if not isinstance(critic_verdict, Mapping):
        return False, ("critic verdict missing or not an object",), ()

    expected = tuple(range(0, int(num_beats) + 2))
    expected_set = set(expected)
    rows, shape_errors = _canonical_claim_support(critic_verdict.get("claim_support"))
    errors: list[str] = list(shape_errors)
    seen: dict[int, int] = {}

    for row in rows:
        idx = row.get("beat_index")
        verdict = row.get("verdict")
        if type(idx) is not int:
            errors.append("claim_support beat_index is not an integer")
            continue
        if idx not in expected_set:
            errors.append(f"claim_support beat_index {idx} is out of range")
            continue
        seen[idx] = seen.get(idx, 0) + 1
        if verdict not in VALID_SEMANTIC_VERDICTS:
            errors.append(f"beat {idx} has invalid semantic verdict {verdict!r}")
        if verdict in R.SEMANTIC_UNSUPPORTED_VERDICTS:
            prop = str(row.get("unsupported_proposition") or "").strip()
            if not prop:
                errors.append(f"beat {idx} {verdict} is missing unsupported_proposition")

    missing = [idx for idx in expected if seen.get(idx, 0) == 0]
    duplicated = [idx for idx in expected if seen.get(idx, 0) > 1]
    if missing:
        errors.append("missing semantic verdict(s) for beat_index " + ",".join(map(str, missing)))
    if duplicated:
        errors.append("duplicate semantic verdict(s) for beat_index " + ",".join(map(str, duplicated)))

    covered = tuple(idx for idx in expected if seen.get(idx, 0) == 1)
    return (not errors), tuple(errors), covered


def critic_with_bounded_retry(
    *,
    num_beats: int,
    call_once: Callable[[], tuple[Mapping[str, Any] | None, str | None]],
    max_attempts: int = 2,
) -> SemanticCoverageResult:
    """Try the semantic critic a bounded number of times, then fail closed.

    ``call_once`` returns ``(parsed_verdict_or_none, error_or_none)``. A parsed
    response that does not cover every spoken line is itself a failed attempt;
    we retry once because live Groq fallback responses have been structurally
    inconsistent under contention. There is never a score-only/mechanical-only
    acceptance fallback.
    """
    attempts = max(1, int(max_attempts))
    errors: list[str] = []

    for attempt in range(1, attempts + 1):
        verdict, call_error = call_once()
        if call_error:
            errors.append(f"attempt {attempt}: {call_error}")
        ok, coverage_errors, covered = validate_semantic_coverage(verdict, num_beats)
        if ok:
            violations = tuple(R.derive_semantic_violations(verdict, num_beats))
            return SemanticCoverageResult(
                verified=True,
                verdict=verdict,
                violations=violations,
                attempts=attempt,
                errors=tuple(errors),
                covered_indices=covered,
            )
        if coverage_errors:
            errors.extend(f"attempt {attempt}: {e}" for e in coverage_errors)

    return SemanticCoverageResult(
        verified=False,
        verdict=None,
        violations=(),
        attempts=attempts,
        errors=tuple(errors) or ("semantic critic unavailable",),
        covered_indices=(),
    )
