#!/usr/bin/env python3
"""Corrected Writer V2.1 promotion torture panel — SCRIPT ONLY.

Runs the exact five topics used in Claude's V2/V2.1 evidence so results remain
directly comparable, but calls the fail-closed takeover runtime rather than the
old fail-open ``generate.generate_candidate_v2`` path.

No render, publishing, memory, or queue writes. The script makes only the
writer/critic/repair/scorer/research calls inside one candidate run. It does NOT
perform a duplicate research call merely to pretty-print provenance.

Each topic emits one coherent editorial dossier:
- complete script for every repair round;
- mechanical + semantic verification state;
- validate + true production quality-floor state;
- score_script vs independent critic disagreement;
- deterministic retention/editorial warnings;
- narrative function/shape and estimated first-eight-second exposure;
- targeted repair plan and round-to-round craft regression;
- blind pairwise-judge plans for eligible clean repair transitions;
- accepted/aborted with explicit reason;
- corrected render-manifest scene order if accepted.

All diagnostic layers are telemetry only. Human editorial judgment remains the
promotion authority.
"""
from __future__ import annotations

import json
import os
import sys
import time

import generate as G
import writer_v21_editorial_diagnostics as E
import writer_v21_orchestrator as O
import writer_v21_pairwise as P
import writer_v21_quality_signals as Q
import writer_v21_repair_regression as RR
import writer_v21_story_shape as S


TOPIC_IDS = (
    "stomach_lining",
    "neutron_star_spoon",
    "mauna_kea",
    "chess_possible_games",
    "mantis_shrimp",
)

# Preserves Claude's last inter-topic pacing. Never shorten merely for speed.
INTER_TOPIC_DELAY_SECONDS = int(os.getenv("WR21_INTER_TOPIC_DELAY_SECONDS", "60"))


def _editorial_for_round(r):
    return E.editorial_diagnostics(
        hook=r.get("hook") or "",
        beats=r.get("beats") or [],
        payoff=r.get("payoff") or "",
    )


def _shape_for_round(r):
    hook = r.get("hook") or ""
    beats = r.get("beats") or []
    payoff = r.get("payoff") or ""
    return {
        "signature": S.shape_signature(hook, beats, payoff),
        "first_8_seconds": S.first_eight_seconds_audit(hook, beats),
    }


