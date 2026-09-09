#!/usr/bin/env python3
"""Deterministic topic × treatment × writability scoring for Content Render.

No provider calls. The selector ranks every eligible treatment for a fact using
signals already present in the curated topic bank, visual scout, and durable
learning ledger. It exists to avoid the old failure mode where a strong topic
was paired with a hash-selected treatment that structurally encouraged weak or
repetitive storytelling.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import re
from typing import Any, Mapping, Sequence

import writer_v2 as W


TREATMENT_SIGNALS: Mapping[str, tuple[str, ...]] = {
    "HIDDEN_MECHANISM": ("because", "mechanism", "inside", "process", "works", "cause", "hidden", "beneath"),
    "CASE_FILE": ("discovered", "mystery", "evidence", "observation", "clue", "wrong", "found", "investigation"),
    "ONE_OBJECT_JOURNEY": ("molecule", "particle", "object", "travels", "journey", "path", "enters", "moves", "ends up"),
    "SCALE_REVEAL": ("times", "million", "billion", "trillion", "size", "distance", "scale", "speed", "density", "larger", "smaller"),
    "MYTH_AUTOPSY": ("myth", "belief", "misconception", "actually", "contrary", "wrong", "not true", "people think"),
    "TIMELINE_TRANSFORMATION": ("years", "ago", "first", "then", "over time", "changed", "evolved", "became", "history"),
    "INSIDE_THE_SYSTEM": ("system", "organ", "body", "network", "component", "inside", "cycle", "feedback", "interaction"),
    "VISUAL_EXPERIMENT": ("experiment", "test", "try", "drop", "heat", "freeze", "pressure", "observe", "measure", "happens"),
}

# Treatments whose beat structures demand evidence shapes that should not be
# inferred merely because their name sounds exciting.
REQUIRED_SIGNAL_MIN = {
    "SCALE_REVEAL": 1,
    "MYTH_AUTOPSY": 1,
    "ONE_OBJECT_JOURNEY": 1,
    "VISUAL_EXPERIMENT": 1,
}


def _text(fact: Mapping[str, Any]) -> str:
    pieces = [
        fact.get("fact"), fact.get("angle"), fact.get("wow"), fact.get("title"),
        " ".join(str(x) for x in (fact.get("queries") or [])),
        " ".join(str(x) for x in (fact.get("key_terms") or [])),
    ]
    return " ".join(str(x or "") for x in pieces).lower()


def _hits(text: str, terms: Sequence[str]) -> int:
    return sum(1 for t in terms if t in text)


def _jargon_burden(fact: Mapping[str, Any]) -> float:
    terms = [str(x).strip() for x in (fact.get("key_terms") or []) if str(x).strip()]
    if not terms:
        return 0.0
    burden = 0.0
    for term in terms:
        words = term.split()
        burden += max(0, len(words) - 2) * 0.28
        burden += 0.22 if re.search(r"[A-Z]{2,}|\d|[-/]", term) else 0.0
        burden += 0.18 if len(term) > 22 else 0.0
    return min(2.0, burden)


def _evidence_richness(fact: Mapping[str, Any]) -> float:
    populated = sum(bool(str(fact.get(k) or "").strip()) for k in ("fact", "angle", "wow"))
    q = len([x for x in (fact.get("queries") or []) if str(x).strip()])
    kt = len([x for x in (fact.get("key_terms") or []) if str(x).strip()])
    return min(2.0, populated * 0.35 + min(q, 4) * 0.15 + min(kt, 4) * 0.12)


def _distinct_beat_proxy(fact: Mapping[str, Any]) -> float:
    vals = [str(fact.get(k) or "").strip().lower() for k in ("fact", "angle", "wow")]
    vals.extend(str(x).strip().lower() for x in (fact.get("queries") or []))
    vals.extend(str(x).strip().lower() for x in (fact.get("key_terms") or []))
    vals = [v for v in vals if v]
    if not vals:
        return 0.0
    # Distinct lexical nuclei, not raw field count. This penalizes topics whose
    # bank metadata repeats the same phrase across every field.
    nuclei: set[str] = set()
    for value in vals:
        words = [w for w in re.findall(r"[a-z0-9]+", value) if len(w) > 4]
        nuclei.update(words[:5])
    return min(2.0, len(nuclei) / 6.0)


def _payoff_potential(fact: Mapping[str, Any]) -> float:
    wow = str(fact.get("wow") or "").strip()
    angle = str(fact.get("angle") or "").strip()
    if not wow and not angle:
        return 0.0
    score = 0.45 if wow else 0.2
    text = (wow + " " + angle).lower()
    if any(x in text for x in ("means", "reveals", "because", "so that", "which means", "today", "you")):
        score += 0.35
    if re.search(r"\b\d", text):
        score += 0.15
    return min(1.0, score)


@dataclass(frozen=True)
class TreatmentScore:
    topic_id: str
    treatment: str
    total: float
    signal_hits: int
    visual_score: float
    evidence_richness: float
    distinct_beat_proxy: float
    payoff_potential: float
    jargon_burden: float
    recent_penalty: float
    failed_pair_penalty: float
    structural_penalty: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_treatment(
    fact: Mapping[str, Any],
    treatment: str,
    *,
    recent_treatments: Sequence[str] = (),
    failed_pair_counts: Mapping[tuple[str, str], int] | None = None,
) -> TreatmentScore:
    if treatment not in W.TREATMENTS:
        raise ValueError(f"unknown treatment {treatment!r}")
    topic_id = str(fact.get("id") or "")
    text = _text(fact)
    signal_hits = _hits(text, TREATMENT_SIGNALS.get(treatment, ()))
    visual = float((W.visual_scout_score(dict(fact), banned_re=None) or {}).get("score") or 0.0)
    evidence = _evidence_richness(fact)
    distinct = _distinct_beat_proxy(fact)
    payoff = _payoff_potential(fact)
    jargon = _jargon_burden(fact)
    recent_penalty = 0.55 if treatment in set(recent_treatments) else 0.0
    failed = int((failed_pair_counts or {}).get((topic_id, treatment), 0))
    failed_penalty = min(2.4, failed * 0.8)
    structural_penalty = 0.0
    required = REQUIRED_SIGNAL_MIN.get(treatment, 0)
    if signal_hits < required:
        structural_penalty += 1.4
    # INSIDE_THE_SYSTEM is useful for true systems, but without multiple system
    # signals its three internal-process beats can collapse into mechanism
    # restatement (the exact run-5 failure shape).
    if treatment == "INSIDE_THE_SYSTEM" and signal_hits < 2:
        structural_penalty += 0.8
    # HIDDEN_MECHANISM benefits from mechanism evidence; without it the middle
    # beats are likely to invent causal texture.
    if treatment == "HIDDEN_MECHANISM" and signal_hits < 1:
        structural_penalty += 0.65

    total = (
        visual * 0.34
        + evidence * 1.15
        + distinct * 1.35
        + payoff * 0.95
        + min(signal_hits, 4) * 0.62
        - jargon * 0.55
        - recent_penalty
        - failed_penalty
        - structural_penalty
    )
    total = round(total, 4)
    reasons = (
        f"signal_hits={signal_hits}",
        f"distinct={distinct:.2f}",
        f"evidence={evidence:.2f}",
        f"visual={visual:.2f}",
        f"failed_pair_count={failed}",
    )
    return TreatmentScore(
        topic_id=topic_id,
        treatment=treatment,
        total=total,
        signal_hits=signal_hits,
        visual_score=round(visual, 3),
        evidence_richness=round(evidence, 3),
        distinct_beat_proxy=round(distinct, 3),
        payoff_potential=round(payoff, 3),
        jargon_burden=round(jargon, 3),
        recent_penalty=round(recent_penalty, 3),
        failed_pair_penalty=round(failed_penalty, 3),
        structural_penalty=round(structural_penalty, 3),
        reasons=reasons,
    )


def rank_treatments(
    fact: Mapping[str, Any],
    *,
    recent_treatments: Sequence[str] = (),
    failed_pair_counts: Mapping[tuple[str, str], int] | None = None,
) -> list[TreatmentScore]:
    rows = [
        score_treatment(
            fact,
            name,
            recent_treatments=recent_treatments,
            failed_pair_counts=failed_pair_counts,
        )
        for name in sorted(W.TREATMENTS)
    ]
    # Stable lexical tie break keeps reruns reproducible.
    return sorted(rows, key=lambda r: (r.total, r.treatment), reverse=True)


def choose_treatment(
    fact: Mapping[str, Any],
    *,
    recent_treatments: Sequence[str] = (),
    failed_pair_counts: Mapping[tuple[str, str], int] | None = None,
) -> tuple[str, dict[str, Any]]:
    ranked = rank_treatments(
        fact,
        recent_treatments=recent_treatments,
        failed_pair_counts=failed_pair_counts,
    )
    if not ranked:
        raise RuntimeError("no Writer V2 treatments available")
    winner = ranked[0]
    legacy = W.select_treatment(str(fact.get("id") or ""), recent_treatments=recent_treatments) or ""
    return winner.treatment, {
        "schema": "topic-treatment-writability-v1",
        "topic_id": str(fact.get("id") or ""),
        "winner": winner.to_dict(),
        "legacy_hash_treatment": legacy,
        "changed_from_legacy": bool(legacy and legacy != winner.treatment),
        "ranked": [x.to_dict() for x in ranked],
    }


def score_topic(
    fact: Mapping[str, Any],
    *,
    recent_treatments: Sequence[str] = (),
    failed_pair_counts: Mapping[tuple[str, str], int] | None = None,
) -> tuple[float, str, dict[str, Any]]:
    treatment, evidence = choose_treatment(
        fact,
        recent_treatments=recent_treatments,
        failed_pair_counts=failed_pair_counts,
    )
    winner = evidence["winner"]
    # Keep score bounded and comparable for topic ranking. The treatment-fit
    # total may exceed 10 because it is an internal additive score.
    normalized = 10.0 / (1.0 + math.exp(-((float(winner["total"]) - 4.0) / 2.0)))
    return round(normalized, 4), treatment, evidence
