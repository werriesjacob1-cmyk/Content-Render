"""Blind pairwise editorial judging for Writer V2.1.

Absolute LLM scores have shown noisy swings under provider contention.  Pairwise
comparison asks an easier editorial question: between two already factually-safe
candidates, which one would a cold viewer be more likely to keep watching?

This module deliberately cannot accept a script or override factual gates.  It
only builds anonymized A/B packets, validates structured verdicts, and maps the
winner back to candidate ids for diagnostics.  The live caller is supplied by
an experiment harness; importing this module performs zero network calls.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


PAIRWISE_CRITERIA = (
    "opening_pull",
    "spoken_naturalness",
    "information_gain",
    "escalation",
    "payoff",
    "low_ai_smell",
    "visual_tellability",
)


@dataclass(frozen=True)
class PairwiseCandidate:
    candidate_id: str
    hook: str
    beats: tuple[str, ...]
    payoff: str
    treatment: str = ""
    factual_clean: bool = False
    validate_clean: bool = False
    semantic_verified: bool = False

    def spoken_text(self) -> str:
        return "\n".join([self.hook, *self.beats, self.payoff]).strip()

    def eligible(self) -> bool:
        return bool(
            self.candidate_id
            and self.spoken_text()
            and self.factual_clean
            and self.validate_clean
            and self.semantic_verified
        )


class PairwiseVerdictError(ValueError):
    pass


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _candidate_fingerprint(candidate: PairwiseCandidate) -> str:
    raw = "\x1f".join((candidate.candidate_id, candidate.spoken_text(), candidate.treatment))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def blind_order(
    left: PairwiseCandidate,
    right: PairwiseCandidate,
    *,
    seed: str = "writer-v21-pairwise-v1",
) -> tuple[PairwiseCandidate, PairwiseCandidate]:
    """Return a stable but identity-blind A/B order.

    The order depends on both candidate fingerprints + an explicit experiment
    seed, never on round number / original-vs-repair status.  Re-running the same
    comparison is deterministic, while changing the experiment seed can flip the
    presentation for a robustness check.
    """
    if left.candidate_id == right.candidate_id:
        raise ValueError("pairwise comparison requires two distinct candidate ids")
    a = _candidate_fingerprint(left)
    b = _candidate_fingerprint(right)
    key = hashlib.sha256((seed + "|" + "|".join(sorted((a, b)))).encode("utf-8")).digest()
    ordered = (left, right) if key[0] % 2 == 0 else (right, left)
    return ordered


def build_pairwise_packet(
    left: PairwiseCandidate,
    right: PairwiseCandidate,
    *,
    seed: str = "writer-v21-pairwise-v1",
) -> dict[str, Any]:
    if not left.eligible() or not right.eligible():
        raise ValueError("pairwise editorial judging is only allowed after factual + validate + semantic gates")
    first, second = blind_order(left, right, seed=seed)
    return {
        "aliases": {"A": first.candidate_id, "B": second.candidate_id},
        "candidate_A": first.spoken_text(),
        "candidate_B": second.spoken_text(),
        "criteria": list(PAIRWISE_CRITERIA),
        "seed": seed,
        "gating": False,
    }


def build_pairwise_prompt(packet: Mapping[str, Any]) -> str:
    """Build an identity-blind editorial prompt.

    Never include candidate ids, round numbers, treatment names, scores, repair
    history, or which text is newer.  The judge sees only the two spoken scripts.
    """
    a = _clean(packet.get("candidate_A"))
    b = _clean(packet.get("candidate_B"))
    if not a or not b:
        raise ValueError("pairwise packet requires both candidate texts")
    return f"""You are a ruthless short-form science editor. Compare two ANONYMOUS spoken scripts that have ALREADY passed separate factual/provenance validation. Do not fact-check or reward technical-sounding language. Judge only which version is the stronger human-facing short-form story.

CANDIDATE A:
{packet['candidate_A']}

CANDIDATE B:
{packet['candidate_B']}

Choose A, B, or TIE using these priorities:
1. opening_pull — first 1–1.5 seconds creates a specific need-to-know without a wind-up;
2. spoken_naturalness — sounds like a smart human talking, not an article or LLM;
3. information_gain — every beat advances rather than restates;
4. escalation — curiosity/intensity meaningfully rises through the middle;
5. payoff — specifically resolves/reframes the opening instead of ending on a generic moral;
6. low_ai_smell — avoids hedging, formal connectors, generic wisdom, canned drama, and try-hard comparisons;
7. visual_tellability — the important beats imply concrete things/mechanisms a video can actually show.

Do NOT infer which version is newer, repaired, original, higher-scoring, or preferred by another judge. If the difference is trivial, choose TIE. A repair that is more cautious but flatter is NOT automatically better.

