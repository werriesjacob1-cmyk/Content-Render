#!/usr/bin/env python3
"""Zero-network regressions for writer_story_bridge.py."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_story_bridge as B


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def inventory(grounded=False):
    return {
        "grounded": grounded,
        "provenance_note": "test",
        "claims": [
            {
                "claim_id": "base_001",
                "claim_text": "A mantis shrimp can perceive polarized light.",
                "source_kind": "base_fact",
                "source_ref": "topic_bank.fact",
                "confidence": "verified_base_fact",
                "allowed_numbers": [],
                "allowed_entities": ["Mantis Shrimp"],
            },
            {
                "claim_id": "dossier_001",
                "claim_text": "Researchers use polarization sensitivity to study mantis shrimp vision.",
                "source_kind": "grounded_dossier" if grounded else "base_fact",
                "source_ref": "research_dossier.grounded" if grounded else "research_dossier.ungrounded_opt_out",
                "confidence": "grounded" if grounded else "verified_base_fact",
                "allowed_numbers": [],
                "allowed_entities": [],
            },
        ],
    }


def test_exact_claim_ids_survive_bridge():
    packet = B.from_writer_inventory("mantis_shrimp", inventory(True))
    check([c.claim_id for c in packet.claims] == ["base_001", "dossier_001"],
          "Writer V2.1 claim IDs survive unchanged")
    check(packet.claims[0].text == "A mantis shrimp can perceive polarized light.",
          "claim text survives unchanged")
    check(packet.grounding_mode == "grounded_writer_dossier", "grounded inventory stays honestly grounded")
    check(any(s.source_type == "grounded_dossier" for s in packet.sources),
          "grounded dossier source kind survives without being relabeled curated")


def test_curated_inventory_is_not_upgraded():
    packet = B.from_writer_inventory("mantis_shrimp", inventory(False))
    check(packet.grounding_mode == "curated_base_fact", "base-only inventory is not upgraded to web grounding")
    check(all(s.source_type == "curated_base_fact" for s in packet.sources),
          "base-only sources remain curated-base-fact provenance")


def test_manifest_reference_verification_fails_closed():
    packet = B.from_writer_inventory("mantis_shrimp", inventory(True))
    manifest = {
        "_semantic_verified": True,
        "hook_source_claim_ids": ["base_001"],
        "scenes": [
            {"source_claim_ids": ["base_001"]},
            {"source_claim_ids": ["dossier_001"]},
        ],
        "payoff_source_claim_ids": ["dossier_001"],
    }
    ok, problems = B.verify_manifest_refs(manifest, packet)
    check(ok and not problems, "known manifest claim refs pass")

    bad = dict(manifest)
    bad["scenes"] = [{"source_claim_ids": ["invented_999"]}]
    ok, problems = B.verify_manifest_refs(bad, packet)
    check(not ok and any("unknown Writer claim ID invented_999" in p for p in problems),
          "unknown manifest claim ref fails closed")

    unverified = dict(manifest)
    unverified["_semantic_verified"] = False
    ok, problems = B.verify_manifest_refs(unverified, packet)
    check(not ok and any("semantic_verified" in p for p in problems),
          "manifest without canonical semantic acceptance fails closed")


def test_empty_or_duplicate_inventory_is_rejected():
    try:
        B.from_writer_inventory("x", {"claims": []})
    except ValueError:
        pass
    else:
        raise AssertionError("empty inventory must reject")
    dup = inventory(False)
    dup["claims"].append(dict(dup["claims"][0]))
    try:
        B.from_writer_inventory("x", dup)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate Writer claim ID must reject")
    check(True, "empty/duplicate Writer inventories reject")


if __name__ == "__main__":
    test_exact_claim_ids_survive_bridge()
    test_curated_inventory_is_not_upgraded()
    test_manifest_reference_verification_fails_closed()
    test_empty_or_duplicate_inventory_is_rejected()
    print("writer_story_bridge tests: PASS")
