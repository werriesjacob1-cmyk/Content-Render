#!/usr/bin/env python3
"""Zero-network tests for story_packet.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research_grounding as RG
import story_packet as SP


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_grounded_bundle_preserves_claim_ids_and_sources():
    payload = {
        "answer": "NASA measured the plume at 12 kilometers. [[1]]",
        "citations": [{
            "source": "https://science.nasa.gov/example",
            "excerpts": ["The observed plume reached approximately 12 kilometers in altitude."],
        }],
        "results": {"web": [{
            "url": "https://science.nasa.gov/example",
            "title": "NASA Example Study",
        }]},
    }
    bundle = RG.parse_you_answer(payload, "plume altitude")
    packet = SP.from_research(bundle, "plume_story")
    check(packet.grounding_mode == "grounded_web", "grounded research stays explicitly web-grounded")
    check(len(packet.claims) == 1 and len(packet.sources) == 1, "one cited claim maps to one verifiable source")
    check(packet.claims[0].claim_id == bundle.claims[0].claim_id, "research claim ID survives into writer/visual story packet unchanged")
    check("12" in packet.claims[0].allowed_numbers, "supported magnitude is exposed mechanically")
    check(packet.sources[0].excerpts, "source excerpts survive for later audit")


def test_curated_fallback_is_honest_not_fake_grounding():
    fact = {
        "id": "venus_day",
        "fact": "A day on Venus lasts 243 Earth days.",
        "whatif": "What would a sunrise feel like there?",
        "wow": "Venus rotates extremely slowly.",
    }
    packet = SP.from_curated_fact(fact)
    check(packet.grounding_mode == "curated_base_fact", "topic-bank fallback is labeled curated, not web-grounded")
    check(packet.sources[0].source_type == "curated_base_fact" and not packet.sources[0].url,
          "curated fallback never fabricates a source URL")
    fact_claim = next(c for c in packet.claims if "243" in c.text)
    check("243" in fact_claim.allowed_numbers, "curated fact supports its own named number")
    check(all(c.source_ids == ("base:venus_day",) for c in packet.claims),
          "every fallback claim points to the explicit base-fact provenance ID")


def test_writer_payload_is_compact_claim_registry_not_mega_prompt():
    packet = SP.from_curated_fact({
        "id": "test",
        "fact": "The Empire State Building is 381 meters tall.",
    })
    payload = SP.writer_payload(packet)
    row = payload["claims"][0]
    check(set(row) == {
        "claim_id", "claim_text", "source_ids", "confidence",
        "allowed_numbers", "allowed_named_entities",
    }, "writer payload exposes only evidence fields needed for claim binding")
    check("381" in row["allowed_numbers"], "writer receives exact supported number")
    check(any("Empire State Building" in x for x in row["allowed_named_entities"]),
          "writer receives supported named comparison entity")
    try:
        packet.require_claim_ids(["claim_does_not_exist"])
        raise AssertionError("unknown claim ID should fail")
    except ValueError as exc:
        check("unknown source_claim_id" in str(exc), "unknown writer/visual claim references fail closed")


if __name__ == "__main__":
    test_grounded_bundle_preserves_claim_ids_and_sources()
    test_curated_fallback_is_honest_not_fake_grounding()
    test_writer_payload_is_compact_claim_registry_not_mega_prompt()
    print("story_packet tests: PASS")
