#!/usr/bin/env python3
"""Zero-network adversarial tests for symmetric factual auditing in Mission 2."""
from __future__ import annotations

import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import writer_v21_quality_bakeoff as Q  # noqa: E402
import writer_v21_factual_audit as F  # noqa: E402

PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def result(topic, side, script, evidence):
    return {
        "topic_id": topic,
        "side": side,
        "script": script,
        "generated": True,
        "validate_clean": True,
        "integrity_clean": True if side == "v21" else None,
        "semantic_verified": True if side == "v21" else None,
        "treatment": "HIDDEN_MECHANISM" if side == "v21" else "",
        "draft_provider_model": "same/model",
        "calls": 1,
        "repair_regression_flags": [],
        "source_evidence": list(evidence),
        "source_evidence_sha256": F.evidence_sha256(evidence),
    }


def mapped_editorial(topic, winner="v21"):
    return {
        "pair_id": f"pair_{topic}",
        "topic_id": topic,
        "winner_side": winner,
        "confidence": "HIGH",
        "criterion_winner_sides": {c: winner for c in Q.CRITERIA},
        "postable_by_side": {"v21": True, "legacy": True},
        "same_draft_model": True,
        "decisive_reasons": ["stronger"],
    }


def factual_mapped(topic, *, legacy="CLEAN", v21="CLEAN"):
    return {
        "pair_id": f"pair_{topic}",
        "topic_id": topic,
        "by_side": {
            "legacy": {"status": legacy, "unsupported_propositions": [], "notes": []},
            "v21": {"status": v21, "unsupported_propositions": [], "notes": []},
        },
    }


def promotion_rows():
    rows = []
    treatments = ["A", "B", "C", "D", "E", "F"]
    for i in range(12):
        evidence = [f"BASE_FACT: fact t{i}", f"DOSSIER: support t{i}"]
        rows.append(result(f"t{i}", "legacy", f"Legacy anonymous script {i}.", evidence))
        row = result(f"t{i}", "v21", f"New anonymous script {i}.", evidence)
        row["treatment"] = treatments[i % len(treatments)]
        rows.append(row)
    return rows


def main():
    fact = {"id": "x", "fact": "Water expands when it freezes.", "wow": "Ice is less dense."}
    evidence = F.build_source_evidence(fact, ["A cited mechanism explains the lattice."])
    check(evidence[0] == "BASE_FACT: Water expands when it freezes.", "source packet starts from frozen base fact")
    check(F.evidence_sha256(evidence) == F.evidence_sha256(list(evidence)), "source evidence hash is deterministic")

    rows = [
        result("x", "legacy", "Anonymous script one.", evidence),
        result("x", "v21", "Anonymous script two.", evidence),
    ]
    packets, keys, excluded = Q.build_blind_packets(rows, seed="factual-test")
    check(len(packets) == len(keys) == 1 and not excluded, "clean generation pair reaches blind factual audit")
    factual_packets = F.build_factual_packets(rows, keys)
    check(len(factual_packets) == 1, "one paired factual packet is built")
    packet = factual_packets[0]
    check(packet["packet_sha256"] == F.packet_sha256(packet), "factual packet self-hash binds scripts and source evidence")
    text = str(packet).lower()
    check("'side':" not in text and "'aliases':" not in text and "writer v2.1" not in text,
          "factual public packet does not expose hidden system identity")
    prompt = F.build_factual_prompt(packet)
    check(packet["packet_sha256"] in prompt, "factual judge prompt carries exact packet binding")

    keys[0]["factual_packet_sha256"] = packet["packet_sha256"]
    clean = {
        "pair_id": packet["pair_id"],
        "packet_sha256": packet["packet_sha256"],
        "status_A": "CLEAN",
        "status_B": "CLEAN",
        "unsupported_propositions_A": [],
        "unsupported_propositions_B": [],
        "notes_A": [],
        "notes_B": [],
    }
    mapped = F.map_factual_verdict(clean, keys[0])
    check(set(mapped["by_side"]) == {"legacy", "v21"}, "factual verdict maps identity only after blind audit")

    wrong_hash = dict(clean, packet_sha256="0" * 64)
    try:
        F.map_factual_verdict(wrong_hash, keys[0])
    except F.FactualAuditError:
        check(True, "stale factual verdict packet hash fails closed")
    else:
        check(False, "stale factual verdict must fail")

    unsupported_without_claim = dict(clean, status_A="UNSUPPORTED")
    try:
        F.parse_factual_verdict(unsupported_without_claim)
    except F.FactualAuditError:
        check(True, "UNSUPPORTED factual verdict requires the unsupported proposition")
    else:
        check(False, "unsupported-without-proposition must fail")

    mismatch = copy.deepcopy(rows)
    mismatch[1]["source_evidence"] = evidence + ["DOSSIER: different evidence"]
    mismatch[1]["source_evidence_sha256"] = F.evidence_sha256(mismatch[1]["source_evidence"])
    try:
        F.build_factual_packets(mismatch, keys)
    except F.FactualAuditError:
        check(True, "paired candidates cannot be judged against different factual evidence")
    else:
        check(False, "different source evidence must fail")

    bad_hash = copy.deepcopy(rows)
    bad_hash[0]["source_evidence_sha256"] = "0" * 64
    try:
        F.build_factual_packets(bad_hash, keys)
    except F.FactualAuditError:
        check(True, "tampered source evidence hash fails before factual judging")
    else:
        check(False, "tampered source evidence hash must fail")

    editorial = [mapped_editorial(f"t{i}", "v21" if i < 9 else "legacy") for i in range(12)]
    factual = [factual_mapped(f"t{i}") for i in range(12)]
    report = F.aggregate_with_factual_audit(editorial, factual, promotion_rows())
    check(report["verdict"] == "PROMOTION_READY_FOR_HUMAN_AUTHORIZATION",
          "clean symmetric factual audit preserves a qualifying editorial result")
    check(report["external_factual_audit"]["v21_external_factual_failures"] == 0,
          "clean V2.1 factual audit records zero failures")

    factual_bad_v21 = copy.deepcopy(factual)
    factual_bad_v21[0]["by_side"]["v21"]["status"] = "UNKNOWN"
    report = F.aggregate_with_factual_audit(editorial, factual_bad_v21, promotion_rows())
    check(report["verdict"] == "NOT_PROMOTION_READY", "one UNKNOWN V2.1 factual audit blocks promotion")
    check(report["external_factual_audit"]["editorial_pairs_excluded"] == 1,
          "factually unclean pair is excluded from creative A/B rather than contaminating it")

    factual_bad_legacy = copy.deepcopy(factual)
    factual_bad_legacy[0]["by_side"]["legacy"]["status"] = "UNKNOWN"
    report = F.aggregate_with_factual_audit(editorial, factual_bad_legacy, promotion_rows())
    check(report["external_factual_audit"]["legacy_external_factual_failures"] == 1,
          "legacy factual failures remain visible instead of disappearing from evidence")

    try:
        F.aggregate_with_factual_audit(editorial, factual[:-1], promotion_rows())
    except F.FactualAuditError:
        check(True, "partial factual verdict coverage fails closed")
    else:
        check(False, "partial factual coverage must fail")

    print(f"{PASS} factual-audit checks passed")


if __name__ == "__main__":
    main()
