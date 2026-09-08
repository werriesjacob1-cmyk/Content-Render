"""Zero-network promotion protocol for Writer V2.1 quality bakeoffs.

This module never calls providers, renders, publishes, or mutates production state.
It freezes a diverse topic panel, blinds paired scripts, validates editorial
verdicts, and applies pre-registered promotion criteria.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

CRITERIA = (
    "opening_pull",
    "spoken_naturalness",
    "information_gain",
    "escalation",
    "payoff",
    "low_ai_smell",
    "visual_tellability",
)
CRITICAL_CRITERIA = ("opening_pull", "spoken_naturalness", "payoff")
SIDES = ("legacy", "v21")

DEFAULT_PROTOCOL: dict[str, Any] = {
    "protocol_version": "writer-v21-quality-proof-v1",
    "stage1_topics": 12,
    "stage2_topics": 20,
    "min_comparable_pairs": 10,
    "min_decisive_pairs": 8,
    "min_v21_editorial_win_share": 0.65,
    "max_one_sided_sign_test_p": 0.10,
    "min_v21_postable_rate": 0.70,
    "max_v21_integrity_failures": 0,
    "min_v21_generation_success_rate": 0.70,
    "max_v21_success_rate_drop_vs_legacy": 0.20,
    "min_distinct_v21_treatments": 5,
    "max_single_treatment_share": 0.40,
    "max_repair_regression_topic_share": 0.25,
    "same_draft_model_min_pairs_for_guardrail": 6,
    "same_draft_model_min_v21_win_share": 0.50,
}


class BakeoffProtocolError(ValueError):
    pass


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _script(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return "\n".join(_clean(line) for line in text.split("\n") if _clean(line))


def stable_hash(*parts: Any) -> str:
    return hashlib.sha256("\x1f".join(str(x) for x in parts).encode("utf-8")).hexdigest()


def select_topic_panel(
    facts: Sequence[Mapping[str, Any]], *, count: int = 12,
    seed: str = "writer-v21-quality-proof-v1",
    treatment_by_id: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Deterministic domain-first, treatment-balanced selection; no quality peeking."""
    if count < 2:
        raise BakeoffProtocolError("topic panel requires at least two topics")
    by_domain: dict[str, list[Mapping[str, Any]]] = {}
    seen: set[str] = set()
    for fact in facts:
        fid = str((fact or {}).get("id") or "").strip()
        domain = str((fact or {}).get("domain") or "unknown").strip() or "unknown"
        if not fid or not _clean((fact or {}).get("fact")) or fid in seen:
            continue
        seen.add(fid)
        by_domain.setdefault(domain, []).append(fact)
    if sum(map(len, by_domain.values())) < count:
        raise BakeoffProtocolError("not enough eligible facts for requested panel")
    for domain, rows in by_domain.items():
        rows.sort(key=lambda r: stable_hash(seed, domain, r.get("id")))
    domains = sorted(by_domain, key=lambda d: stable_hash(seed, "domain", d))
    remaining = {d: list(rows) for d, rows in by_domain.items()}
    tcounts: dict[str, int] = {}
    out: list[dict[str, str]] = []
    while len(out) < count:
        advanced = False
        for domain in domains:
            rows = remaining[domain]
            if not rows:
                continue
            if treatment_by_id:
                row = min(rows, key=lambda r: (
                    tcounts.get(str(treatment_by_id.get(str(r.get("id"))) or ""), 0),
                    stable_hash(seed, domain, r.get("id")),
                ))
                rows.remove(row)
            else:
                row = rows.pop(0)
            fid = str(row.get("id"))
            tr = str((treatment_by_id or {}).get(fid) or "")
            if tr:
                tcounts[tr] = tcounts.get(tr, 0) + 1
            picked = {"topic_id": fid, "domain": domain, "fact": _clean(row.get("fact"))}
            if tr:
                picked["planned_treatment"] = tr
            out.append(picked)
            advanced = True
            if len(out) == count:
                break
        if not advanced:
            break
    if len(out) != count:
        raise BakeoffProtocolError("panel selection exhausted unexpectedly")
    return out