def _print_round(r, quality, editorial, shape):
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

    print(
        "     editorial telemetry: "
        f"warnings={editorial.get('warning_kinds')} "
        f"hook_words={editorial.get('hook_word_count')} "
        f"hook_payoff_overlap={editorial.get('hook_payoff_overlap')}"
    )
    info_gain = editorial.get("beat_information_gain") or []
    if info_gain:
        print(
            "     information gain: "
            + ", ".join(
                f"b{x.get('beat_index')}={x.get('new_content_ratio')}" for x in info_gain
            )
        )

    sig = shape.get("signature") or {}
    first8 = shape.get("first_8_seconds") or {}
    print(
        "     story shape: "
        f"primary={sig.get('primary_sequence')} "
        f"unique_functions={sig.get('unique_function_count')}"
    )
    print(
        "     first 8s: "
        f"hook_est={first8.get('hook_estimated_seconds')}s "
        f"fully_heard_beats_after_hook={first8.get('fully_heard_beats_after_hook')} "
        f"functions={first8.get('opening_primary_functions')} "
        f"warnings={first8.get('warnings')}"
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


def _render_manifest_story(manifest):
    scenes = list(manifest.get("scenes") or [])
    print("  FINAL RENDER-MANIFEST STORY:")
    for scene in scenes:
        role = scene.get("_v2_role") or "scene"
        print(
            f"    scene {scene.get('id')} [{role}] {scene.get('voiceover')} "
            f"claims={scene.get('source_claim_ids')} query={scene.get('search_query')!r}"
        )
    print(f"    script={manifest.get('script')}")
    print(f"    semantic_verified={manifest.get('_semantic_verified')}")

    # Reconstruct the actual writer shape without accidentally counting the
    # promoted hook/payoff scenes as middle beats a second time.
    middle = [s for s in scenes if s.get("_v2_role") == "beat"]
    writer_shape = {
        "hook": manifest.get("hook"),
        "hook_source_claim_ids": manifest.get("hook_source_claim_ids") or [],
        "beats": [
            {
                "voiceover": s.get("voiceover"),
                "source_claim_ids": s.get("source_claim_ids") or [],
            }
            for s in middle
        ],
        "payoff": manifest.get("payoff"),
        "payoff_source_claim_ids": manifest.get("payoff_source_claim_ids") or [],
    }
    print(f"    claim-bound writer shape retained: {json.dumps(writer_shape, ensure_ascii=False)}")


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
    regression = RR.analyze_debug(debug)
    pairwise_plans = P.pairwise_plans_from_debug(debug)

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

    rounds = list(debug.get("rounds") or [])
    quality_rounds = list(q.get("rounds") or [])
    for idx, round_info in enumerate(rounds):
        quality = quality_rounds[idx] if idx < len(quality_rounds) else Q.quality_signal_report(
            round_info.get("score"), round_info.get("critic_verdict")
        )
        _print_round(
            round_info,
            quality,
            _editorial_for_round(round_info),
            _shape_for_round(round_info),
        )

    print(f"  QUALITY SIGNAL SUMMARY: {json.dumps(q, sort_keys=True)}")
    print(f"  REPAIR REGRESSION SUMMARY: {json.dumps(regression, ensure_ascii=False, sort_keys=True)}")
    print(
        "  BLIND PAIRWISE PLANS: "
        f"{len(pairwise_plans)} eligible clean transition(s); "
        "prompts prepared but NOT called by this runner"
    )
    for plan in pairwise_plans:
        print(
            f"    rounds {plan.get('from_round')}->{plan.get('to_round')} "
            f"aliases={plan.get('packet', {}).get('aliases')}"
        )

    print(f"  ACCEPTED: {debug.get('accepted')}  error={debug.get('error')!r}")
    print(f"  selected_score={debug.get('score')} repair_rounds={debug.get('repair_rounds')}")

    if manifest:
        _render_manifest_story(manifest)
    else:
        print(f"  ABORTED: validate_err={debug.get('validate_err')!r}")

    last_round = rounds[-1] if rounds else {}
    last_editorial = _editorial_for_round(last_round) if last_round else {}
    last_shape = _shape_for_round(last_round) if last_round else {}
    return {
        "topic": tid,
        "treatment": debug.get("treatment"),
        "accepted": bool(debug.get("accepted")),
        "score": debug.get("score"),
        "calls": debug.get("total_calls"),
        "semantic_retries": debug.get("semantic_retries_used"),
        "repair_rounds": debug.get("repair_rounds"),
        "quality_signal": q,
        "repair_regression": regression,
        "pairwise_plan_count": len(pairwise_plans),
        "final_editorial_warning_kinds": last_editorial.get("warning_kinds") or [],
        "final_story_shape": (last_shape.get("signature") or {}).get("primary_sequence"),
        "final_first8_warnings": (last_shape.get("first_8_seconds") or {}).get("warnings") or [],
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
            f"{r['topic']}: treatment={r['treatment']} accepted={r['accepted']} score={r['score']} "
            f"calls={r['calls']} semantic_retries={r['semantic_retries']} repair_rounds={r['repair_rounds']} "
            f"judge_disagreement={qs.get('max_disagreement_band')} "
            f"winner_disagreement={(qs.get('selection') or {}).get('winner_disagreement')} "
            f"repair_regressions={r['repair_regression'].get('all_regression_flag_kinds')} "
            f"editorial={r['final_editorial_warning_kinds']} first8={r['final_first8_warnings']} "
            f"shape={r['final_story_shape']} error={r['error']!r}"
        )

    # Portfolio-level structure matters: treatment labels alone are not proof of
    # variety. Use the best/latest text from every topic attempt available.
    script_shapes = []
    for r in results:
        shape = r.get("final_story_shape")
        if shape:
            script_shapes.append({
                "hook": "",
                "beats": [],
                "payoff": "",
                "treatment": r.get("treatment"),
                "_precomputed_shape": shape,
            })
    # Raw shape sequences are already printed per topic. Full cross-script
    # S.portfolio_diversity() requires script text; retain a future-safe note
    # instead of fabricating comparison inputs from only the signature.
    print(f"topics_with_shape_evidence={len(script_shapes)}/{len(results)}")

    accepted = sum(1 for r in results if r["accepted"])
    print(
        f"accepted={accepted}/{len(results)} — NOT a promotion verdict until a human reads the scripts "
        "and reviews factual safety, first-8-second momentum, repair regressions, and actual postability"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
