#!/usr/bin/env python3
"""SCRIPT-ONLY BAKEOFF -- WRITER_V2 mission, 2026-09-03. NOT part of the
production pipeline: no render, no publish, no manifest saved. For each of 3
topics (from substantially different domains, chosen by
writer_v2.rank_topics_by_visual_score, not arbitrarily), generates:
  A. a LEGACY reference script -- the real production build_prompt() sent
     through the real production call_groq() provider chain (whatever
     actually carries it today: Gemini/OpenRouter are known down, Groq's
     gpt-oss-120b is known too small a TPM cap for this prompt -- so this is
     realistically testing Mistral, or reporting an honest failure).
  B. a V2 script via generate_candidate_v2() (treatment selection, compact
     story packet, lean prompt, structured output on Groq gpt-oss-120b --
     confirmed live-working in wr2_recon.py's run 33787937760).
Both are scored through the SAME validate()/score_script() gate -- the bar
is not touched. Prints full scripts + all debug metadata (treatment,
provenance, provider/model, token sizes, real usage, score) for side-by-side
human judgment. Nothing here is saved or fed back into memory/queue files.
"""
import json
import sys

import generate as G
import writer_v2 as W2

TOPIC_IDS = ["tardigrade", "neutron_star_spoon", "stomach_lining"]


def _print_manifest(label, m, debug):
    print(f"\n----- {label} -----")
    print(json.dumps(debug, indent=2, default=str))
    if m is None:
        print("(no usable manifest produced)")
        return
    print(f"\nTITLE: {m.get('title')}")
    print(f"HOOK: {m.get('hook')}")
    print(f"TREATMENT: {m.get('treatment', '(legacy -- no treatment concept)')}")
    print("SCENES:")
    for s in m.get("scenes", []):
        print(f"  [{s.get('id')}] ({s.get('search_query')!r}) {s.get('voiceover')}")
    if m.get("payoff"):
        print(f"PAYOFF: {m['payoff']}")
    print(f"WORD COUNT: {len(m.get('script', '').split())}")


def run_legacy(fact, dossier):
    prompt = G.build_prompt("CURIOSITY_ITCH", G.VIEWER_JOBS[0][1], "none", fact=fact,
                            avoid_openers=None, cta_style="SAVE_WORTHY",
                            dossier=dossier, hook_frame=G.HOOK_FRAMES[0])
    debug = {"prompt_chars": len(prompt), "prompt_tokens_est": G.estimate_tokens(prompt)}
    try:
        raw = G.call_groq(prompt)
    except Exception as e:  # noqa: BLE001
        debug["error"] = f"{type(e).__name__}: {e}"
        debug["provider_model"] = list(G._WORKING_MODEL) if G._WORKING_MODEL else None
        return None, debug
    debug["provider_model"] = list(G._WORKING_MODEL) if G._WORKING_MODEL else None
    try:
        m = json.loads(raw)
        if not isinstance(m, dict):
            raise ValueError(f"model returned a {type(m).__name__}, not an object")
    except Exception as e:  # noqa: BLE001
        debug["error"] = f"JSON parse failed: {e}"
        debug["raw"] = (raw or "")[:500]
        return None, debug
    err = G.validate(m, "CURIOSITY_ITCH", fact=fact)
    debug["validate_err"] = err
    if err:
        return None, debug
    debug["score"] = G.score_script(m, fact=fact, cta_style="SAVE_WORTHY")
    return m, debug


def main():
    bank = {f["id"]: f for f in G.load_bank()}
    print(f"BAKEOFF TOPICS: {TOPIC_IDS}\n")

    for tid in TOPIC_IDS:
        fact = bank.get(tid)
        if not fact:
            print(f"!! topic {tid} not found in bank, skipping")
            continue
        print(f"\n{'#' * 78}\n# TOPIC: {tid}  ({fact['domain']})\n# fact: {fact['fact']}\n{'#' * 78}")

        vscore = W2.visual_scout_score(fact, banned_re=G.UNSTOCKABLE_Q)
        print(f"visual_scout_score: {json.dumps(vscore)}")

        dossier = G.research_dossier(fact)
        print(f"research_dossier(): {len(dossier)} facts (grounded={bool(dossier)})")

        m_legacy, d_legacy = run_legacy(fact, dossier)
        _print_manifest("A. LEGACY (real build_prompt + call_groq chain)", m_legacy, d_legacy)

        m_v2, d_v2 = G.generate_candidate_v2(fact, job_name="CURIOSITY_ITCH",
                                             recent_treatments=[], avoid_topics="none",
                                             cta_style="SAVE_WORTHY", use_structured=True)
        _print_manifest("B. V2 (writer_v2 treatment + packet + structured output)", m_v2, d_v2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
