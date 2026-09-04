#!/usr/bin/env python3
"""Zero-network contract tests against Claude Writer V2.1's current schema."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import story_packet as SP
import writer_v21_adapter as A


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def v21_inventory():
    return {
        "claims": [
            {
                "claim_id": "base_001",
                "claim_text": "A day on Venus lasts 243 Earth days.",
                "source_kind": "base_fact",
                "source_ref": "topic_bank.fact",
                "confidence": "verified_base_fact",
                "allowed_numbers": ["243"],
                "allowed_units": ["days"],
                "allowed_entities": ["Venus", "Earth"],
                "allowed_terms": ["venus", "lasts", "earth", "days"],
            },
            {
                "claim_id": "dossier_001",
                "claim_text": "NASA observations show Venus rotates very slowly.",
                "source_kind": "grounded_dossier",
                "source_ref": "research_dossier.grounded",
                "confidence": "grounded",
                "allowed_numbers": [],
                "allowed_units": [],
                "allowed_entities": ["NASA", "Venus"],
                "allowed_terms": ["nasa", "observations", "venus", "rotates", "slowly"],
            },
        ],
        "key_terms": ["Venus", "rotation"],
        "grounded": True,
        "provenance_note": "grounded via live Google Search",
    }


def accepted_debug():
    return {
        "accepted": True,
        "score": 8.1,
        "validate_err": None,
        "repair_rounds": 1,
        "total_calls": 4,
        "rounds": [
            {
                "round": 0,
                "mechanical_hard_count": 1,
                "semantic_violation_count": 0,
                "violations": [
                    {"beat_index": 1, "kind": "unsupported_number", "value": "999",
                     "severity": "hard", "cited_claim_ids": ["base_001"], "detail": "unsupported"},
                    {"beat_index": 2, "kind": "unsupported_term", "value": "quietly",
                     "severity": "soft", "cited_claim_ids": ["dossier_001"], "detail": "telemetry"},
                ],
                "validate_err": None,
                "score": 7.8,
                "critic_avg": 7.2,
                "repair_plan": {"tier": 1, "repair_type": "PROVENANCE", "target_beats": [1]},
            },
            {
                "round": 1,
                "mechanical_hard_count": 0,
                "semantic_violation_count": 0,
                "violations": [],
                "validate_err": None,
                "score": 8.1,
                "critic_avg": 8.0,
                "repair_plan": {"tier": 3, "repair_type": "NONE", "target_beats": []},
            },
        ],
    }


def test_v21_inventory_to_story_packet_preserves_ids_without_fake_urls():
    packet = A.story_packet_from_v21_inventory("venus_day", v21_inventory())
    check([c.claim_id for c in packet.claims] == ["base_001", "dossier_001"],
          "V2.1 claim IDs survive unchanged")
    check(packet.grounding_mode == "writer_v21_grounded_dossier_text",
          "current V2.1 grounded dossier is labeled as grounded text, not exact URL provenance")
    check(all(not s.url for s in packet.sources),
          "adapter never invents source URLs absent from Claude's current inventory")
    check(packet.require_claim_ids(["base_001"])[0].text.startswith("A day on Venus"),
          "session can resolve Claude claim IDs mechanically")


def test_exact_source_story_packet_can_feed_v21_schema():
    packet = SP.StoryPacket(
        "plume",
        claims=(SP.StoryClaim(
            "claim_web_001",
            "NASA measured the plume at 12 kilometers.",
            ("src_1",),
            "grounded",
            allowed_numbers=("12",),
            allowed_named_entities=("NASA",),
        ),),
        sources=(SP.StorySource(
            "src_1", "web", "NASA study", "https://science.nasa.gov/example",
            ("The plume reached approximately 12 kilometers.",),
        ),),
        grounding_mode="grounded_web",
    )
    inv = A.v21_inventory_from_story_packet(packet, key_terms=["plume"])
    row = inv["claims"][0]
    check(inv["grounded"] is True and row["source_kind"] == "grounded_story_packet",
          "exact web-grounded packet stays grounded in V2.1 inventory")
    check(row["source_urls"] == ["https://science.nasa.gov/example"],
          "exact source URL survives into the V2.1-compatible inventory")
    check("12" in row["allowed_numbers"] and "kilometers" in row["allowed_units"],
          "V2.1 mechanical number/unit vocabulary is populated")
    check(row["claim_id"] == "claim_web_001" and row["claim_text"] == packet.claims[0].text,
          "conversion never rewrites or renumbers evidence claims")


def test_debug_acceptance_uses_claudes_actual_clean_candidate_contract():
    good = accepted_debug()
    check(A.accepted_traceability(good),
          "accepted=True + score + no validate error is recognized as V2.1 accepted output")
    summary = A.debug_traceability_summary(good)
    check(summary["hard_total"] == 1 and summary["soft_total"] == 1,
          "hard and soft telemetry stay distinct across repair rounds")
    bad = dict(good, accepted=False)
    check(not A.accepted_traceability(bad), "aborted V2.1 run cannot certify downstream traceability")
    bad2 = dict(good, validate_err="scene 2 jargon")
    check(not A.accepted_traceability(bad2), "validate failure cannot certify downstream traceability")


def test_v21_manifest_hook_scene_payoff_passes_session_adapter():
    inv = v21_inventory()
    manifest = {
        "title": "Venus",
        "hook": "Venus makes a single day last 243 Earth days.",
        "hook_source_claim_ids": ["base_001"],
        "payoff": "That slow rotation changes what a day means there.",
        "payoff_source_claim_ids": ["dossier_001"],
        "scenes": [
            {"id": 1, "voiceover": "A day on Venus lasts 243 Earth days.",
             "search_query": "Venus slow rotation", "source_claim_ids": ["base_001"]},
            {"id": 2, "voiceover": "NASA observations show Venus rotates very slowly.",
             "search_query": "Venus rotation planet", "source_claim_ids": ["dossier_001"]},
        ],
    }
    session = A.session_from_v21(manifest, inv, accepted_debug(), "venus_day")
    check(session.traceability_ready, "actual V2.1 hook/scene/payoff citation shape plugs into quality session")
    check(session.hook_binding.source_claim_ids == ("base_001",),
          "hook provenance survives adapter")
    check(session.payoff_binding.source_claim_ids == ("dossier_001",),
          "payoff provenance survives adapter")


if __name__ == "__main__":
    test_v21_inventory_to_story_packet_preserves_ids_without_fake_urls()
    test_exact_source_story_packet_can_feed_v21_schema()
    test_debug_acceptance_uses_claudes_actual_clean_candidate_contract()
    test_v21_manifest_hook_scene_payoff_passes_session_adapter()
    print("writer_v21_adapter tests: PASS")
