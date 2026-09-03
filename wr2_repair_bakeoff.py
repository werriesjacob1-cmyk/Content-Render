#!/usr/bin/env python3
"""SCRIPT-ONLY LIVE BAKEOFF -- V2 traceability/repair mission, 2026-09-03,
Phase 10. NOT part of the production pipeline: no render, no publish, no
manifest saved, no memory/queue file touched. Exercises the FULL
generate_candidate_v2() repair loop (draft -> check_traceability() ->
validate()/score_script() -> creative critic -> classify_repair() ->
targeted repair -> revalidate -> rescore -> accept-or-abort) against 5 real
topics spanning the mission's required categories:

  1. stomach_lining        -- biological/medical mechanism
  2. neutron_star_spoon    -- space/physics
  3. mauna_kea              -- Earth/nature (and itself a magnitude-comparison
                               topic: "measured from the ocean floor")
  4. chess_possible_games  -- a topic that invites seductive, easily-inflated
                               number comparisons (atoms in the universe)
  5. mantis_shrimp          -- visually strong (real, filmable subject)

For each topic, prints every diagnostic the mission's report requires:
topic, treatment, source mode (grounded dossier vs base-fact-only), model,
initial script, initial provenance violations, initial quality score, critic
diagnosis, repair round(s), final script, final provenance result, final
quality score, category scores, token usage, accepted/rejected. Nothing here
is judged automatically -- the human editorial verdict (Phase 11) is written
up separately after reading this output.
"""
import json
import sys
import time

import generate as G
import writer_v2 as W2
import writer_v2_repair as WR

# 2026-09-03 Phase 10 first attempt: 5 topics dispatched back-to-back
# saturated Groq's 8000-TPM/minute cap almost immediately (each topic can
# burn 5 calls x ~1500-3500 prompt tokens across retries) -- 3 of 5 topics
# never even got a working initial draft. A real production render only
# generates ONE video, so this contention is an artifact of THIS bakeoff's
# own tight loop, not the architecture. Pace topics out so each one gets a
# fresh-ish per-minute budget instead of inheriting the last topic's debt.
INTER_TOPIC_DELAY_SECONDS = 45

TOPIC_IDS = ["stomach_lining", "neutron_star_spoon", "mauna_kea", "chess_possible_games", "mantis_shrimp"]


def _print_round(r):
    print(f"  -- round {r['round']} --")
    print(f"     HOOK: {r.get('hook')}")
    for i, b in enumerate(r.get("beats") or []):
        print(f"     [{i + 1}] {b}")
    print(f"     PAYOFF: {r.get('payoff')}")
    print(f"     traceability violations ({r['violation_count']}):")
    for v in r["violations"]:
        print(f"       beat {v['beat_index']}: {v['kind']} {v['value']!r} (cited: {v['cited_claim_ids']})")
    print(f"     validate_err: {r['validate_err']}")
    print(f"     score: {r['score']}")
    if "critic_verdict" in r:
        cv = r["critic_verdict"]
        if cv:
            print(f"     critic scores: {cv.get('scores')}")
            print(f"     critic repair_type: {cv.get('repair_type')}  target_beats: {cv.get('target_beats')}")
            print(f"     critic diagnosis: {cv.get('diagnosis')}")
        else:
            print(f"     critic call failed: {r.get('critic_error')}")
    if "repair_plan" in r:
        print(f"     repair plan applied: {r['repair_plan']}")
    if r.get("repair_error"):
        print(f"     repair error: {r['repair_error']}")


