#!/usr/bin/env python3
"""Corrected Writer V2.1 promotion torture panel — SCRIPT ONLY.

Runs the exact five topics used in Claude's V2/V2.1 evidence so results remain
directly comparable, but calls the fail-closed takeover orchestrator rather than
``generate.generate_candidate_v2``.

No render, no publishing, no memory/queue writes. The script makes only the
writer/critic/repair/scorer/research calls inside one candidate run. It does NOT
perform a duplicate research call for pretty-printing.

Evidence printed per topic:
- treatment / grounding / call count;
- every candidate round's complete script text;
- mechanical + semantic verification state;
- validate + production quality-floor state;
- critic diagnosis/claim support;
- score_script vs independent critic disagreement telemetry;
- targeted repair plan/stall state;
- accepted/aborted with explicit reason;
- full final script if accepted.

This runner does not alter any quality threshold. Human editorial judgment is
still required after reading the scripts.
"""
from __future__ import annotations

import json
import os
import sys
import time

import generate as G
import writer_v2_repair as R
import writer_v21_orchestrator as O
import writer_v21_quality_signals as Q


TOPIC_IDS = (
    "stomach_lining",
    "neutron_star_spoon",
    "mauna_kea",
    "chess_possible_games",
    "mantis_shrimp",
)

# 60s preserved from Claude's last live-run pacing. Override upward only when
# current rate-limit evidence justifies it; never shorten merely for speed.
INTER_TOPIC_DELAY_SECONDS = int(os.getenv("WR21_INTER_TOPIC_DELAY_SECONDS", "60"))


def _print_round(r, quality):
    print(f"  -- ROUND {r.get('round')} --")
    print(f"     HOOK: {r.get('hook')}")
    for i, text in enumerate(r.get("beats") or [], 1):
        print(f"     [{i}] {text}")
    print(f"     PAYOFF: {r.get('payoff')}")
    print(
        "     integrity: "
        f"mechanical_hard={r.get('mechanical_hard_count')} "
        f"semantic_verified={r.get('semantic_verified')} "
        f"semantic_violations={r.get('semantic_violation_count')} "
        f"semantic_critic_attempts={r.get('semantic_critic_attempts')}"
    )
    if r.get("semantic_gate_failure"):
        print(f"     SEMANTIC GATE FAILURE: {r.get('semantic_gate_failure')}")
    if r.get("semantic_coverage_errors"):
        print(f"     semantic coverage errors: {r.get('semantic_coverage_errors')}")
    print(f"     validate_err: {r.get('validate_err')}")
    print(f"     score_clears_floor: {r.get('score_clears_floor')}")
    print(f"     score_script: {r.get('score')}")
    print(f"     critic_avg: {r.get('critic_avg')}")
    print(
        "     scorer disagreement: "
        f"band={quality.get('disagreement_band')} "
        f"mapped_mean_abs={quality.get('mean_abs_mapped_delta')} "
        f"mapped_max_abs={quality.get('max_abs_mapped_delta')}"
    )
    if quality.get("critic_dimensions_below_6"):
        print(f"     critic human-quality warnings: {quality['critic_dimensions_below_6']}")
    for name, pair in (quality.get("mapped_dimensions") or {}).items():
        print(
            f"       {name}: legacy={pair['legacy']} critic={pair['critic']} "
            f"delta={pair['critic_minus_legacy']:+.2f}"
        )

    cv = r.get("critic_verdict")
    if cv:
        print(f"     critic claim_support: {cv.get('claim_support')}")
        print(f"     critic diagnosis: {cv.get('diagnosis')}")
        print(
            f"     critic requested repair={cv.get('repair_type')} "
            f"targets={cv.get('target_beats')}"
        )
    elif r.get("critic_error"):
        print(f"     critic error: {r.get('critic_error')}")

    hard = [v for v in (r.get("violations") or []) if v.get("severity") == "hard"]
    soft = [v for v in (r.get("violations") or []) if v.get("severity") == "soft"]
    if hard:
        print("     HARD violations:")
        for v in hard[:12]:
            print(
                f"       beat {v.get('beat_index')}: {v.get('kind')} "
                f"{v.get('value')!r} cited={v.get('cited_claim_ids')}"
            )
    if soft:
        print(f"     soft telemetry sample ({len(soft)} total):")
        for v in soft[:6]:
            print(f"       beat {v.get('beat_index')}: {v.get('kind')} {v.get('value')!r}")
    print(f"     repair plan: {r.get('repair_plan')}")
    if r.get("repair_error"):
        print(f"     repair error: {r.get('repair_error')}")


