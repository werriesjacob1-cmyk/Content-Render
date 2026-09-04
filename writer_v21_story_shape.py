"""Deterministic narrative-shape and first-8-second diagnostics for Writer V2.1.

Treatment names are not evidence of real structural variety.  This module looks
at the surface FUNCTION of each spoken beat (question, evidence, reversal,
mechanism, scale, consequence, etc.) and compares the resulting sequence across
scripts.  It also estimates what a viewer hears in the first eight seconds so a
strong whole-script score cannot hide a slow opening.

Everything here is non-gating telemetry.  No virality probability is invented.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Mapping, Sequence


FEATURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("question", re.compile(r"\?|\b(?:why|how|what if|could|can|would)\b", re.I)),
    ("evidence", re.compile(r"\b(?:evidence|measured|observed|found|recorded|detected|study|data|clue)\b", re.I)),
    ("wrong_hypothesis", re.compile(r"\b(?:assumed|thought|believed|seemed|expected|supposed|wrong)\b", re.I)),
    ("reversal", re.compile(r"\b(?:but|instead|actually|except|yet|turns out|rather than)\b", re.I)),
    ("mechanism", re.compile(r"\b(?:because|causes?|triggers?|works by|mechanism|pressure|reaction|gravity|friction|absorbs?|releases?|converts?)\b", re.I)),
    ("scale", re.compile(r"\b(?:times|million|billion|trillion|larger|smaller|taller|heavier|faster|slower|scale|enormous|tiny)\b|\d", re.I)),
    ("timeline", re.compile(r"\b(?:years? ago|seconds? later|before|after|eventually|first|then|today|now|over time)\b", re.I)),
    ("journey", re.compile(r"\b(?:enters?|leaves?|travels?|moves?|crosses?|passes?|ends up|begins?|starts?)\b", re.I)),
    ("consequence", re.compile(r"\b(?:means|therefore|so that|result|consequence|leads to|allows?|prevents?|matters|changes?)\b", re.I)),
    ("viewer_reframe", re.compile(r"\b(?:you|your|we|our)\b.*\b(?:see|think|feel|experience|notice|realize|remember)\b", re.I)),
    ("comparison", re.compile(r"\b(?:than|compared with|compared to|versus|vs\.?|like a|as .* as)\b", re.I)),
    ("experiment", re.compile(r"\b(?:test|experiment|try this|set up|drop|pour|place|watch what happens)\b", re.I)),
)

PRIMARY_PRIORITY = (
    "question", "wrong_hypothesis", "evidence", "reversal", "experiment",
    "mechanism", "scale", "journey", "timeline", "consequence", "viewer_reframe", "comparison",
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _words(value: Any) -> list[str]:
    return re.findall(r"\b[\w'’-]+\b", _clean(value))


def line_features(line: str) -> tuple[str, ...]:
    text = _clean(line)
    found = [name for name, pattern in FEATURE_PATTERNS if pattern.search(text)]
    return tuple(found or ["statement"])


def primary_function(line: str) -> str:
    features = set(line_features(line))
    for name in PRIMARY_PRIORITY:
        if name in features:
            return name
    return "statement"


def shape_signature(hook: str, beats: Sequence[str], payoff: str) -> dict[str, Any]:
    lines = [_clean(hook), *[_clean(x) for x in beats], _clean(payoff)]
    features = [line_features(line) for line in lines]
    primary = [primary_function(line) for line in lines]
    return {
        "primary_sequence": primary,
        "feature_sequence": [list(x) for x in features],
        "unique_primary_functions": sorted(set(primary)),
        "unique_function_count": len(set(primary)),
        "repeated_primary_runs": sum(1 for i in range(1, len(primary)) if primary[i] == primary[i - 1]),
        "gating": False,
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def shape_similarity(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    """0..1 structural similarity based on aligned beat functions/features."""
    ap = list(a.get("primary_sequence") or [])
    bp = list(b.get("primary_sequence") or [])
    af = list(a.get("feature_sequence") or [])
    bf = list(b.get("feature_sequence") or [])
    n = max(len(ap), len(bp), 1)
    primary_matches = sum(1 for i in range(min(len(ap), len(bp))) if ap[i] == bp[i]) / n
    feature_scores = []
    for i in range(min(len(af), len(bf))):
        feature_scores.append(_jaccard(set(af[i]), set(bf[i])))
    feature_mean = sum(feature_scores) / len(feature_scores) if feature_scores else 0.0
    length_penalty = min(len(ap), len(bp)) / max(len(ap), len(bp), 1)
    return round((0.55 * primary_matches + 0.35 * feature_mean + 0.10 * length_penalty), 3)


def compare_scripts(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    sa = shape_signature(a.get("hook", ""), a.get("beats") or [], a.get("payoff", ""))
    sb = shape_signature(b.get("hook", ""), b.get("beats") or [], b.get("payoff", ""))
    sim = shape_similarity(sa, sb)
    return {
        "similarity": sim,
        "a_primary_sequence": sa["primary_sequence"],
        "b_primary_sequence": sb["primary_sequence"],
        "same_treatment_label": bool(a.get("treatment") and a.get("treatment") == b.get("treatment")),
        "high_shape_similarity": sim >= 0.75,
        "gating": False,
    }


def portfolio_diversity(scripts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    for i in range(len(scripts)):
        for j in range(i + 1, len(scripts)):
            row = compare_scripts(scripts[i], scripts[j])
            row["a_index"] = i
            row["b_index"] = j
            rows.append(row)
    similarities = [r["similarity"] for r in rows]
    return {
        "pair_count": len(rows),
        "mean_pair_similarity": round(sum(similarities) / len(similarities), 3) if similarities else None,
        "max_pair_similarity": max(similarities) if similarities else None,
        "high_similarity_pairs": [
            {"a_index": r["a_index"], "b_index": r["b_index"], "similarity": r["similarity"]}
            for r in rows if r["high_shape_similarity"]
        ],
        "pairs": rows,
        "gating": False,
    }


def first_eight_seconds_audit(
    hook: str,
    beats: Sequence[str],
    *,
    words_per_second: float = 2.6,
    window_seconds: float = 8.0,
) -> dict[str, Any]:
    """Estimate the spoken narrative exposed before ~8 seconds.

    Uses a transparent WPS estimate until real TTS timings exist.  It preserves
    exact word/time assumptions so later audio-backed analysis can replace it.
    """
    if not math.isfinite(words_per_second) or words_per_second <= 0:
        raise ValueError("words_per_second must be finite and > 0")
    if not math.isfinite(window_seconds) or window_seconds <= 0:
        raise ValueError("window_seconds must be finite and > 0")

    lines = [_clean(hook), *[_clean(x) for x in beats]]
    budget_words = words_per_second * window_seconds
    elapsed_words = 0
    exposed: list[dict[str, Any]] = []
    for idx, line in enumerate(lines):
        wc = len(_words(line))
        start_s = elapsed_words / words_per_second
        end_s = (elapsed_words + wc) / words_per_second
        if start_s >= window_seconds:
            break
        fraction = 1.0 if end_s <= window_seconds else max(0.0, (budget_words - elapsed_words) / max(wc, 1))
        exposed.append({
            "beat_index": idx,
            "role": "hook" if idx == 0 else f"beat_{idx}",
            "text": line,
            "word_count": wc,
            "start_s": round(start_s, 2),
            "end_s": round(min(end_s, window_seconds), 2),
            "fraction_heard": round(min(1.0, fraction), 3),
            "primary_function": primary_function(line),
            "features": list(line_features(line)),
        })
        elapsed_words += wc

    functions = [x["primary_function"] for x in exposed if x["fraction_heard"] >= 0.5]
    distinct = len(set(functions))
    fully_heard_after_hook = sum(1 for x in exposed[1:] if x["fraction_heard"] >= 0.95)
    warnings = []
    hook_words = len(_words(hook))
    hook_seconds = hook_words / words_per_second
    if hook_seconds > 3.0:
        warnings.append("hook_consumes_more_than_3_seconds")
    if fully_heard_after_hook < 1:
        warnings.append("no_full_escalation_beat_by_8_seconds")
    if len(functions) >= 2 and distinct <= 1:
        warnings.append("opening_function_repeats_without_structural_escalation")
    if exposed and all(x["primary_function"] in {"statement", "comparison", "scale"} for x in exposed):
        warnings.append("opening_is_description_or_magnitude_only")

    return {
        "assumed_words_per_second": words_per_second,
        "window_seconds": window_seconds,
        "word_budget": round(budget_words, 1),
        "hook_estimated_seconds": round(hook_seconds, 2),
        "exposed_beats": exposed,
        "fully_heard_beats_after_hook": fully_heard_after_hook,
        "opening_primary_functions": functions,
        "opening_distinct_function_count": distinct,
        "warnings": warnings,
        "gating": False,
    }
