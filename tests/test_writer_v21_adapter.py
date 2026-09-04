#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import story_packet as SP
import writer_v21_adapter as A

def check(cond,label):
    if not cond: raise AssertionError(label)
    print(f"PASS {label}")

def v21_inventory():
    return {"claims":[{"claim_id":"base_001","claim_text":"A day on Venus lasts 243 Earth days.","source_kind":"base_fact","source_ref":"topic_bank.fact","confidence":"verified_base_fact","allowed_numbers":["243"],"allowed_units":["days"],"allowed_entities":["Venus","Earth"],"allowed_terms":["venus","lasts","earth","days"]},{"claim_id":"dossier_001","claim_text":"NASA observations show Venus rotates very slowly.","source_kind":"grounded_dossier","source_ref":"research_dossier.grounded","confidence":"grounded","allowed_numbers":[],"allowed_units":[],"allowed_entities":["NASA","Venus"],"allowed_terms":["nasa","observations","venus","rotates","slowly"]}],"key_terms":["Venus","rotation"],"grounded":True,"provenance_note":"grounded via live Google Search"}

def accepted_debug():
    return {"accepted":True,"score":8.1,"validate_err":None,"repair_rounds":1,"total_calls":4,"rounds":[{"round":0,"semantic_verified":True,"mechanical_hard_count":1,"semantic_violation_count":0,"violations":[{"severity":"hard"},{"severity":"soft"}],"validate_err":None,"score":7.8},{"round":1,"semantic_verified":True,"mechanical_hard_count":0,"semantic_violation_count":0,"violations":[],"validate_err":None,"score":8.1}]}

def manifest(semantic=True):
    return {"title":"Venus","hook":"Venus makes a single day last 243 Earth days.","hook_source_claim_ids":["base_001"],"payoff":"That slow rotation changes what a day means there.","payoff_source_claim_ids":["dossier_001"],"_semantic_verified":semantic,"scenes":[{"id":1,"voiceover":"A day on Venus lasts 243 Earth days.","search_query":"Venus slow rotation","source_claim_ids":["base_001"]},{"id":2,"voiceover":"NASA observations show Venus rotates very slowly.","search_query":"Venus rotation planet","source_claim_ids":["dossier_001"]}]}

def test_inventory_roundtrip():
    p=A.story_packet_from_v21_inventory("venus_day",v21_inventory()); check([c.claim_id for c in p.claims]==["base_001","dossier_001"],"claim IDs preserved"); check(all(not s.url for s in p.sources),"no fake URLs")
    web=SP.StoryPacket("plume",(SP.StoryClaim("c","NASA measured 12 kilometers.",( "s",),"grounded",allowed_numbers=("12",)),),(SP.StorySource("s","web","NASA","https://science.nasa.gov/example",("12 kilometers",)),),"grounded_web")
    inv=A.v21_inventory_from_story_packet(web); check(inv["claims"][0]["source_urls"]==["https://science.nasa.gov/example"],"exact URL preserved")

def test_semantic_acceptance_is_fail_closed():
    d=accepted_debug(); m=manifest(True); check(A.accepted_traceability(d,m),"takeover semantic proof accepted")
    check(not A.accepted_traceability(d,manifest(False)),"manifest without semantic proof rejected")
    legacy=dict(d); legacy["rounds"]=[dict(r,semantic_verified=False) for r in d["rounds"]]; check(not A.accepted_traceability(legacy,m),"Claude-era acceptance alone rejected")
    check(not A.accepted_traceability(d,None),"missing manifest proof rejected")
    bad=dict(d,accepted=False); check(not A.accepted_traceability(bad,m),"aborted run rejected")

def test_session_boundary():
    good=A.session_from_v21(manifest(True),v21_inventory(),accepted_debug(),"venus_day"); check(good.traceability_ready,"semantically verified candidate reaches quality stack")
    bad=A.session_from_v21(manifest(False),v21_inventory(),accepted_debug(),"venus_day"); check(not bad.traceability_ready,"unverified candidate blocked before quality stack")

if __name__=="__main__":
    test_inventory_roundtrip(); test_semantic_acceptance_is_fail_closed(); test_session_boundary(); print("writer_v21_adapter tests: PASS")