Return ONLY JSON:
{{"winner":"A|B|TIE","confidence":"LOW|MEDIUM|HIGH","criterion_winners":{{"opening_pull":"A|B|TIE","spoken_naturalness":"A|B|TIE","information_gain":"A|B|TIE","escalation":"A|B|TIE","payoff":"A|B|TIE","low_ai_smell":"A|B|TIE","visual_tellability":"A|B|TIE"}},"decisive_reasons":["..."],"losing_defects":["..."],"would_post_winner":true}}"""


def parse_pairwise_verdict(raw: str | Mapping[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception as exc:
        raise PairwiseVerdictError("pairwise verdict is not valid JSON") from exc

    winner = str(data.get("winner") or "").upper()
    confidence = str(data.get("confidence") or "").upper()
    if winner not in {"A", "B", "TIE"}:
        raise PairwiseVerdictError("winner must be A, B, or TIE")
    if confidence not in {"LOW", "MEDIUM", "HIGH"}:
        raise PairwiseVerdictError("confidence must be LOW, MEDIUM, or HIGH")

    cw = data.get("criterion_winners")
    if not isinstance(cw, Mapping) or set(cw) != set(PAIRWISE_CRITERIA):
        raise PairwiseVerdictError("criterion_winners must cover the exact pairwise criteria")
    normalized: dict[str, str] = {}
    for name in PAIRWISE_CRITERIA:
        value = str(cw.get(name) or "").upper()
        if value not in {"A", "B", "TIE"}:
            raise PairwiseVerdictError(f"invalid criterion winner for {name}")
        normalized[name] = value

    reasons = data.get("decisive_reasons")
    defects = data.get("losing_defects")
    if not isinstance(reasons, list) or not isinstance(defects, list):
        raise PairwiseVerdictError("decisive_reasons and losing_defects must be arrays")
    reasons = [_clean(x) for x in reasons if _clean(x)][:5]
    defects = [_clean(x) for x in defects if _clean(x)][:5]
    if winner != "TIE" and not reasons:
        raise PairwiseVerdictError("non-tie verdict requires at least one decisive reason")

    would_post = data.get("would_post_winner")
    if not isinstance(would_post, bool):
        raise PairwiseVerdictError("would_post_winner must be boolean")

    return {
        "winner": winner,
        "confidence": confidence,
        "criterion_winners": normalized,
        "decisive_reasons": reasons,
        "losing_defects": defects,
        "would_post_winner": would_post,
        "gating": False,
    }


def map_verdict_to_candidates(packet: Mapping[str, Any], verdict: Mapping[str, Any]) -> dict[str, Any]:
    aliases = packet.get("aliases") or {}
    if set(aliases) != {"A", "B"}:
        raise PairwiseVerdictError("packet aliases missing")
    winner_alias = verdict.get("winner")
    winner_id = None if winner_alias == "TIE" else aliases.get(winner_alias)
    criterion_ids = {
        name: (None if alias == "TIE" else aliases.get(alias))
        for name, alias in (verdict.get("criterion_winners") or {}).items()
    }
    return {
        **dict(verdict),
        "winner_candidate_id": winner_id,
        "criterion_winner_candidate_ids": criterion_ids,
        "candidate_ids": sorted(aliases.values()),
        "gating": False,
    }


def candidate_from_round(round_info: Mapping[str, Any]) -> PairwiseCandidate:
    hard_count = int(round_info.get("mechanical_hard_count") or 0) + int(round_info.get("semantic_violation_count") or 0)
    return PairwiseCandidate(
        candidate_id=f"candidate_{int(round_info.get('round', 0))}",
        hook=_clean(round_info.get("hook")),
        beats=tuple(_clean(x) for x in (round_info.get("beats") or [])),
        payoff=_clean(round_info.get("payoff")),
        treatment=_clean(round_info.get("treatment")),
        factual_clean=(hard_count == 0),
        validate_clean=not bool(round_info.get("validate_err")),
        semantic_verified=bool(round_info.get("semantic_verified")),
    )


def pairwise_plans_from_debug(debug: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Create blind plans for consecutive eligible rounds, without calling a judge."""
    rounds = list((debug or {}).get("rounds") or [])
    out: list[dict[str, Any]] = []
    for i in range(1, len(rounds)):
        before = candidate_from_round(rounds[i - 1])
        after = candidate_from_round(rounds[i])
        if not before.eligible() or not after.eligible():
            continue
        packet = build_pairwise_packet(before, after, seed=f"repair-transition-{i}")
        out.append({
            "from_round": int(rounds[i - 1].get("round", i - 1)),
            "to_round": int(rounds[i].get("round", i)),
            "packet": packet,
            "prompt": build_pairwise_prompt(packet),
            "gating": False,
        })
    return out
