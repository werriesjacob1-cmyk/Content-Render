#!/usr/bin/env python3
"""Guarded SCRIPT-ONLY generator for the Writer V2.1 quality proof.

Provider calls require BOTH --allow-provider-calls and the exact environment
acknowledgement. Production/provider-aware modules are imported only after that
gate. The runner never renders, publishes, writes manifest.json, or touches queues.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping

LIVE_ENV = "WR21_QUALITY_BAKEOFF_LIVE"
LIVE_ACK = "I_ACCEPT_PROVIDER_CALLS"


def _load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(path: str, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def _digest(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _verify_plan(plan: Mapping[str, Any]) -> None:
    expected = str(plan.get("plan_sha256") or "")
    payload = dict(plan)
    payload.pop("plan_sha256", None)
    if not expected or _digest(payload) != expected:
        raise ValueError("plan hash missing or mismatched")
    if not isinstance(plan.get("topics"), list) or not plan["topics"]:
        raise ValueError("plan contains no topics")


def _gate(args: argparse.Namespace) -> None:
    if not args.allow_provider_calls or os.environ.get(LIVE_ENV) != LIVE_ACK:
        raise RuntimeError(
            "provider calls disabled; requires --allow-provider-calls AND "
            f"{LIVE_ENV}={LIVE_ACK}"
        )


def _pm(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return f"{value[0]}/{value[1]}"
    return str(value or "").strip()


def _safe_calls(calls: Any) -> list[dict[str, Any]]:
    allowed = {
        "provider", "model", "provider_model", "structured", "schema", "schema_name",
        "ok", "status", "error", "usage", "prompt_tokens", "completion_tokens", "total_tokens",
    }
    out: list[dict[str, Any]] = []
    for row in calls if isinstance(calls, list) else []:
        if isinstance(row, Mapping):
            out.append({k: row[k] for k in allowed if k in row})
    return out


def _draft_model(calls: Any) -> str:
    safe = _safe_calls(calls)
    if not safe:
        return ""
    first = safe[0]
    if first.get("provider_model"):
        return _pm(first["provider_model"])
    return "/".join(x for x in (str(first.get("provider") or ""), str(first.get("model") or "")) if x)


@contextmanager
def _frozen_dossier(G, dossier: list[str]):
    original = G.research_dossier
    G.research_dossier = lambda _fact: list(dossier)
    try:
        yield
    finally:
        G.research_dossier = original


def _spoken(N, manifest: Mapping[str, Any] | None) -> str:
    if not manifest:
        return ""
    try:
        return str(N.spoken_text(dict(manifest)) or "").strip()
    except Exception:
        return str(manifest.get("script") or "").strip()


def _run_legacy(G, N, fact: Mapping[str, Any], dossier: list[str]) -> dict[str, Any]:
    prompt = G.build_prompt(
        "CURIOSITY_ITCH", G.VIEWER_JOBS[0][1], "none", fact=fact,
        avoid_openers=None, cta_style="SAVE_WORTHY", dossier=dossier,
        hook_frame=G.HOOK_FRAMES[0],
    )
    row: dict[str, Any] = {
        "topic_id": str(fact.get("id") or ""), "side": "legacy",
        "prompt_chars": len(prompt), "prompt_tokens_est": G.estimate_tokens(prompt),
        "generated": False, "validate_clean": False, "integrity_clean": None,
        "semantic_verified": None, "treatment": "", "calls": 1, "script": "",
        "repair_regression_flags": [],
    }
    try:
        raw = G.call_groq(prompt)
        row["draft_provider_model"] = _pm(getattr(G, "_WORKING_MODEL", None))
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError(f"legacy model returned {type(obj).__name__}, not object")
        err = G.validate(obj, "CURIOSITY_ITCH", fact=fact)
        row.update(
            generated=True, validate_clean=not bool(err), validate_err=err,
            script=_spoken(N, obj),
            score=None if err else G.score_script(obj, fact=fact, cta_style="SAVE_WORTHY"),
        )
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"
        row.setdefault("draft_provider_model", _pm(getattr(G, "_WORKING_MODEL", None)))
    return row


def _run_v21(G, N, O, RR, fact: Mapping[str, Any], dossier: list[str]) -> dict[str, Any]:
    try:
        with _frozen_dossier(G, dossier):
            manifest, debug = O.generate_candidate_v21(
                fact, job_name="CURIOSITY_ITCH", recent_treatments=[], avoid_topics="none",
                cta_style="SAVE_WORTHY", use_structured=True,
            )
    except Exception as exc:  # noqa: BLE001
        return {
            "topic_id": str(fact.get("id") or ""), "side": "v21", "generated": False,
            "validate_clean": False, "integrity_clean": None, "semantic_verified": None,
            "script": "", "treatment": "", "calls": 0, "provider_trace": [],
            "repair_regression_flags": [], "error": f"{type(exc).__name__}: {exc}",
        }
    debug = debug if isinstance(debug, dict) else {}
    calls = debug.get("calls") or []
    semantic = bool(manifest and manifest.get("_semantic_verified"))
    regression = RR.analyze_debug(debug)
    return {
        "topic_id": str(fact.get("id") or ""), "side": "v21",
        "generated": bool(manifest), "validate_clean": bool(manifest and debug.get("accepted")),
        "integrity_clean": semantic if manifest else None,
        "semantic_verified": semantic if manifest else None,
        "script": _spoken(N, manifest), "treatment": str(debug.get("treatment") or ""),
        "calls": len(calls), "draft_provider_model": _draft_model(calls),
        "provider_trace": _safe_calls(calls), "score": debug.get("score"),
        "error": str(debug.get("error") or ""),
        "semantic_retries_used": int(debug.get("semantic_retries_used") or 0),
        "round_count": len(debug.get("rounds") or []),
        "repair_transition_count": len(regression.get("transitions") or []),
        "repair_regression_flags": list(regression.get("all_regression_flag_kinds") or []),
    }


def _order(seed: str, topic: str) -> tuple[str, str]:
    bit = int(hashlib.sha256(f"{seed}|{topic}|generation-order".encode()).hexdigest()[:2], 16) % 2
    return ("legacy", "v21") if bit == 0 else ("v21", "legacy")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", required=True)
    p.add_argument("--out", default="artifacts/wr21_generation_results.json")
    p.add_argument("--allow-provider-calls", action="store_true")
    p.add_argument("--inter-topic-delay", type=int, default=60)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)
    try:
        _gate(args)
        plan = _load(args.plan)
        if not isinstance(plan, dict):
            raise ValueError("plan must be object")
        _verify_plan(plan)
    except Exception as exc:  # noqa: BLE001
        print(f"LIVE BAKEOFF REFUSED: {exc}", file=sys.stderr)
        return 3

    # Provider-aware production modules are deliberately imported only here.
    import generate as G  # noqa: PLC0415
    import narration as N  # noqa: PLC0415
    import writer_v21_orchestrator as O  # noqa: PLC0415
    import writer_v21_repair_regression as RR  # noqa: PLC0415

    bank = {str(f.get("id")): f for f in G.load_bank() if isinstance(f, dict) and f.get("id")}
    topics = list(plan["topics"])
    if args.limit is not None:
        topics = topics[:max(0, args.limit)]
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if Path(args.out).exists():
        prior = _load(args.out)
        if isinstance(prior, dict) and prior.get("plan_sha256") == plan.get("plan_sha256"):
            for row in prior.get("results") or []:
                if isinstance(row, dict):
                    existing[(str(row.get("topic_id")), str(row.get("side")))] = row

    doc: dict[str, Any] = {
        "experiment": "writer-v21-quality-proof-live-generation",
        "plan_sha256": plan["plan_sha256"], "seed": plan.get("seed"),
        "script_only": True, "rendered": False, "published": False,
        "results": list(existing.values()),
    }
    for idx, planned in enumerate(topics):
        topic = str(planned.get("topic_id") or "")
        fact = bank.get(topic)
        if not fact:
            for side in ("legacy", "v21"):
                existing[(topic, side)] = {
                    "topic_id": topic, "side": side, "generated": False, "validate_clean": False,
                    "integrity_clean": None, "semantic_verified": None, "script": "", "treatment": "",
                    "calls": 0, "repair_regression_flags": [], "error": "topic missing from bank",
                }
            doc["results"] = list(existing.values()); _write(args.out, doc)
            continue
        if idx and args.inter_topic_delay > 0:
            time.sleep(args.inter_topic_delay)
        print(f"### {idx + 1}/{len(topics)} {topic} — freeze one shared dossier")
        try:
            dossier = list(G.research_dossier(fact) or [])
        except Exception as exc:  # noqa: BLE001
            print(f"dossier failure: {type(exc).__name__}: {exc}; using empty dossier")
            dossier = []
        dossier_sha = hashlib.sha256(json.dumps(dossier, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        order = _order(str(plan.get("seed") or ""), topic)
        for side in order:
            key = (topic, side)
            if key in existing:
                print(f"  {side}: resume-skip")
                continue
            print(f"  {side}: generate script only")
            row = _run_legacy(G, N, fact, dossier) if side == "legacy" else _run_v21(G, N, O, RR, fact, dossier)
            row["dossier_sha256"] = dossier_sha
            row["generation_order"] = list(order)
            existing[key] = row
            doc["results"] = list(existing.values())
            _write(args.out, doc)
            print(f"    generated={row.get('generated')} validate={row.get('validate_clean')} provider={row.get('draft_provider_model')!r} calls={row.get('calls')} error={row.get('error')!r}")
    doc["results"] = sorted(existing.values(), key=lambda r: (str(r.get("topic_id")), str(r.get("side"))))
    doc["results_sha256"] = _digest(doc["results"])
    _write(args.out, doc)
    print(f"SCRIPT-ONLY results -> {args.out}; no render/publish action invoked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