def normalize_result(raw: Mapping[str, Any]) -> dict[str, Any]:
    side = str(raw.get("side") or "").lower().strip()
    topic = str(raw.get("topic_id") or raw.get("topic") or "").strip()
    if side not in SIDES or not topic:
        raise BakeoffProtocolError("generation result requires topic_id and side=legacy|v21")
    integrity = raw.get("integrity_clean") if isinstance(raw.get("integrity_clean"), bool) else None
    semantic = raw.get("semantic_verified") if isinstance(raw.get("semantic_verified"), bool) else None
    return {
        "topic_id": topic,
        "side": side,
        "script": _script(raw.get("script")),
        "generated": bool(raw.get("generated", bool(raw.get("script")))),
        "validate_clean": bool(raw.get("validate_clean", raw.get("validate_err") in (None, ""))),
        "integrity_clean": integrity,
        "semantic_verified": semantic,
        "treatment": str(raw.get("treatment") or "").strip(),
        "draft_provider_model": str(raw.get("draft_provider_model") or "").strip(),
        "calls": int(raw.get("calls") or 0),
        "repair_regression_flags": sorted({str(x) for x in (raw.get("repair_regression_flags") or []) if str(x)}),
        "error": str(raw.get("error") or "").strip(),
    }


def comparable(row: Mapping[str, Any]) -> bool:
    return bool(row.get("generated") and row.get("validate_clean") and _script(row.get("script")))


def _assert_blind(packet: Mapping[str, Any]) -> None:
    forbidden_keys = {
        "side", "system", "treatment", "provider", "provider_model",
        "draft_provider_model", "repair_round", "candidate_id", "answer_key", "aliases",
    }
    def walk(value: Any, path: str = "") -> list[str]:
        leaks: list[str] = []
        if isinstance(value, Mapping):
            for k, v in value.items():
                key = str(k).lower()
                if key in forbidden_keys:
                    leaks.append(path + key)
                if key not in {"candidate_a", "candidate_b"}:
                    leaks.extend(walk(v, path + key + "."))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                leaks.extend(walk(v, path + f"{i}."))
        elif isinstance(value, str) and value.lower() in {"legacy", "v21", "writer v2.1", "writer_v2"}:
            leaks.append(path.rstrip("."))
        return leaks
    leaks = walk(packet)
    if leaks:
        raise BakeoffProtocolError(f"blind packet leaks hidden identity: {leaks}")