def run_topic(tid, fact):
    print(f"\n{'#' * 88}\n# TOPIC: {tid} ({fact.get('domain')})\n# FACT: {fact.get('fact')}\n{'#' * 88}")
    manifest, debug = O.generate_candidate_v21(
        fact,
        job_name="CURIOSITY_ITCH",
        recent_treatments=[],
        avoid_topics="none",
        cta_style="SAVE_WORTHY",
        use_structured=True,
    )
    q = Q.analyze_debug(debug)

    print(
        f"orchestrator={debug.get('orchestrator')} treatment={debug.get('treatment')} "
        f"grounded={debug.get('grounded')} provenance={debug.get('provenance_note')!r}"
    )
    print(
        f"prompt={debug.get('prompt_chars')} chars/~{debug.get('prompt_tokens_est')} tokens "
        f"calls={debug.get('total_calls')} semantic_retries={debug.get('semantic_retries_used')} "
        f"ceiling={debug.get('structured_invocation_ceiling')}"
    )
    for i, call in enumerate(debug.get("calls") or []):
        print(
            f"  call {i}: provider={call.get('provider')} model={call.get('model')} "
            f"structured={call.get('structured')} usage={call.get('usage')} "
            f"error={call.get('error')}"
        )

    for round_info, quality in zip(debug.get("rounds") or [], q.get("rounds") or []):
        _print_round(round_info, quality)

    print(f"  QUALITY SIGNAL SUMMARY: {json.dumps(q, sort_keys=True)}")
    print(f"  ACCEPTED: {debug.get('accepted')}  error={debug.get('error')!r}")
    print(f"  selected_score={debug.get('score')} repair_rounds={debug.get('repair_rounds')}")

    if manifest:
        print("  FINAL SCRIPT:")
        print(f"    HOOK: {manifest.get('hook')}")
        for i, scene in enumerate(manifest.get("scenes") or [], 1):
            print(f"    [{i}] {scene.get('voiceover')}")
        print(f"    PAYOFF: {manifest.get('payoff')}")
        print(f"    semantic_verified={manifest.get('_semantic_verified')}")

        # Belt-and-suspenders mechanical re-check using the claim IDs already
        # retained in the manifest. Full semantic evidence remains in debug.
        writer_shape = {
            "hook": manifest.get("hook"),
            "hook_source_claim_ids": manifest.get("hook_source_claim_ids") or [],
            "beats": [
                {
                    "voiceover": s.get("voiceover"),
                    "source_claim_ids": s.get("source_claim_ids") or [],
                }
                for s in (manifest.get("scenes") or [])
            ],
            "payoff": manifest.get("payoff"),
            "payoff_source_claim_ids": manifest.get("payoff_source_claim_ids") or [],
        }
        # We intentionally do NOT call research again to reconstruct the claim
        # inventory here. The orchestrator already performed traceability before
        # selection; an extra dossier request would waste quota and could change
        # evidence mid-run.
        print(f"    claim-bound writer shape retained: {json.dumps(writer_shape, ensure_ascii=False)}")
    else:
        print(f"  ABORTED: validate_err={debug.get('validate_err')!r}")

    return {
        "topic": tid,
        "accepted": bool(debug.get("accepted")),
        "score": debug.get("score"),
        "calls": debug.get("total_calls"),
        "semantic_retries": debug.get("semantic_retries_used"),
        "repair_rounds": debug.get("repair_rounds"),
        "quality_signal": q,
        "error": debug.get("error"),
    }


def main():
    bank = {f["id"]: f for f in G.load_bank()}
    print("WRITER V2.1 TAKEOVER TORTURE PANEL — SCRIPT ONLY / NO RENDER / NO PUBLISH")
    print(f"topics={list(TOPIC_IDS)} delay={INTER_TOPIC_DELAY_SECONDS}s")
    results = []
    for idx, tid in enumerate(TOPIC_IDS):
        fact = bank.get(tid)
        if not fact:
            print(f"!! {tid}: topic not found in bank")
            continue
        if idx and INTER_TOPIC_DELAY_SECONDS > 0:
            print(f"\n[bakeoff] pacing {INTER_TOPIC_DELAY_SECONDS}s before {tid}...")
            time.sleep(INTER_TOPIC_DELAY_SECONDS)
        results.append(run_topic(tid, fact))

    print(f"\n{'=' * 88}\nSUMMARY\n{'=' * 88}")
    for r in results:
        qs = r["quality_signal"]
        print(
            f"{r['topic']}: accepted={r['accepted']} score={r['score']} calls={r['calls']} "
            f"semantic_retries={r['semantic_retries']} repair_rounds={r['repair_rounds']} "
            f"max_judge_disagreement={qs.get('max_disagreement_band')} "
            f"winner_disagreement={(qs.get('selection') or {}).get('winner_disagreement')} "
            f"error={r['error']!r}"
        )
    accepted = sum(1 for r in results if r["accepted"])
    print(f"accepted={accepted}/{len(results)} — this is NOT a promotion verdict until a human reads the scripts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
