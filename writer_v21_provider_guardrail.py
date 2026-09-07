"""Provider/model comparability guardrail for Writer V2.1 quality proof.

The system-level bakeoff intentionally records real provider-routing behavior, but
promotion must not be attributable merely to one side receiving a stronger draft
model. This zero-network layer requires a sufficiently large factually-clean subset
where BOTH systems' initial drafts used the exact same provider/model identity.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import writer_v21_quality_bakeoff as Q

DEFAULTS: dict[str, Any] = {
    "min_same_draft_model_pairs": 8,
    "min_same_draft_model_decisive_pairs": 6,
    "min_same_draft_model_v21_win_share": 0.65,
    "max_same_draft_model_sign_test_p": 0.20,
}


def _rate(a: int, b: int) -> float:
    return a / b if b else 0.0


def apply_provider_guardrail(
    report: Mapping[str, Any],
    editorial_mapped: Sequence[Mapping[str, Any]],
    *, protocol: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of report with a hard causal provider/model guardrail applied."""
    cfg = {**DEFAULTS, **dict(protocol or {})}
    out = dict(report)
    out["checks"] = [dict(x) for x in (report.get("checks") or [])]

    excluded = {
        str(x.get("pair_id") or "")
        for x in ((report.get("external_factual_audit") or {}).get("excluded_pairs") or [])
        if isinstance(x, Mapping)
    }
    factually_clean = [x for x in editorial_mapped if str(x.get("pair_id") or "") not in excluded]
    same = [x for x in factually_clean if x.get("same_draft_model") is True]
    wins = sum(x.get("winner_side") == "v21" for x in same)
    losses = sum(x.get("winner_side") == "legacy" for x in same)
    ties = sum(x.get("winner_side") is None for x in same)
    decisive = wins + losses
    win_share = _rate(wins, decisive)
    sign_p = Q.one_sided_sign_test_p(wins, losses)

    critical: dict[str, dict[str, int]] = {}
    critical_regression = False
    for criterion in Q.CRITICAL_CRITERIA:
        v = sum((row.get("criterion_winner_sides") or {}).get(criterion) == "v21" for row in same)
        l = sum((row.get("criterion_winner_sides") or {}).get(criterion) == "legacy" for row in same)
        t = sum((row.get("criterion_winner_sides") or {}).get(criterion) is None for row in same)
        critical[criterion] = {"v21": v, "legacy": l, "ties": t, "net": v - l}
        critical_regression = critical_regression or l > v

    enough_pairs = len(same) >= int(cfg["min_same_draft_model_pairs"])
    enough_decisive = decisive >= int(cfg["min_same_draft_model_decisive_pairs"])
    share_ok = win_share >= float(cfg["min_same_draft_model_v21_win_share"])
    sign_ok = sign_p <= float(cfg["max_same_draft_model_sign_test_p"])

    def add(name: str, passed: bool, observed: Any, required: str) -> None:
        out["checks"].append({
            "name": name,
            "passed": bool(passed),
            "observed": observed,
            "required": required,
            "hard": True,
        })

    add("same_draft_model_pairs", enough_pairs, len(same), f">={cfg['min_same_draft_model_pairs']}")
    add("same_draft_model_decisive_pairs", enough_decisive, decisive, f">={cfg['min_same_draft_model_decisive_pairs']}")
    add("same_draft_model_v21_win_share", share_ok, win_share, f">={cfg['min_same_draft_model_v21_win_share']}")
    add("same_draft_model_sign_test", sign_ok, sign_p, f"<={cfg['max_same_draft_model_sign_test_p']}")
    for criterion, counts in critical.items():
        add(f"same_draft_model_criterion_{criterion}_net", counts["net"] >= 0, counts["net"], ">=0")

    out["causal_provider_guardrail"] = {
        "factually_clean_editorial_pairs": len(factually_clean),
        "same_draft_model_pairs": len(same),
        "provider_mismatched_pairs": len(factually_clean) - len(same),
        "wins": {"v21": wins, "legacy": losses, "ties": ties},
        "decisive_pairs": decisive,
        "v21_decisive_win_share": win_share,
        "one_sided_sign_test_p": sign_p,
        "critical_criteria": critical,
    }

    sample_short = not enough_pairs or not enough_decisive
    causal_quality_fail = (not sample_short) and (not share_ok or not sign_ok or critical_regression)
    if causal_quality_fail:
        out["verdict"] = "NOT_PROMOTION_READY"
    elif sample_short and out.get("verdict") == "PROMOTION_READY_FOR_HUMAN_AUTHORIZATION":
        out["verdict"] = "EXPAND_SAMPLE"
    return out