def build_blind_packets(
    results: Sequence[Mapping[str, Any]], *, seed: str = "writer-v21-quality-proof-v1",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_topic: dict[str, dict[str, dict[str, Any]]] = {}
    for raw in results:
        row = normalize_result(raw)
        slot = by_topic.setdefault(row["topic_id"], {})
        if row["side"] in slot:
            raise BakeoffProtocolError(f"duplicate {row['side']} result for {row['topic_id']}")
        slot[row["side"]] = row
    packets: list[dict[str, Any]] = []
    keys: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for topic in sorted(by_topic):
        slot = by_topic[topic]
        legacy, v21 = slot.get("legacy"), slot.get("v21")
        if not legacy or not v21:
            excluded.append({"topic_id": topic, "reason": "missing_side"})
            continue
        if not comparable(legacy) or not comparable(v21):
            excluded.append({
                "topic_id": topic, "reason": "candidate_not_comparable",
                "legacy_generated": legacy["generated"], "legacy_validate_clean": legacy["validate_clean"],
                "v21_generated": v21["generated"], "v21_validate_clean": v21["validate_clean"],
            })
            continue
        h = stable_hash(seed, topic, legacy["script"], v21["script"])
        first = "legacy" if int(h[:2], 16) % 2 == 0 else "v21"
        second = "v21" if first == "legacy" else "legacy"
        pair_id = "pair_" + h[:16]
        packet = {
            "pair_id": pair_id,
            "candidate_A": slot[first]["script"],
            "candidate_B": slot[second]["script"],
            "criteria": list(CRITERIA),
            "judge_instruction": "Judge human-facing short-form quality only; do not infer which candidate is newer.",
        }
        _assert_blind(packet)
        packets.append(packet)
        keys.append({
            "pair_id": pair_id, "topic_id": topic, "aliases": {"A": first, "B": second},
            "same_draft_model": bool(
                legacy["draft_provider_model"] and
                legacy["draft_provider_model"] == v21["draft_provider_model"]
            ),
        })
    return packets, keys, excluded


def build_judge_prompt(packet: Mapping[str, Any]) -> str:
    _assert_blind(packet)
    return f"""You are a ruthless short-form science editor. Compare two ANONYMOUS spoken scripts about the same topic. Do not fact-check here; integrity is audited separately. Judge what would hold a cold viewer better while sounding like a smart human speaking naturally.

CANDIDATE A:\n{packet['candidate_A']}\n\nCANDIDATE B:\n{packet['candidate_B']}

Criteria: {', '.join(CRITERIA)}. Opening_pull is the first 1-1.5 seconds. Information_gain means each beat adds something new. Low_ai_smell rewards language that is not templated, formal, hedged, generic, or try-hard. Visual_tellability rewards concrete mechanisms/objects/actions footage can show. Use TIE if the difference is trivial.

Return ONLY JSON:\n{{"pair_id":"{packet['pair_id']}","winner":"A|B|TIE","confidence":"LOW|MEDIUM|HIGH","criterion_winners":{{"opening_pull":"A|B|TIE","spoken_naturalness":"A|B|TIE","information_gain":"A|B|TIE","escalation":"A|B|TIE","payoff":"A|B|TIE","low_ai_smell":"A|B|TIE","visual_tellability":"A|B|TIE"}},"postable_A":true,"postable_B":true,"decisive_reasons":["..."]}}"""


def parse_verdict(raw: Mapping[str, Any] | str) -> dict[str, Any]:
    try:
        d = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception as exc:
        raise BakeoffProtocolError("verdict is not valid JSON") from exc
    if not str(d.get("pair_id") or ""):
        raise BakeoffProtocolError("verdict missing pair_id")
    winner, confidence = str(d.get("winner") or "").upper(), str(d.get("confidence") or "").upper()
    if winner not in {"A", "B", "TIE"} or confidence not in {"LOW", "MEDIUM", "HIGH"}:
        raise BakeoffProtocolError("invalid winner/confidence")
    cw = d.get("criterion_winners")
    if not isinstance(cw, Mapping) or set(cw) != set(CRITERIA):
        raise BakeoffProtocolError("criterion_winners must cover exact criteria")
    normalized = {c: str(cw[c]).upper() for c in CRITERIA}
    if any(v not in {"A", "B", "TIE"} for v in normalized.values()):
        raise BakeoffProtocolError("invalid criterion winner")
    if not isinstance(d.get("postable_A"), bool) or not isinstance(d.get("postable_B"), bool):
        raise BakeoffProtocolError("postable_A/postable_B must be booleans")
    reasons = d.get("decisive_reasons") or []
    if not isinstance(reasons, list) or (winner != "TIE" and not reasons):
        raise BakeoffProtocolError("non-tie verdict requires decisive_reasons")
    return {
        "pair_id": str(d["pair_id"]), "winner": winner, "confidence": confidence,
        "criterion_winners": normalized, "postable_A": d["postable_A"],
        "postable_B": d["postable_B"], "decisive_reasons": [_clean(x) for x in reasons if _clean(x)][:5],
    }


def map_verdict(verdict: Mapping[str, Any] | str, key: Mapping[str, Any]) -> dict[str, Any]:
    d = parse_verdict(verdict)
    if d["pair_id"] != key.get("pair_id"):
        raise BakeoffProtocolError("verdict/key pair_id mismatch")
    aliases = key.get("aliases") or {}
    if set(aliases) != {"A", "B"} or set(aliases.values()) != set(SIDES):
        raise BakeoffProtocolError("malformed private aliases")
    map_alias = lambda a: None if a == "TIE" else aliases[a]
    return {
        "pair_id": d["pair_id"], "topic_id": str(key.get("topic_id") or ""),
        "winner_side": map_alias(d["winner"]), "confidence": d["confidence"],
        "criterion_winner_sides": {c: map_alias(a) for c, a in d["criterion_winners"].items()},
        "postable_by_side": {aliases["A"]: d["postable_A"], aliases["B"]: d["postable_B"]},
        "same_draft_model": bool(key.get("same_draft_model")),
        "decisive_reasons": d["decisive_reasons"],
    }


def one_sided_sign_test_p(wins: int, losses: int) -> float:
    if wins < 0 or losses < 0:
        raise BakeoffProtocolError("negative win/loss count")
    n = wins + losses
    return 1.0 if not n else sum(math.comb(n, k) for k in range(wins, n + 1)) / (2 ** n)


def _rate(a: int, b: int) -> float:
    return a / b if b else 0.0


def aggregate_promotion(
    mapped: Sequence[Mapping[str, Any]], generation_results: Sequence[Mapping[str, Any]],
    *, protocol: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = {**DEFAULT_PROTOCOL, **dict(protocol or {})}
    rows = [normalize_result(r) for r in generation_results]
    legacy = [r for r in rows if r["side"] == "legacy"]
    v21 = [r for r in rows if r["side"] == "v21"]
    if not legacy or not v21:
        raise BakeoffProtocolError("both systems are required")
    wins = sum(v.get("winner_side") == "v21" for v in mapped)
    losses = sum(v.get("winner_side") == "legacy" for v in mapped)
    ties = sum(v.get("winner_side") is None for v in mapped)
    decisive, comparable_pairs = wins + losses, len(mapped)
    win_share, sign_p = _rate(wins, decisive), one_sided_sign_test_p(wins, losses)
    cc = {c: {"v21": 0, "legacy": 0, "tie": 0} for c in CRITERIA}
    for v in mapped:
        for c, side in (v.get("criterion_winner_sides") or {}).items():
            if c in cc:
                cc[c]["tie" if side is None else side] += 1
    post_v = sum((v.get("postable_by_side") or {}).get("v21") is True for v in mapped)
    post_l = sum((v.get("postable_by_side") or {}).get("legacy") is True for v in mapped)
    success = lambda rs: _rate(sum(comparable(r) for r in rs), len(rs))
    legacy_success, v21_success = success(legacy), success(v21)
    integrity_failures = sum(
        r["generated"] and (r["integrity_clean"] is not True or r["semantic_verified"] is not True)
        for r in v21
    )
    valid_v21 = [r for r in v21 if comparable(r)]
    treatments = [r["treatment"] for r in valid_v21 if r["treatment"]]
    tcounts = {t: treatments.count(t) for t in sorted(set(treatments))}
    max_tshare = _rate(max(tcounts.values()) if tcounts else 0, len(treatments))
    repair_topics = sum(bool(r["repair_regression_flags"]) for r in valid_v21)
    repair_share = _rate(repair_topics, len(valid_v21))
    same = [v for v in mapped if v.get("same_draft_model")]
    same_w = sum(v.get("winner_side") == "v21" for v in same)
    same_l = sum(v.get("winner_side") == "legacy" for v in same)
    same_share = _rate(same_w, same_w + same_l)

    checks: list[dict[str, Any]] = []
    def add(name: str, ok: bool, observed: Any, required: str, hard: bool = True) -> None:
        checks.append({"name": name, "passed": bool(ok), "observed": observed, "required": required, "hard": hard})
    add("comparable_pairs", comparable_pairs >= cfg["min_comparable_pairs"], comparable_pairs, f">={cfg['min_comparable_pairs']}")
    add("decisive_pairs", decisive >= cfg["min_decisive_pairs"], decisive, f">={cfg['min_decisive_pairs']}")
    add("v21_editorial_win_share", win_share >= cfg["min_v21_editorial_win_share"], win_share, f">={cfg['min_v21_editorial_win_share']}")
    add("one_sided_sign_test", sign_p <= cfg["max_one_sided_sign_test_p"], sign_p, f"<={cfg['max_one_sided_sign_test_p']}")
    add("v21_postable_rate", _rate(post_v, comparable_pairs) >= cfg["min_v21_postable_rate"], _rate(post_v, comparable_pairs), f">={cfg['min_v21_postable_rate']}")
    add("v21_integrity_failures", integrity_failures <= cfg["max_v21_integrity_failures"], integrity_failures, f"<={cfg['max_v21_integrity_failures']}")
    add("v21_generation_success_rate", v21_success >= cfg["min_v21_generation_success_rate"], v21_success, f">={cfg['min_v21_generation_success_rate']}")
    add("v21_success_rate_drop", legacy_success - v21_success <= cfg["max_v21_success_rate_drop_vs_legacy"], legacy_success - v21_success, f"<={cfg['max_v21_success_rate_drop_vs_legacy']}")
    add("v21_treatment_diversity", len(tcounts) >= cfg["min_distinct_v21_treatments"], len(tcounts), f">={cfg['min_distinct_v21_treatments']}")
    add("v21_treatment_concentration", max_tshare <= cfg["max_single_treatment_share"], max_tshare, f"<={cfg['max_single_treatment_share']}")
    add("v21_repair_regression_topic_share", repair_share <= cfg["max_repair_regression_topic_share"], repair_share, f"<={cfg['max_repair_regression_topic_share']}")
    for c in CRITICAL_CRITERIA:
        add(f"criterion_{c}_net", cc[c]["v21"] >= cc[c]["legacy"], cc[c]["v21"] - cc[c]["legacy"], ">=0")
    if len(same) >= cfg["same_draft_model_min_pairs_for_guardrail"]:
        add("same_draft_model_guardrail", same_share >= cfg["same_draft_model_min_v21_win_share"], same_share, f">={cfg['same_draft_model_min_v21_win_share']}")
    else:
        add("same_draft_model_guardrail", True, {"pairs": len(same), "status": "INSUFFICIENT"}, "informational", False)

    hard_fail = [x for x in checks if x["hard"] and not x["passed"]]
    sample_short = comparable_pairs < cfg["min_comparable_pairs"] or decisive < cfg["min_decisive_pairs"]
    integrity_block = any(x["name"] == "v21_integrity_failures" and not x["passed"] for x in checks)
    verdict = (
        "PROMOTION_READY_FOR_HUMAN_AUTHORIZATION" if not hard_fail else
        "EXPAND_SAMPLE" if sample_short and not integrity_block else
        "NOT_PROMOTION_READY"
    )
    return {
        "protocol_version": cfg["protocol_version"], "verdict": verdict,
        "topics_observed": len({r["topic_id"] for r in rows}), "comparable_pairs": comparable_pairs,
        "wins": {"v21": wins, "legacy": losses, "ties": ties}, "decisive_pairs": decisive,
        "v21_editorial_win_share": win_share, "one_sided_sign_test_p": sign_p,
        "postable_rate": {"v21": _rate(post_v, comparable_pairs), "legacy": _rate(post_l, comparable_pairs)},
        "generation_success_rate": {"v21": v21_success, "legacy": legacy_success},
        "v21_integrity_failures": integrity_failures, "criterion_counts": cc,
        "treatment_counts": tcounts, "max_single_treatment_share": max_tshare,
        "repair_regression": {"topics_with_flags": repair_topics, "topic_share": repair_share},
        "same_draft_model": {"pairs": len(same), "v21_wins": same_w, "legacy_wins": same_l, "v21_decisive_win_share": same_share},
        "checks": checks,
    }
