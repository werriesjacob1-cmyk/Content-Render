#!/usr/bin/env python3
"""Zero-provider CLI for Writer V2.1 blind quality-proof experiments.

prepare freezes a deterministic panel and thresholds; blind builds anonymous A/B
packets from sealed generation evidence; score requires every comparable pair's
verdict before mapping identities and applying the pre-registered promotion gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

import writer_v21_quality_bakeoff as Q

ROOT = Path(__file__).resolve().parent
DEFAULT_BANK = ROOT / "topic_bank.json"
DEFAULT_QUARANTINE = ROOT / "topic_quarantine.json"


def _load(path: str | os.PathLike[str]) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(path: str | os.PathLike[str], data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def _digest(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _verify_envelope_hash(doc: Mapping[str, Any], field: str) -> None:
    expected = str(doc.get(field) or "")
    payload = dict(doc)
    payload.pop(field, None)
    if not expected or _digest(payload) != expected:
        raise Q.BakeoffProtocolError(f"{field} missing or mismatched")


def _read_plan(path: str) -> dict[str, Any]:
    doc = _load(path)
    if not isinstance(doc, dict):
        raise Q.BakeoffProtocolError("plan must be an object")
    _verify_envelope_hash(doc, "plan_sha256")
    if not isinstance(doc.get("protocol"), dict) or not isinstance(doc.get("topics"), list):
        raise Q.BakeoffProtocolError("plan must contain protocol{} and topics[]")
    ids = [str(x.get("topic_id") or "") for x in doc["topics"] if isinstance(x, dict)]
    if not ids or len(ids) != len(doc["topics"]) or len(set(ids)) != len(ids):
        raise Q.BakeoffProtocolError("plan topic identities are missing or duplicated")
    if int(doc.get("topic_count") or 0) != len(ids):
        raise Q.BakeoffProtocolError("plan topic_count does not match topics[]")
    return doc


def _read_sealed_results(path: str, plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    doc = _load(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
        raise Q.BakeoffProtocolError("generation evidence must be an object with results[]")
    expected_hash = str(doc.get("results_sha256") or "")
    if not expected_hash or _digest(doc["results"]) != expected_hash:
        raise Q.BakeoffProtocolError("generation results are unsealed or results_sha256 mismatched")
    if str(doc.get("plan_sha256") or "") != str(plan.get("plan_sha256") or ""):
        raise Q.BakeoffProtocolError("generation evidence belongs to a different frozen plan")

    expected_topics = {str(x["topic_id"]) for x in plan["topics"]}
    seen: set[tuple[str, str]] = set()
    by_topic: dict[str, set[str]] = {t: set() for t in expected_topics}
    normalized: list[dict[str, Any]] = []
    planned_treatment = {
        str(x["topic_id"]): str(x.get("planned_treatment") or "")
        for x in plan["topics"] if isinstance(x, dict)
    }
    raw_by_topic: dict[str, list[Mapping[str, Any]]] = {}
    for raw in doc["results"]:
        if not isinstance(raw, Mapping):
            raise Q.BakeoffProtocolError("generation result row must be an object")
        row = Q.normalize_result(raw)
        topic, side = row["topic_id"], row["side"]
        if topic not in expected_topics:
            raise Q.BakeoffProtocolError(f"generation evidence contains unplanned topic {topic}")
        key = (topic, side)
        if key in seen:
            raise Q.BakeoffProtocolError(f"duplicate generation result {topic}/{side}")
        seen.add(key)
        by_topic[topic].add(side)
        raw_by_topic.setdefault(topic, []).append(raw)
        expected_t = planned_treatment.get(topic, "")
        if side == "v21" and row["generated"] and expected_t and row["treatment"] != expected_t:
            raise Q.BakeoffProtocolError(
                f"V2.1 treatment drift for {topic}: expected {expected_t}, got {row['treatment'] or '<blank>'}"
            )
        normalized.append(dict(raw))
    missing = sorted(t for t, sides in by_topic.items() if sides != set(Q.SIDES))
    if missing or len(seen) != 2 * len(expected_topics):
        raise Q.BakeoffProtocolError(f"generation evidence is incomplete for planned topics: {missing}")
    for topic, raw_rows in raw_by_topic.items():
        dossier_hashes = {str(r.get("dossier_sha256") or "") for r in raw_rows}
        if len(dossier_hashes) != 1 or "" in dossier_hashes:
            raise Q.BakeoffProtocolError(f"paired systems did not share one sealed dossier for {topic}")
        orders = {tuple(r.get("generation_order") or []) for r in raw_rows}
        if len(orders) != 1 or next(iter(orders), ()) not in {("legacy", "v21"), ("v21", "legacy")}:
            raise Q.BakeoffProtocolError(f"generation order evidence malformed for {topic}")
    return normalized


def _read_private_key(path: str, *, plan: Mapping[str, Any], results_sha256: str) -> list[dict[str, Any]]:
    doc = _load(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("keys"), list):
        raise Q.BakeoffProtocolError("private key must contain keys[]")
    _verify_envelope_hash(doc, "private_sha256")
    if str(doc.get("plan_sha256") or "") != str(plan.get("plan_sha256") or ""):
        raise Q.BakeoffProtocolError("private key belongs to a different frozen plan")
    if str(doc.get("results_sha256") or "") != results_sha256:
        raise Q.BakeoffProtocolError("private key belongs to different generation evidence")
    if int(doc.get("key_count") or -1) != len(doc["keys"]):
        raise Q.BakeoffProtocolError("private key_count does not match keys[]")
    ids = [str(k.get("pair_id") or "") for k in doc["keys"] if isinstance(k, dict)]
    if len(ids) != len(doc["keys"]) or len(set(ids)) != len(ids) or any(not x for x in ids):
        raise Q.BakeoffProtocolError("private pair identities are missing or duplicated")
    return list(doc["keys"])


def cmd_prepare(args: argparse.Namespace) -> int:
    bank = _load(args.bank)
    facts = bank.get("facts") if isinstance(bank, dict) else None
    if not isinstance(facts, list):
        raise Q.BakeoffProtocolError("topic bank must contain facts[]")
    quarantine_ids: set[str] = set()
    if Path(args.quarantine).exists():
        qdoc = _load(args.quarantine)
        if isinstance(qdoc, dict) and isinstance(qdoc.get("ids"), list):
            quarantine_ids = {str(x) for x in qdoc["ids"] if str(x)}
    eligible = [f for f in facts if isinstance(f, dict) and str(f.get("id") or "") not in quarantine_ids]
    import writer_v2 as W
    treatment_by_id = {
        str(f["id"]): str(W.select_treatment(str(f["id"]), []) or "")
        for f in eligible if f.get("id")
    }
    protocol = dict(Q.DEFAULT_PROTOCOL)
    count = args.count or int(protocol["stage1_topics"])
    panel = Q.select_topic_panel(eligible, count=count, seed=args.seed, treatment_by_id=treatment_by_id)
    plan = {
        "experiment": "writer-v21-quality-proof",
        "protocol": protocol,
        "seed": args.seed,
        "topic_count": count,
        "topics": panel,
        "quarantine_excluded_count": len(quarantine_ids),
        "planned_treatment_count": len({x.get("planned_treatment") for x in panel if x.get("planned_treatment")}),
        "rules": {
            "generation": "same frozen topic panel and research dossier; record all failures/provider traces",
            "editorial_judging": "identity-blind A/B; factual integrity evaluated separately",
            "promotion": "pre-registered checks only; passing never auto-activates production",
            "render_publish": "forbidden during script-only quality proof",
        },
    }
    plan["plan_sha256"] = _digest(plan)
    _write(args.out, plan)
    print(f"prepared {count}-topic plan -> {args.out}")
    print(f"plan_sha256={plan['plan_sha256']}")
    for row in panel:
        print(f"panel {row['topic_id']} domain={row['domain']} treatment={row.get('planned_treatment')}")
    return 0


def cmd_blind(args: argparse.Namespace) -> int:
    plan = _read_plan(args.plan)
    result_doc = _load(args.results)
    results = _read_sealed_results(args.results, plan)
    results_sha = str(result_doc["results_sha256"])
    packets, keys, exclusions = Q.build_blind_packets(results, seed=args.seed)
    public = {
        "experiment": "writer-v21-quality-proof",
        "plan_sha256": plan["plan_sha256"],
        "results_sha256": results_sha,
        "seed": args.seed,
        "packet_count": len(packets),
        "packets": packets,
        "judge_prompts": [Q.build_judge_prompt(p) for p in packets],
    }
    private = {
        "experiment": "writer-v21-quality-proof-private-key",
        "plan_sha256": plan["plan_sha256"],
        "results_sha256": results_sha,
        "seed": args.seed,
        "key_count": len(keys),
        "keys": keys,
        "exclusions": exclusions,
    }
    public["public_sha256"] = _digest(public)
    private["private_sha256"] = _digest(private)
    _write(args.public_out, public)
    _write(args.key_out, private)
    print(f"built {len(packets)} blind packets -> {args.public_out}")
    print(f"private key -> {args.key_out}; exclusions={len(exclusions)}")
    return 0


def _read_verdicts(path: str) -> list[dict[str, Any]]:
    data = _load(path)
    if isinstance(data, list):
        return list(data)
    if isinstance(data, dict) and isinstance(data.get("verdicts"), list):
        return list(data["verdicts"])
    raise Q.BakeoffProtocolError("verdicts must be a list or object with verdicts[]")


def cmd_score(args: argparse.Namespace) -> int:
    plan = _read_plan(args.plan)
    result_doc = _load(args.results)
    results = _read_sealed_results(args.results, plan)
    results_sha = str(result_doc["results_sha256"])
    keys = _read_private_key(args.key, plan=plan, results_sha256=results_sha)
    by_id = {str(k["pair_id"]): k for k in keys}
    verdicts = _read_verdicts(args.verdicts)
    ids = [str(v.get("pair_id") or "") for v in verdicts if isinstance(v, Mapping)]
    if len(ids) != len(verdicts) or len(set(ids)) != len(ids) or any(not x for x in ids):
        raise Q.BakeoffProtocolError("verdict pair identities are missing or duplicated")
    expected_ids, actual_ids = set(by_id), set(ids)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        unknown = sorted(actual_ids - expected_ids)
        raise Q.BakeoffProtocolError(
            f"verdict coverage must be exact; missing={missing}, unknown={unknown}"
        )
    mapped = [Q.map_verdict(v, by_id[str(v["pair_id"])]) for v in verdicts]
    report = Q.aggregate_promotion(mapped, results, protocol=plan["protocol"])
    out = {
        "experiment": "writer-v21-quality-proof",
        "plan_sha256": plan["plan_sha256"],
        "results_sha256": results_sha,
        "private_key_sha256": _load(args.key)["private_sha256"],
        "verdict_count": len(verdicts),
        "report": report,
        "mapped_verdicts": mapped,
    }
    out["report_sha256"] = _digest(out)
    _write(args.out, out)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"report -> {args.out}")
    return 0 if report["verdict"] == "PROMOTION_READY_FOR_HUMAN_AUTHORIZATION" else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    x = sub.add_parser("prepare")
    x.add_argument("--bank", default=str(DEFAULT_BANK))
    x.add_argument("--quarantine", default=str(DEFAULT_QUARANTINE))
    x.add_argument("--count", type=int, default=None)
    x.add_argument("--seed", default="writer-v21-quality-proof-v1")
    x.add_argument("--out", default="artifacts/wr21_quality_plan.json")
    x.set_defaults(func=cmd_prepare)
    x = sub.add_parser("blind")
    x.add_argument("--plan", required=True)
    x.add_argument("--results", required=True)
    x.add_argument("--seed", default="writer-v21-quality-proof-v1")
    x.add_argument("--public-out", default="artifacts/wr21_blind_packets.json")
    x.add_argument("--key-out", default="artifacts/wr21_blind_answer_key.json")
    x.set_defaults(func=cmd_blind)
    x = sub.add_parser("score")
    x.add_argument("--plan", required=True)
    x.add_argument("--results", required=True)
    x.add_argument("--key", required=True)
    x.add_argument("--verdicts", required=True)
    x.add_argument("--out", default="artifacts/wr21_quality_report.json")
    x.set_defaults(func=cmd_score)
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except (Q.BakeoffProtocolError, OSError, json.JSONDecodeError) as exc:
        print(f"BAKEOFF PROTOCOL ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
