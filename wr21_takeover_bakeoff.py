#!/usr/bin/env python3
"""Corrected Writer V2.1 promotion torture panel — SCRIPT ONLY."""
from __future__ import annotations
import json, os, sys, time
import generate as G
import writer_v21_editorial_diagnostics as E
import writer_v21_hook_payoff as HP
import writer_v21_orchestrator as O
import writer_v21_pairwise as P
import writer_v21_quality_signals as Q
import writer_v21_repair_regression as RR
import writer_v21_story_shape as S

TOPIC_IDS=("stomach_lining","neutron_star_spoon","mauna_kea","chess_possible_games","mantis_shrimp")
INTER_TOPIC_DELAY_SECONDS=int(os.getenv("WR21_INTER_TOPIC_DELAY_SECONDS","60"))

def _editorial_for_round(r): return E.editorial_diagnostics(hook=r.get("hook") or "",beats=r.get("beats") or [],payoff=r.get("payoff") or "")
def _shape_for_round(r):
    h=r.get("hook") or ""; b=r.get("beats") or []; p=r.get("payoff") or ""
    return {"signature":S.shape_signature(h,b,p),"first_8_seconds":S.first_eight_seconds_audit(h,b)}
def _hp_for_round(r,fact):
    return HP.payoff_proof_report(hook=r.get("hook") or "",payoff=r.get("payoff") or "",central_question=(fact or {}).get("whatif") or "")

def _print_round(r,quality,editorial,shape,payoff):
    print(f"  -- ROUND {r.get('round')} --\n     HOOK: {r.get('hook')}")
    for i,t in enumerate(r.get('beats') or [],1): print(f"     [{i}] {t}")
    print(f"     PAYOFF: {r.get('payoff')}")
    print(f"     integrity: mechanical_hard={r.get('mechanical_hard_count')} semantic_verified={r.get('semantic_verified')} semantic_violations={r.get('semantic_violation_count')} semantic_critic_attempts={r.get('semantic_critic_attempts')}")
    if r.get('semantic_gate_failure'): print(f"     SEMANTIC GATE FAILURE: {r.get('semantic_gate_failure')}")
    print(f"     validate_err: {r.get('validate_err')}\n     score_clears_floor: {r.get('score_clears_floor')}\n     score_script: {r.get('score')}\n     critic_avg: {r.get('critic_avg')}")
    print(f"     scorer disagreement: band={quality.get('disagreement_band')} mapped_mean_abs={quality.get('mean_abs_mapped_delta')} mapped_max_abs={quality.get('max_abs_mapped_delta')}")
    print(f"     editorial telemetry: warnings={editorial.get('warning_kinds')} hook_words={editorial.get('hook_word_count')} hook_payoff_overlap={editorial.get('hook_payoff_overlap')}")
    sig=shape.get('signature') or {}; f8=shape.get('first_8_seconds') or {}
    print(f"     story shape: primary={sig.get('primary_sequence')} unique_functions={sig.get('unique_function_count')}")
    print(f"     first 8s: hook_est={f8.get('hook_estimated_seconds')}s fully_heard_beats_after_hook={f8.get('fully_heard_beats_after_hook')} functions={f8.get('opening_primary_functions')} warnings={f8.get('warnings')}")
    print(f"     payoff proof: opening_overlap={payoff.get('opening_payoff_overlap')} resolution_cue={payoff.get('resolution_cue_present')} warnings={payoff.get('warnings')}")
    cv=r.get('critic_verdict')
    if cv: print(f"     critic claim_support: {cv.get('claim_support')}\n     critic diagnosis: {cv.get('diagnosis')}\n     critic requested repair={cv.get('repair_type')} targets={cv.get('target_beats')}")
    hard=[v for v in (r.get('violations') or []) if v.get('severity')=='hard']
    if hard:
        print('     HARD violations:')
        for v in hard[:12]: print(f"       beat {v.get('beat_index')}: {v.get('kind')} {v.get('value')!r} cited={v.get('cited_claim_ids')}")
    print(f"     repair plan: {r.get('repair_plan')}")

