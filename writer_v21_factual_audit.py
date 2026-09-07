"""Identity-blind, source-bounded factual audit for Writer V2.1 bakeoffs.

This module is deliberately zero-network. It creates a second anonymous judging
surface, separate from editorial quality, so a candidate cannot win by being more
sensational because it invented a claim. Both systems are judged against the same
sealed source packet.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

import writer_v21_quality_bakeoff as Q

FACT_STATUSES = ("CLEAN", "UNSUPPORTED", "UNKNOWN")


class FactualAuditError(Q.BakeoffProtocolError):
    pass


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def evidence_sha256(evidence: Sequence[str]) -> str:
    normalized = [_clean(x) for x in evidence if _clean(x)]
    raw = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_source_evidence(fact: Mapping[str, Any], dossier: Sequence[Any]) -> list[str]:
    """Build factual support only; query/planning metadata is intentionally excluded."""
    out: list[str] = []
    fields = (
        ("BASE_FACT", "fact"),
        ("WOW", "wow"),
        ("ANGLE", "angle"),
        ("WHAT_IF", "whatif"),
        ("WHAT_IF", "what_if"),
    )
    seen: set[str] = set()
    for label, key in fields:
        value = _clean(fact.get(key))
        item = f"{label}: {value}" if value else ""
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    for raw in dossier:
        value = _clean(raw)
        item = f"DOSSIER: {value}" if value else ""
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    if not out:
        raise FactualAuditError("source evidence is empty")
    return out


def _result_lookup(results: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    out: dict[tuple[str, str], Mapping[str, Any]] = {}
    for raw in results:
        row = Q.normalize_result(raw)
        key = (row["topic_id"], row["side"])
        if key in out:
            raise FactualAuditError(f"duplicate generation row {key[0]}/{key[1]}")
        out[key] = raw
    return out


def _verified_evidence(raw: Mapping[str, Any]) -> tuple[list[str], str]:
    evidence = raw.get("source_evidence")
    if not isinstance(evidence, list) or not evidence or any(not isinstance(x, str) or not _clean(x) for x in evidence):
        raise FactualAuditError("generation row missing non-empty source_evidence[]")
    normalized = [_clean(x) for x in evidence]
    claimed = str(raw.get("source_evidence_sha256") or "")
    actual = evidence_sha256(normalized)
    if not claimed or claimed != actual:
        raise FactualAuditError("source evidence hash missing or mismatched")
    return normalized, actual


def _assert_blind(packet: Mapping[str, Any]) -> None:
    forbidden_keys = {
        "side", "system", "treatment", "provider", "provider_model",
        "draft_provider_model", "answer_key", "aliases", "winner_side",
    }
    leaks: list[str] = []

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                low = str(key).lower()
                if low in forbidden_keys:
                    leaks.append(path + low)
                walk(child, path + low + ".")
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, path + f"{i}.")
        elif isinstance(value, str) and value.lower() in {"legacy", "v21", "writer v2.1", "writer_v2"}:
            leaks.append(path.rstrip("."))

    walk(packet)
    if leaks:
        raise FactualAuditError(f"factual packet leaks hidden identity: {leaks}")


def build_factual_packets(
    results: Sequence[Mapping[str, Any]], keys: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    lookup = _result_lookup(results)
    packets: list[dict[str, Any]] = []
    for key in keys:
        pair_id = str(key.get("pair_id") or "")
        topic = str(key.get("topic_id") or "")
        aliases = key.get("aliases") or {}
        if not pair_id or not topic or set(aliases) != {"A", "B"} or set(aliases.values()) != set(Q.SIDES):
            raise FactualAuditError("malformed private key while building factual packets")
        raw_a = lookup.get((topic, aliases["A"]))
        raw_b = lookup.get((topic, aliases["B"]))
        if raw_a is None or raw_b is None:
            raise FactualAuditError(f"missing generation evidence for factual pair {pair_id}")
        ev_a, sha_a = _verified_evidence(raw_a)
        ev_b, sha_b = _verified_evidence(raw_b)
        if sha_a != sha_b or ev_a != ev_b:
            raise FactualAuditError(f"paired candidates do not share identical source evidence for {pair_id}")
        script_a = Q._script(raw_a.get("script"))
        script_b = Q._script(raw_b.get("script"))
        if not script_a or not script_b:
            raise FactualAuditError(f"factual packet requires two non-empty scripts for {pair_id}")
        packet = {
            "pair_id": pair_id,
            "source_evidence_sha256": sha_a,
            "source_evidence": ev_a,
            "candidate_A": script_a,
            "candidate_B": script_b,
            "audit_instruction": (
                "Audit factual propositions only against the supplied source evidence. "
                "Connective/editorial phrasing is allowed; do not reward or penalize style."
            ),
        }
        _assert_blind(packet)
        packets.append(packet)
    return packets


def build_factual_prompt(packet: Mapping[str, Any]) -> str:
    _assert_blind(packet)
    evidence = "\n".join(f"- {x}" for x in packet["source_evidence"])
    return f"""You are a strict factual-support auditor. Two ANONYMOUS short-form science scripts were generated from the SAME source packet.

SOURCE EVIDENCE (this is the complete allowed factual support):
{evidence}

CANDIDATE A:
{packet['candidate_A']}

CANDIDATE B:
{packet['candidate_B']}

For each candidate, identify whether every factual proposition is supported by the source evidence. Ordinary connective/editorial language, rhetorical questions, transitions, and clearly non-factual framing are allowed. Do not use outside knowledge. Do not infer which candidate is newer. If the source packet is insufficient to decide a factual proposition, use UNKNOWN rather than guessing.

