"""Round-to-round repair regression telemetry for Writer V2.1.

A repair can be factually correct and still make the content worse: a sharp hook
can become hedged/clinical, a specific payoff can turn into a generic moral, or a
short beat can balloon into written prose. This module compares consecutive V2.1
rounds and records those regressions WITHOUT altering selection.

The diagnostics are intentionally conservative and transparent. They preserve
before/after lines and raw score/critic/editorial deltas so a human can decide
whether a future selection-policy change is justified by evidence.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import writer_v21_editorial_diagnostics as E
import writer_v21_quality_signals as Q


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _word_count(value: Any) -> int:
    return len(_text(value).split())


def _round_lines(round_info: Mapping[str, Any]) -> list[str]:
    return [
        _text(round_info.get("hook")),
        *[_text(x) for x in (round_info.get("beats") or [])],
        _text(round_info.get("payoff")),
    ]


def _scenes_from_round(round_info: Mapping[str, Any]) -> list[dict[str, Any]]:
    # V2 debug currently retains voiceover text, not each scene's visual_intent.
    # Keep this hook for future richer debug; don't fabricate visual diagnostics.
    visuals = round_info.get("visual_intents") or []
    return [{"visual_intent": x} for x in visuals]


def _editorial(round_info: Mapping[str, Any]) -> dict[str, Any]:
    return E.editorial_diagnostics(
        hook=_text(round_info.get("hook")),
        beats=[_text(x) for x in (round_info.get("beats") or [])],
        payoff=_text(round_info.get("payoff")),
        scenes=_scenes_from_round(round_info),
    )


def _quality(round_info: Mapping[str, Any]) -> dict[str, Any]:
    return Q.quality_signal_report(round_info.get("score"), round_info.get("critic_verdict"))


def _warning_count(editorial: Mapping[str, Any], kind: str) -> int:
    return sum(1 for w in (editorial.get("warnings") or []) if w.get("kind") == kind)


def _targeted_indices(previous_round: Mapping[str, Any], line_count: int) -> list[int]:
    plan = previous_round.get("repair_plan") or {}
    targets: list[int] = []
    for raw in plan.get("target_beats") or []:
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < line_count and idx not in targets:
            targets.append(idx)
    return sorted(targets)


def compare_rounds(
    previous_round: Mapping[str, Any],
    current_round: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare one repair transition. Pure telemetry; never gating."""
    before = _round_lines(previous_round)
    after = _round_lines(current_round)
    max_len = max(len(before), len(after))
    before += [""] * (max_len - len(before))
    after += [""] * (max_len - len(after))

    targeted = _targeted_indices(previous_round, max_len)
    changed = [i for i in range(max_len) if before[i] != after[i]]
    unexpected = [i for i in changed if targeted and i not in targeted]

    line_changes: list[dict[str, Any]] = []
    for idx in changed:
        bw = _word_count(before[idx])
        aw = _word_count(after[idx])
        line_changes.append({
            "beat_index": idx,
            "targeted": idx in targeted,
            "before": before[idx],
            "after": after[idx],
            "before_words": bw,
            "after_words": aw,
            "word_delta": aw - bw,
        })

    before_editorial = _editorial(previous_round)
    after_editorial = _editorial(current_round)
    before_quality = _quality(previous_round)
    after_quality = _quality(current_round)

    flags: list[dict[str, Any]] = []

    # The hook/payoff are the most expensive lines to bloat. +5 words or >=40%
    # expansion is visible telemetry, not an arbitrary failure threshold.
    for endpoint_idx, role in ((0, "hook"), (max_len - 1, "payoff")):
        if endpoint_idx >= len(before) or not before[endpoint_idx] or not after[endpoint_idx]:
            continue
        bw = _word_count(before[endpoint_idx])
        aw = _word_count(after[endpoint_idx])
        if aw > bw and ((aw - bw) >= 5 or aw >= max(1, int(bw * 1.4))):
            flags.append({
                "kind": f"{role}_inflation",
                "beat_index": endpoint_idx,
                "before_words": bw,
                "after_words": aw,
                "detail": f"{role} grew materially after repair",
            })

    for kind in (
        "generic_ai_moralizing",
        "low_information_gain",
        "adjacent_repetition",
        "payoff_restates_hook",
        "spoken_sentence_too_long",
        "monotone_sentence_rhythm",
    ):
        before_count = _warning_count(before_editorial, kind)
        after_count = _warning_count(after_editorial, kind)
        if after_count > before_count:
            flags.append({
                "kind": f"new_editorial_{kind}",
                "beat_index": None,
                "before_count": before_count,
                "after_count": after_count,
                "detail": f"repair introduced more {kind} warnings",
            })

    bcrit = before_quality.get("critic_craft_avg")
    acrit = after_quality.get("critic_craft_avg")
    if isinstance(bcrit, (int, float)) and isinstance(acrit, (int, float)) and acrit < bcrit - 0.75:
        flags.append({
            "kind": "critic_craft_drop",
            "beat_index": None,
            "before": bcrit,
            "after": acrit,
            "delta": round(acrit - bcrit, 3),
            "detail": "independent critic craft average dropped materially after repair",
        })

    boverall = before_quality.get("legacy_overall")
    aoverall = after_quality.get("legacy_overall")
    if isinstance(boverall, (int, float)) and isinstance(aoverall, (int, float)) and aoverall < boverall - 0.75:
        flags.append({
            "kind": "legacy_score_drop",
            "beat_index": None,
            "before": boverall,
            "after": aoverall,
            "delta": round(aoverall - boverall, 3),
            "detail": "legacy quality self-score dropped materially after repair",
        })

    before_band = before_quality.get("disagreement_band")
    after_band = after_quality.get("disagreement_band")
    order = {"UNAVAILABLE": -1, "LOW": 0, "MODERATE": 1, "SEVERE": 2}
    if order.get(str(after_band), -1) > order.get(str(before_band), -1):
        flags.append({
            "kind": "judge_disagreement_worsened",
            "beat_index": None,
            "before": before_band,
            "after": after_band,
            "detail": "legacy scorer and independent critic disagree more after repair",
        })

    if unexpected:
        flags.append({
            "kind": "untargeted_text_changed",
            "beat_index": None,
            "indices": unexpected,
            "detail": "repair changed line(s) outside the declared targeted beat set",
        })

    return {
        "from_round": int(previous_round.get("round", 0)),
        "to_round": int(current_round.get("round", 0)),
        "repair_type": (previous_round.get("repair_plan") or {}).get("repair_type"),
        "targeted_indices": targeted,
        "changed_indices": changed,
        "unexpected_changed_indices": unexpected,
        "line_changes": line_changes,
        "before_quality": before_quality,
        "after_quality": after_quality,
        "before_editorial_warning_kinds": before_editorial.get("warning_kinds") or [],
        "after_editorial_warning_kinds": after_editorial.get("warning_kinds") or [],
        "regression_flags": flags,
        "regression_flag_kinds": sorted({f["kind"] for f in flags}),
        "gating": False,
    }


def analyze_debug(debug: Mapping[str, Any] | None) -> dict[str, Any]:
    """Analyze every consecutive round transition in one candidate run."""
    rounds = list((debug or {}).get("rounds") or [])
    transitions = [compare_rounds(rounds[i - 1], rounds[i]) for i in range(1, len(rounds))]
    return {
        "transitions": transitions,
        "transitions_with_regression_flags": [
            t["to_round"] for t in transitions if t.get("regression_flags")
        ],
        "all_regression_flag_kinds": sorted({
            kind
            for t in transitions
            for kind in (t.get("regression_flag_kinds") or [])
        }),
        "gating": False,
    }