def run_topic(tid, fact):
    print(f"\n{'#' * 78}\n# TOPIC: {tid}  ({fact['domain']})\n# fact: {fact['fact']}\n{'#' * 78}")

    dossier = G.research_dossier(fact)
    grounded = bool(dossier)
    print(f"research_dossier(): {len(dossier)} facts (grounded={grounded})")
    if not grounded:
        print("  -> base-fact-only mode this run (no grounding available) -- this is the HARDER "
              "provenance test per the mission's own framing, not a blocked run.")

    inv = W2.build_claim_inventory(fact, dossier_facts=dossier, grounded=grounded)
    print(f"claim inventory: {len(inv['claims'])} claims, provenance_note={inv['provenance_note']!r}")
    for c in inv["claims"]:
        print(f"  [{c['claim_id']}] ({c['source_kind']}/{c['source_ref']}) {c['claim_text']}")

    treatment = W2.select_treatment(tid)
    print(f"treatment: {treatment}")

    m, debug = G.generate_candidate_v2(fact, job_name="CURIOSITY_ITCH", recent_treatments=[],
                                       avoid_topics="none", cta_style="SAVE_WORTHY", use_structured=True)

    print(f"\nprompt: {debug['prompt_chars']} chars, ~{debug['prompt_tokens_est']} tokens")
    print(f"calls made: {debug.get('total_calls')}")
    for i, c in enumerate(debug.get("calls") or []):
        print(f"  call {i}: provider={c.get('provider')} model={c.get('model')} "
              f"structured={c.get('structured')} usage={c.get('usage')} error={c.get('error')}")

    for r in debug.get("rounds") or []:
        _print_round(r)

    print(f"\nrepair_rounds: {debug.get('repair_rounds')}")
    print(f"ACCEPTED: {debug.get('accepted')}")

    if m:
        print(f"\nFINAL TITLE: {m.get('title')}")
        print(f"FINAL HOOK: {m.get('hook')}  (claims: {m.get('hook_source_claim_ids')})")
        for s in m.get("scenes", []):
            print(f"  [{s['id']}] ({s['search_query']!r}) {s['voiceover']}  (claims: {s['source_claim_ids']})")
        print(f"FINAL PAYOFF: {m.get('payoff')}  (claims: {m.get('payoff_source_claim_ids')})")
        print(f"FINAL SCORE: {m.get('_quality')}")
        print(f"WORD COUNT: {len(m.get('script', '').split())}")
        final_violations = WR.check_traceability(
            {"hook": m["hook"], "hook_source_claim_ids": m["hook_source_claim_ids"],
             "beats": [{"voiceover": s["voiceover"], "source_claim_ids": s["source_claim_ids"]}
                      for s in m["scenes"]],
             "payoff": m["payoff"], "payoff_source_claim_ids": m["payoff_source_claim_ids"]},
            inv)
        print(f"FINAL TRACEABILITY RE-CHECK (should be 0): {len(final_violations)}")
    else:
        print("\n(no usable manifest -- run ABORTED)")
        print(f"final validate_err: {debug.get('validate_err')}")

    return m, debug


def main():
    bank = {f["id"]: f for f in G.load_bank()}
    print(f"PHASE 10 LIVE BAKEOFF -- TOPICS: {TOPIC_IDS}")
    results = {}
    for i, tid in enumerate(TOPIC_IDS):
        if i > 0:
            print(f"\n[bakeoff] pacing {INTER_TOPIC_DELAY_SECONDS}s before next topic "
                  f"(let the per-minute TPM budget recover)...")
            time.sleep(INTER_TOPIC_DELAY_SECONDS)
        fact = bank.get(tid)
        if not fact:
            print(f"!! topic {tid} not found in bank, skipping")
            continue
        m, debug = run_topic(tid, fact)
        results[tid] = {"accepted": debug.get("accepted"), "score": debug.get("score"),
                        "repair_rounds": debug.get("repair_rounds"), "calls": debug.get("total_calls")}

    print(f"\n\n{'=' * 78}\nSUMMARY\n{'=' * 78}")
    for tid, r in results.items():
        print(f"  {tid}: accepted={r['accepted']} score={r['score']} "
              f"repair_rounds={r['repair_rounds']} calls={r['calls']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