def _render_manifest_story(m):
    scenes=list(m.get('scenes') or [])
    print('  FINAL RENDER-MANIFEST STORY:')
    for s in scenes: print(f"    scene {s.get('id')} [{s.get('_v2_role') or 'scene'}] {s.get('voiceover')} claims={s.get('source_claim_ids')} query={s.get('search_query')!r}")
    hp=HP.manifest_hook_payoff_report(m)
    print(f"    HOOK SURFACES: {json.dumps(hp['hook_surfaces'],ensure_ascii=False,sort_keys=True)}")
    print(f"    PAYOFF PROOF: {json.dumps(hp['payoff_proof'],ensure_ascii=False,sort_keys=True)}")
    print(f"    script={m.get('script')}\n    semantic_verified={m.get('_semantic_verified')}")

def run_topic(tid,fact):
    print(f"\n{'#'*88}\n# TOPIC: {tid} ({fact.get('domain')})\n# FACT: {fact.get('fact')}\n{'#'*88}")
    manifest,debug=O.generate_candidate_v21(fact,job_name='CURIOSITY_ITCH',recent_treatments=[],avoid_topics='none',cta_style='SAVE_WORTHY',use_structured=True)
    q=Q.analyze_debug(debug); regression=RR.analyze_debug(debug); pairs=P.pairwise_plans_from_debug(debug)
    rounds=list(debug.get('rounds') or []); qr=list(q.get('rounds') or [])
    for i,r in enumerate(rounds):
        qual=qr[i] if i<len(qr) else Q.quality_signal_report(r.get('score'),r.get('critic_verdict'))
        _print_round(r,qual,_editorial_for_round(r),_shape_for_round(r),_hp_for_round(r,fact))
    print(f"  QUALITY SIGNAL SUMMARY: {json.dumps(q,sort_keys=True)}\n  REPAIR REGRESSION SUMMARY: {json.dumps(regression,ensure_ascii=False,sort_keys=True)}\n  BLIND PAIRWISE PLANS: {len(pairs)} eligible clean transition(s); prompts prepared but NOT called by this runner")
    print(f"  ACCEPTED: {debug.get('accepted')} error={debug.get('error')!r}")
    if manifest: _render_manifest_story(manifest)
    else: print(f"  ABORTED: validate_err={debug.get('validate_err')!r}")
    last=rounds[-1] if rounds else {}; ed=_editorial_for_round(last) if last else {}; sh=_shape_for_round(last) if last else {}; pp=_hp_for_round(last,fact) if last else {}
    return {"topic":tid,"treatment":debug.get('treatment'),"accepted":bool(debug.get('accepted')),"score":debug.get('score'),"calls":debug.get('total_calls'),"quality_signal":q,"repair_regression":regression,"pairwise_plan_count":len(pairs),"final_editorial_warning_kinds":ed.get('warning_kinds') or [],"final_story_shape":(sh.get('signature') or {}).get('primary_sequence'),"final_first8_warnings":(sh.get('first_8_seconds') or {}).get('warnings') or [],"final_payoff_warnings":pp.get('warnings') or [],"error":debug.get('error')}

def main():
    bank={f['id']:f for f in G.load_bank()}; results=[]
    print('WRITER V2.1 TAKEOVER TORTURE PANEL — SCRIPT ONLY / NO RENDER / NO PUBLISH')
    for idx,tid in enumerate(TOPIC_IDS):
        if idx and INTER_TOPIC_DELAY_SECONDS>0: time.sleep(INTER_TOPIC_DELAY_SECONDS)
        if tid in bank: results.append(run_topic(tid,bank[tid]))
    print(f"\n{'='*88}\nSUMMARY\n{'='*88}")
    for r in results: print(f"{r['topic']}: treatment={r['treatment']} accepted={r['accepted']} score={r['score']} calls={r['calls']} judge_disagreement={r['quality_signal'].get('max_disagreement_band')} repair_regressions={r['repair_regression'].get('all_regression_flag_kinds')} editorial={r['final_editorial_warning_kinds']} first8={r['final_first8_warnings']} payoff={r['final_payoff_warnings']} shape={r['final_story_shape']} error={r['error']!r}")
    print(f"accepted={sum(1 for r in results if r['accepted'])}/{len(results)} — NOT a promotion verdict until human editorial review")
    return 0
if __name__=='__main__': sys.exit(main())
