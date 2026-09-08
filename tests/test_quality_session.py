#!/usr/bin/env python3
"""Zero-network tests for quality_session.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_session as QS
import story_packet as SP


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def story():
    return SP.from_curated_fact({
        "id": "venus_day",
        "fact": "A day on Venus lasts 243 Earth days.",
        "wow": "Venus rotates extremely slowly.",
    })


def test_v21_claim_bound_manifest_passes_new_preflight():
    packet = story()
    c0 = packet.claims[0].claim_id
    c1 = packet.claims[-1].claim_id
    manifest = {
        "title": "Venus day",
        "hook": "Venus makes one day last longer than you expect.",
        "hook_source_claim_ids": [c0],
        "payoff": "That slow rotation changes what a day means there.",
        "payoff_source_claim_ids": [c1],
        "scenes": [
            {
                "id": "1",
                "voiceover": "A day on Venus lasts 243 Earth days.",
                "search_query": "Venus slow rotation planet",
                "source_claim_ids": [c0],
            },
            {
                "id": "2",
                "voiceover": "That happens because Venus rotates extremely slowly.",
                "search_query": "Venus rotating globe animation",
                "source_claim_ids": [c1],
            },
        ],
    }
    plan = QS.build_session_plan(manifest, packet, upstream_traceability_passed=True)
    check(plan.provider_calls_made == 0 and not plan.publishing_enabled,
          "session assembly is zero-call and cannot publish")
    check(plan.hook_binding.traceability_bound and plan.payoff_binding.traceability_bound,
          "V2.1 hook and payoff evidence IDs survive the handoff")
    check(all(x.traceability_bound for x in plan.scenes), "every factual scene binds to a known story claim ID")
    check(plan.traceability_ready, "accepted V2.1 evidence chain is ready end to end")
    ok, reasons = QS.render_preflight(plan)
    check(ok and not reasons, "accepted fully claim-bound V2.1 manifest can pass new-stack preflight")


def test_v21_connective_line_can_have_empty_ids_only_after_upstream_pass():
    packet = story()
    c0 = packet.claims[0].claim_id
    manifest = {
        "title": "Connective",
        "hook": "A day on Venus lasts 243 Earth days.",
        "hook_source_claim_ids": [c0],
        "payoff": "So what does that mean?",
        "payoff_source_claim_ids": [],
        "scenes": [{
            "id": "1", "voiceover": "So what happens next?",
            "search_query": "Venus planet rotation", "source_claim_ids": [],
        }],
    }
    trusted = QS.build_session_plan(manifest, packet, upstream_traceability_passed=True)
    check(trusted.scenes[0].traceability_bound and trusted.payoff_binding.traceability_bound,
          "empty IDs are accepted when V2.1 already certified connective/editorial meaning")
    untrusted = QS.build_session_plan(manifest, packet, upstream_traceability_passed=None)
    check(not untrusted.scenes[0].traceability_bound and not untrusted.payoff_binding.traceability_bound,
          "integration layer never self-declares an uncited line connective without V2.1 verdict")


def test_legacy_unbound_manifest_is_visible_not_silently_trusted():
    packet = story()
    manifest = {
        "title": "Legacy",
        "hook": "A day on Venus lasts 243 Earth days.",
        "scenes": [{
            "id": "1",
            "voiceover": "A day on Venus lasts 243 Earth days.",
            "search_query": "Venus planet rotation",
        }],
    }
    plan = QS.build_session_plan(manifest, packet)
    check(not plan.scenes[0].traceability_bound, "legacy scene without claim IDs is marked unbound")
    check("no source_claim_ids" in plan.scenes[0].traceability_error, "traceability gap is explicit")
    ok, reasons = QS.render_preflight(plan)
    check(not ok and any("V2.1" in x or "claim" in x for x in reasons),
          "legacy manifest cannot enter strict new-stack preflight without V2.1 evidence verdict")


def test_unknown_claim_reference_fails_closed_even_if_upstream_flag_is_true():
    packet = story()
    c0 = packet.claims[0].claim_id
    manifest = {
        "title": "Bad ref",
        "hook": "A day on Venus lasts 243 Earth days.",
        "hook_source_claim_ids": [c0],
        "payoff": "So what does that mean?",
        "payoff_source_claim_ids": [],
        "scenes": [{
            "id": "1",
            "voiceover": "A day on Venus lasts 243 Earth days.",
            "search_query": "Venus planet rotation",
            "source_claim_ids": ["claim_invented"],
        }],
    }
    plan = QS.build_session_plan(manifest, packet, upstream_traceability_passed=True)
    check(not plan.scenes[0].traceability_bound, "invented claim ID does not bind")
    check(any("unknown source_claim_id" in x for x in plan.blockers),
          "unknown claim ID stays a blocker even when upstream claims acceptance")


if __name__ == "__main__":
    test_v21_claim_bound_manifest_passes_new_preflight()
    test_v21_connective_line_can_have_empty_ids_only_after_upstream_pass()
    test_legacy_unbound_manifest_is_visible_not_silently_trusted()
    test_unknown_claim_reference_fails_closed_even_if_upstream_flag_is_true()
    print("quality_session tests: PASS")
