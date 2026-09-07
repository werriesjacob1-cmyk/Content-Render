#!/usr/bin/env python3
"""Zero-provider CLI for Writer V2.1 blind quality-proof experiments.

prepare freezes a deterministic panel and thresholds; blind builds anonymous A/B
packets; score maps completed verdicts back to systems and applies promotion gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

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


def _read_results(path: str) -> list[dict[str, Any]]:
    data = _load(path)
    if isinstance(data, list):
        return list(data)
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return list(data["results"])
    raise Q.BakeoffProtocolError("results must be a list or object with results[]")


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
    # Pure deterministic treatment mapping; no provider call or quality peeking.
    import writer_v2 as W
    treatment_by_id = {
        str(f["id"]): str(W.select_treatment(str(f["id"]), []) or "")
        for f in eligible if f.get("id")
    }
    protocol = dict(Q.DEFAULT_PROTOCOL)
    count = args.count or int(protocol["stage1_topics"])
    panel = Q.select_topic_panel(
        eligible, count=count, seed=args.seed, treatment_by_id=treatment_by_id,
    )
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
    packets, keys, exclusions = Q.build_blind_packets(_read_results(args.results), seed=args.seed)
    public = {
        "experiment": "writer-v21-quality-proof",
        "seed": args.seed,
        "packet_count": len(packets),
        "packets": packets,
        "judge_prompts": [Q.build_judge_prompt(p) for p in packets],
    }
    private = {
        "experiment": "writer-v21-quality-proof-private-key",
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
    key_doc = _load(args.key)
    keys = key_doc.get("keys") if isinstance(key_doc, dict) else None
    if not isinstance(keys, list):
        raise Q.BakeoffProtocolError("private key must contain keys[]")
    by_id = {str(k.get("pair_id")): k for k in keys if isinstance(k, dict) and k.get("pair_id")}
    verdicts = _read_verdicts(args.verdicts)
    ids = [str(v.get("pair_id") or "") for v in verdicts]
    if len(set(ids)) != len(ids):
        raise Q.BakeoffProtocolError("duplicate pair_id in verdicts")
    unknown = sorted(i for i in ids if i not in by_id)
    if unknown:
        raise Q.BakeoffProtocolError(f"unknown verdict pair ids: {unknown}")
    mapped = [Q.map_verdict(v, by_id[str(v.get("pair_id"))]) for v in verdicts]
    protocol = Q.DEFAULT_PROTOCOL
    if args.plan:
        plan = _load(args.plan)
        if isinstance(plan, dict) and isinstance(plan.get("protocol"), dict):
            protocol = plan["protocol"]
    report = Q.aggregate_promotion(mapped, _read_results(args.results), protocol=protocol)
    out = {"experiment": "writer-v21-quality-proof", "report": report, "mapped_verdicts": mapped}
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
    x.add_argument("--results", required=True)
    x.add_argument("--seed", default="writer-v21-quality-proof-v1")
    x.add_argument("--public-out", default="artifacts/wr21_blind_packets.json")
    x.add_argument("--key-out", default="artifacts/wr21_blind_answer_key.json")
    x.set_defaults(func=cmd_blind)
    x = sub.add_parser("score")
    x.add_argument("--results", required=True)
    x.add_argument("--key", required=True)
    x.add_argument("--verdicts", required=True)
    x.add_argument("--plan", default=None)
    x.add_argument("--out", default="artifacts/wr21_quality_report.json")
    x.set_defaults(func=cmd_score)
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except Q.BakeoffProtocolError as exc:
        print(f"BAKEOFF PROTOCOL ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
