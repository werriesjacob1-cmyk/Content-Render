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


def test_claim_bound_manifest_passes_new_preflight():
    packet = story()
    cid = packet.claims[0].claim_id
    manifest = {
        "title": "Venus day",
        "scenes": [
            {
                "id": "1",
                "voiceover": "A day on Venus lasts 243 Earth days.",
                "search_query": "Venus slow rotation planet",
                "source_claim_ids": [cid],
            },
            {
                "id": "2",
                "voiceover": "That happens because Venus rotates extremely slowly.",
                "search_query": "Venus rotating globe animation",
                "source_claim_ids": [packet.claims[-1].claim_id],
            },
        ],
    }
    plan = QS.build_session_plan(manifest, packet)
    check(plan.provider_calls_made == 0 and not plan.publishing_enabled,
          "session assembly is zero-call and cannot publish")
    check(all(x.traceability_bound for x in plan.scenes), "every scene binds to a known story claim ID")
    ok, reasons = QS.render_preflight(plan)
    check(ok and not reasons, "fully claim-bound manifest can pass new-stack render preflight")
    check(plan.writer_claim_payload["grounding_mode"] == "curated_base_fact",
          "writer evidence mode survives into session plan")


def test_legacy_unbound_manifest_is_visible_not_silently_trusted():
    packet = story()
    manifest = {
        "title": "Legacy",
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
    check(not ok and any("claim" in x for x in reasons), "unbound legacy manifest cannot enter strict new-stack render preflight")


def test_unknown_claim_reference_fails_closed():
    packet = story()
    manifest = {
        "title": "Bad ref",
        "scenes": [{
            "id": "1",
            "voiceover": "A day on Venus lasts 243 Earth days.",
            "search_query": "Venus planet rotation",
            "source_claim_ids": ["claim_invented"],
        }],
    }
    plan = QS.build_session_plan(manifest, packet)
    check(not plan.scenes[0].traceability_bound, "invented claim ID does not bind")
    check(any("unknown source_claim_id" in x for x in plan.blockers), "unknown claim ID becomes a preflight blocker")


if __name__ == "__main__":
    test_claim_bound_manifest_passes_new_preflight()
    test_legacy_unbound_manifest_is_visible_not_silently_trusted()
    test_unknown_claim_reference_fails_closed()
    print("quality_session tests: PASS")