Return ONLY JSON:
{{"pair_id":"{packet['pair_id']}","status_A":"CLEAN|UNSUPPORTED|UNKNOWN","status_B":"CLEAN|UNSUPPORTED|UNKNOWN","unsupported_propositions_A":[],"unsupported_propositions_B":[],"notes_A":[],"notes_B":[]}}"""


def parse_factual_verdict(raw: Mapping[str, Any] | str) -> dict[str, Any]:
    try:
        d = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception as exc:
        raise FactualAuditError("factual verdict is not valid JSON") from exc
    pair_id = str(d.get("pair_id") or "")
    if not pair_id:
        raise FactualAuditError("factual verdict missing pair_id")
    out: dict[str, Any] = {"pair_id": pair_id}
    for alias in ("A", "B"):
        status = str(d.get(f"status_{alias}") or "").upper()
        if status not in FACT_STATUSES:
            raise FactualAuditError(f"invalid factual status for {alias}")
        props = d.get(f"unsupported_propositions_{alias}")
        notes = d.get(f"notes_{alias}", [])
        if not isinstance(props, list) or not isinstance(notes, list):
            raise FactualAuditError(f"factual proposition/notes fields for {alias} must be lists")
        props = [_clean(x) for x in props if _clean(x)]
        notes = [_clean(x) for x in notes if _clean(x)]
        if status == "UNSUPPORTED" and not props:
            raise FactualAuditError(f"UNSUPPORTED status for {alias} requires a proposition")
        if status == "CLEAN" and props:
            raise FactualAuditError(f"CLEAN status for {alias} cannot list unsupported propositions")
        out[f"status_{alias}"] = status
        out[f"unsupported_propositions_{alias}"] = props[:10]
        out[f"notes_{alias}"] = notes[:10]
    return out


def map_factual_verdict(verdict: Mapping[str, Any] | str, key: Mapping[str, Any]) -> dict[str, Any]:
    d = parse_factual_verdict(verdict)
    if d["pair_id"] != key.get("pair_id"):
        raise FactualAuditError("factual verdict/key pair_id mismatch")
    aliases = key.get("aliases") or {}
    if set(aliases) != {"A", "B"} or set(aliases.values()) != set(Q.SIDES):
        raise FactualAuditError("malformed private aliases")
    by_side: dict[str, dict[str, Any]] = {}
    for alias in ("A", "B"):
        side = aliases[alias]
        by_side[side] = {
            "status": d[f"status_{alias}"],
            "unsupported_propositions": d[f"unsupported_propositions_{alias}"],
            "notes": d[f"notes_{alias}"],
        }
    return {
        "pair_id": d["pair_id"],
        "topic_id": str(key.get("topic_id") or ""),
        "by_side": by_side,
    }


def aggregate_with_factual_audit(
    editorial_mapped: Sequence[Mapping[str, Any]],
    factual_mapped: Sequence[Mapping[str, Any]],
    generation_results: Sequence[Mapping[str, Any]],
    *, protocol: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    editorial_by_id = {str(x.get("pair_id") or ""): x for x in editorial_mapped}
    factual_by_id = {str(x.get("pair_id") or ""): x for x in factual_mapped}
    if not editorial_by_id or set(editorial_by_id) != set(factual_by_id):
        raise FactualAuditError("editorial and factual audit pair coverage must match exactly")
    clean_editorial: list[Mapping[str, Any]] = []
    v21_failures = 0
    legacy_failures = 0
    statuses = {side: {status: 0 for status in FACT_STATUSES} for side in Q.SIDES}
    excluded: list[dict[str, Any]] = []
    for pair_id in sorted(editorial_by_id):
        factual = factual_by_id[pair_id]
        by_side = factual.get("by_side") or {}
        if set(by_side) != set(Q.SIDES):
            raise FactualAuditError(f"mapped factual verdict missing a side for {pair_id}")
        pair_clean = True
        pair_status: dict[str, str] = {}
        for side in Q.SIDES:
            status = str((by_side.get(side) or {}).get("status") or "")
            if status not in FACT_STATUSES:
                raise FactualAuditError(f"mapped factual verdict has invalid status for {pair_id}/{side}")
            statuses[side][status] += 1
            pair_status[side] = status
            if status != "CLEAN":
                pair_clean = False
                if side == "v21":
                    v21_failures += 1
                else:
                    legacy_failures += 1
        if pair_clean:
            clean_editorial.append(editorial_by_id[pair_id])
        else:
            excluded.append({"pair_id": pair_id, "topic_id": factual.get("topic_id"), "statuses": pair_status})

    report = Q.aggregate_promotion(clean_editorial, generation_results, protocol=protocol)
    total = len(factual_mapped)
    audit = {
        "pairs_audited": total,
        "editorial_pairs_both_factually_clean": len(clean_editorial),
        "editorial_pairs_excluded": len(excluded),
        "excluded_pairs": excluded,
        "status_counts": statuses,
        "clean_rate": {
            side: statuses[side]["CLEAN"] / total if total else 0.0 for side in Q.SIDES
        },
        "v21_external_factual_failures": v21_failures,
        "legacy_external_factual_failures": legacy_failures,
    }
    check = {
        "name": "v21_external_factual_failures",
        "passed": v21_failures == 0,
        "observed": v21_failures,
        "required": "=0",
        "hard": True,
    }
    report["external_factual_audit"] = audit
    report.setdefault("checks", []).append(check)
    if v21_failures:
        report["verdict"] = "NOT_PROMOTION_READY"
    return report
