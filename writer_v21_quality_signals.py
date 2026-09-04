"""Non-gating quality-signal diagnostics for Writer V2.1.

The legacy ``score_script`` self-scorer and the independent V2.1 critic are both
LLM judgments. Live evidence showed a large score swing after a small repair, and
both provider paths currently run at temperature 0.7. Before changing any
promotion threshold or ranking rule, collect apples-to-apples disagreement data.

Nothing in this module can accept/reject a candidate. It only reports evidence.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


# Only compare dimensions that really mean the same thing in both rubrics.
MAPPED_DIMENSIONS = {
    "hook": "hook_strength",
    "escalation": "escalation",
    "payoff": "payoff",
    "clarity": "clarity",
}

CRITIC_CRAFT_DIMENSIONS = (
    "hook_strength",
    "clarity",
    "escalation",
    "payoff",
    "spoken_naturalness",
    "cliche_ai_smell",
    "structural_distinctiveness",
    "visual_tellability",
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _mean(values: Sequence[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def quality_signal_report(
    legacy_score: Mapping[str, Any] | None,
    critic_verdict: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare overlapping scoring dimensions without changing any gate.

    Disagreement bands are diagnostic labels, not scientific thresholds:
    - LOW: judges are broadly within ~1 point;
    - MODERATE: material disagreement worth human inspection;
    - SEVERE: at least one mapped dimension differs by ~3 points or the average
      mapped difference is very large.

    The raw mapped deltas are retained so future promotion decisions can change
    these labels without losing evidence.
    """
    legacy = dict(legacy_score or {})
    critic_scores = dict((critic_verdict or {}).get("scores") or {})
    mapped: dict[str, dict[str, float]] = {}
    abs_deltas: list[float] = []

    for legacy_name, critic_name in MAPPED_DIMENSIONS.items():
        lv = _number(legacy.get(legacy_name))
        cv = _number(critic_scores.get(critic_name))
        if lv is None or cv is None:
            continue
        delta = cv - lv
        mapped[legacy_name] = {
            "legacy": round(lv, 3),
            "critic": round(cv, 3),
            "critic_minus_legacy": round(delta, 3),
            "abs_delta": round(abs(delta), 3),
        }
        abs_deltas.append(abs(delta))

    critic_craft_values = [
        v for name in CRITIC_CRAFT_DIMENSIONS
        if (v := _number(critic_scores.get(name))) is not None
    ]
    legacy_overall = _number(legacy.get("overall"))
    critic_craft_avg = _mean(critic_craft_values)
    mean_abs = _mean(abs_deltas)
    max_abs = max(abs_deltas) if abs_deltas else None

    if mean_abs is None or max_abs is None:
        band = "UNAVAILABLE"
    elif max_abs >= 3.0 or mean_abs >= 1.75:
        band = "SEVERE"
    elif max_abs >= 2.0 or mean_abs >= 1.0:
        band = "MODERATE"
    else:
        band = "LOW"

    low_critic_dimensions = sorted(
        name for name in CRITIC_CRAFT_DIMENSIONS
        if (v := _number(critic_scores.get(name))) is not None and v < 6.0
    )

    return {
        "available": bool(mapped),
        "legacy_overall": round(legacy_overall, 3) if legacy_overall is not None else None,
        "critic_craft_avg": round(critic_craft_avg, 3) if critic_craft_avg is not None else None,
        "mapped_dimensions": mapped,
        "mean_abs_mapped_delta": round(mean_abs, 3) if mean_abs is not None else None,
        "max_abs_mapped_delta": round(max_abs, 3) if max_abs is not None else None,
        "disagreement_band": band,
        "critic_dimensions_below_6": low_critic_dimensions,
        "gating": False,
    }


def selection_signal_report(candidates: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Report whether the legacy-score winner and critic-craft winner disagree.

    Only candidates already eligible under factual/validate/quality-floor gates
    participate. This does NOT choose a winner; it exposes whether the current
    selection rule would benefit from a future robustness change.
    """
    eligible: list[Mapping[str, Any]] = []
    for c in candidates or []:
        if c.get("hard_violations") or c.get("validate_err"):
            continue
        score = _number(c.get("score"))
        critic = _number(c.get("critic_avg"))
        if score is None or critic is None:
            continue
        eligible.append(c)

    if not eligible:
        return {
            "available": False,
            "eligible_candidate_count": 0,
            "winner_disagreement": False,
            "gating": False,
        }

    # Ties preserve chronology, matching Writer V2.1's current selection intent.
    legacy_winner = max(eligible, key=lambda c: (_number(c.get("score")) or -999, -int(c.get("round", 0))))
    critic_winner = max(eligible, key=lambda c: (_number(c.get("critic_avg")) or -999, -int(c.get("round", 0))))
    disagreement = legacy_winner is not critic_winner

    return {
        "available": True,
        "eligible_candidate_count": len(eligible),
        "legacy_winner_round": int(legacy_winner.get("round", 0)),
        "legacy_winner_score": round(_number(legacy_winner.get("score")) or 0.0, 3),
        "critic_winner_round": int(critic_winner.get("round", 0)),
        "critic_winner_avg": round(_number(critic_winner.get("critic_avg")) or 0.0, 3),
        "winner_disagreement": disagreement,
        "legacy_winner_critic_avg": round(_number(legacy_winner.get("critic_avg")) or 0.0, 3),
        "critic_winner_legacy_score": round(_number(critic_winner.get("score")) or 0.0, 3),
        "gating": False,
    }
