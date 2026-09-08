#!/usr/bin/env python3
"""Generate one evidence-bound Writer V2.1 certification bundle.

This is NOT the unattended production generator. It is the private quality lane
used before a flagship render. It makes provider calls only with a two-part
explicit acknowledgement, never renders, never publishes, and writes every
artifact needed to prove the visual stack received the same claim IDs the Writer
used.

Outputs:
- manifest.json                 canonical accepted Writer V2.1 manifest
- writer_debug.json             bounded semantic/repair/quality evidence
- writer_evidence.json          exact fact+dossier+claim inventory
- quality_session_plan.json     strict Writer->Visual Director preflight
- certification_selection.json  deterministic topic-selection evidence
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

import generate as G
import quality_session as QS
import writer_story_bridge as WSB
import writer_v2 as W
import writer_v21_orchestrator as O


LIVE_ACK = "I_ACCEPT_PROVIDER_CALLS"


def _load_history() -> list[dict[str, Any]]:
    try:
        with open(G.MEMORY, encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("history") or []) if isinstance(data, dict) else []
    except Exception:
        return []


def _eligible_bank() -> list[dict[str, Any]]:
    bank_all = G.load_bank()
    quarantined = G.load_topic_quarantine()
    return list(G.selectable_bank(bank_all, quarantined))


def _visual_rank(fact: Mapping[str, Any]) -> tuple[float, int, int, str]:
    report = W.visual_scout_score(dict(fact), banned_re=G.UNSTOCKABLE_Q)
    score = float(report.get("score") or 0.0)
    queries = len([q for q in (fact.get("queries") or []) if str(q).strip()])
    specifics = len([k for k in (fact.get("key_terms") or []) if str(k).strip()])
    return (score, queries, specifics, str(fact.get("id") or ""))


def select_topic(topic_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pick an explicit topic or deterministic visual-first fresh hero topic."""
    bank = _eligible_bank()
    if not bank:
        raise RuntimeError("no eligible topic-bank facts")
    by_id = {str(f.get("id")): f for f in bank}
    if topic_id and topic_id != "auto":
        if topic_id not in by_id:
            raise ValueError(f"topic {topic_id!r} is absent or quarantined")
        fact = dict(by_id[topic_id])
        return fact, {
            "mode": "explicit",
            "selected_topic_id": topic_id,
            "visual_scout": W.visual_scout_score(fact, banned_re=G.UNSTOCKABLE_Q),
        }

    history = _load_history()
    used = {str(h.get("fact_id")) for h in history if h.get("fact_id")}
    fresh = [f for f in bank if str(f.get("id")) not in used] or bank
    ranked = sorted(fresh, key=_visual_rank, reverse=True)
    fact = dict(ranked[0])
    shortlist = []
    for row in ranked[:8]:
        shortlist.append({
            "topic_id": row.get("id"),
            "domain": row.get("domain"),
            "rank": list(_visual_rank(row)[:3]),
            "visual_scout": W.visual_scout_score(dict(row), banned_re=G.UNSTOCKABLE_Q),
        })
    return fact, {
        "mode": "auto_visual_first_fresh",
        "selected_topic_id": fact.get("id"),
        "used_topic_count": len(used),
        "eligible_topic_count": len(bank),
        "fresh_topic_count": len(fresh),
        "shortlist": shortlist,
    }


def _recent_treatments(history: list[dict[str, Any]], n: int = 6) -> list[str]:
    vals = []
    for row in history[-n:]:
        t = str(row.get("treatment") or "").strip()
        if t:
            vals.append(t)
    return vals


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)


def build_bundle(topic_id: str, out_dir: str) -> dict[str, Any]:
    fact, selection = select_topic(topic_id)
    history = _load_history()

    # Research exactly ONCE. The canonical orchestrator normally calls
    # research_dossier internally; pin it to this exact result for the duration
    # of generation so the manifest and exported evidence inventory cannot drift
    # because a second network attempt returned a different dossier.
    dossier = G.research_dossier(fact)
    grounded = bool(dossier)
    inventory = W.build_claim_inventory(fact, dossier_facts=dossier, grounded=grounded)
    original_research = G.research_dossier
    G.research_dossier = lambda _fact: list(dossier)
    try:
        manifest, debug = O.generate_candidate_v21(
            fact,
            job_name="CURIOSITY_ITCH",
            recent_treatments=_recent_treatments(history),
            avoid_topics=", ".join(str(h.get("title") or h.get("fact_id") or "") for h in history[-5:]),
            cta_style="SAVE_WORTHY",
            use_structured=True,
        )
    finally:
        G.research_dossier = original_research

    if not manifest or not debug.get("accepted"):
        raise RuntimeError(f"Writer V2.1 did not produce an accepted candidate: {debug.get('error')!r}")
    if manifest.get("_semantic_verified") is not True:
        raise RuntimeError("accepted Writer V2.1 manifest is missing semantic verification marker")

    story = WSB.from_writer_inventory(str(fact.get("id") or ""), inventory)
    refs_ok, ref_errors = WSB.verify_manifest_refs(manifest, story)
    if not refs_ok:
        raise RuntimeError("Writer evidence bridge failed: " + "; ".join(ref_errors))

    session = QS.build_session_plan(
        manifest,
        story,
        upstream_traceability_passed=True,
    )
    ready, blockers = QS.render_preflight(session)
    if not ready:
        raise RuntimeError("strict quality-session preflight failed: " + "; ".join(blockers))

    out = Path(out_dir)
    evidence = {
        "topic_id": fact.get("id"),
        "fact": fact,
        "grounded_dossier": list(dossier),
        "claim_inventory": inventory,
        "grounded": grounded,
        "manifest_referenced_claim_ids": list(WSB.manifest_claim_ids(manifest)),
        "story_packet": {
            "topic_id": story.topic_id,
            "grounding_mode": story.grounding_mode,
            "claims": [asdict(c) for c in story.claims],
            "sources": [asdict(s) for s in story.sources],
        },
    }
    _write_json(out / "manifest.json", manifest)
    _write_json(out / "writer_debug.json", debug)
    _write_json(out / "writer_evidence.json", evidence)
    _write_json(out / "quality_session_plan.json", session.to_dict())
    _write_json(out / "certification_selection.json", selection)

    return {
        "topic_id": fact.get("id"),
        "treatment": debug.get("treatment"),
        "accepted": True,
        "semantic_verified": True,
        "grounded": grounded,
        "claim_count": len(inventory.get("claims") or []),
        "referenced_claim_count": len(WSB.manifest_claim_ids(manifest)),
        "quality_session_ready": ready,
        "writer_total_calls": debug.get("total_calls"),
        "out_dir": str(out),
    }


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--topic", default="auto", help="eligible topic_bank id, or 'auto' for deterministic visual-first fresh selection")
    p.add_argument("--out", default="artifacts/quality_certification")
    p.add_argument("--allow-provider-calls", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.allow_provider_calls or os.getenv("QUALITY_CERTIFICATION_LIVE", "") != LIVE_ACK:
        print(
            "REFUSING: certification generation requires BOTH --allow-provider-calls and "
            f"QUALITY_CERTIFICATION_LIVE={LIVE_ACK}",
            file=sys.stderr,
        )
        return 2
    try:
        result = build_bundle(args.topic, args.out)
    except Exception as exc:
        print(f"CERTIFICATION GENERATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
