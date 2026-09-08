#!/usr/bin/env python3
"""Zero-network adversarial tests for the Writer V2.1 quality-proof harness."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import writer_v21_quality_bakeoff as Q  # noqa: E402

PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def synthetic_facts():
    return [
        {"id": f"{domain}_{i}", "domain": domain, "fact": f"{domain} fact {i}"}
        for domain in ("space", "body", "animals", "physics", "earth", "tech")
        for i in range(4)
    ]


def result(topic, side, *, generated=True, validate=True, integrity=None, semantic=None,
           treatment="", model="same/model", repair=None):
    if side == "v21":
        integrity = True if integrity is None else integrity
        semantic = True if semantic is None else semantic
    return {
        "topic_id": topic, "side": side,
        "script": f"Anonymous spoken story about {topic}.",
        "generated": generated, "validate_clean": validate,
        "integrity_clean": integrity, "semantic_verified": semantic,
        "treatment": treatment, "draft_provider_model": model,
        "calls": 1, "repair_regression_flags": repair or [],
    }


def mapped(topic, winner="v21", *, same=True, crit=None):
    crit = crit or {c: winner for c in Q.CRITERIA}
    return {
        "pair_id": f"p_{topic}", "topic_id": topic, "winner_side": winner,
        "confidence": "HIGH", "criterion_winner_sides": crit,
        "postable_by_side": {"v21": True, "legacy": False},
        "same_draft_model": same, "decisive_reasons": ["stronger"],
    }


def generation_panel(*, bad_integrity=False, repair_topics=0):
    rows = []
    treatments = ["A", "B", "C", "D", "E", "F"]
    for i in range(12):
        topic = f"t{i}"
        rows.append(result(topic, "legacy", treatment=""))
        rows.append(result(
            topic, "v21", treatment=treatments[i % 6],
            integrity=False if bad_integrity and i == 0 else True,
            repair=["critic_craft_drop"] if i < repair_topics else [],
        ))
    return rows


def test_panel_determinism_and_balance():
    facts = synthetic_facts()
    a = Q.select_topic_panel(facts, count=12, seed="s")
    b = Q.select_topic_panel(facts, count=12, seed="s")
    c = Q.select_topic_panel(facts, count=12, seed="different")
    check(a == b, "same seed freezes the same topic panel")
    check(a != c, "experiment seed changes deterministic panel")
    check(len({x["domain"] for x in a}) == 6, "panel round-robins across domains")
    check(len({x["topic_id"] for x in a}) == 12, "panel contains no duplicate topics")
    treatments = ["HIDDEN", "CASE", "OBJECT", "SCALE", "MYTH", "TIME", "INSIDE", "VISUAL"]
    tmap = {row["id"]: treatments[i % 8] for i, row in enumerate(facts)}
    balanced = Q.select_topic_panel(facts, count=12, seed="b", treatment_by_id=tmap)
    check(len({x.get("planned_treatment") for x in balanced}) >= 6,
          "panel exercises multiple treatments without generated-quality peeking")


def test_real_bank_panel():
    bank = json.loads((ROOT / "topic_bank.json").read_text(encoding="utf-8"))
    quarantine_path = ROOT / "topic_quarantine.json"
    quarantine = json.loads(quarantine_path.read_text(encoding="utf-8")) if quarantine_path.exists() else {"ids": []}
    blocked = {str(x) for x in quarantine.get("ids", [])}
    facts = [f for f in bank.get("facts", []) if str(f.get("id") or "") not in blocked]
    import writer_v2 as W
    tmap = {str(f["id"]): str(W.select_treatment(str(f["id"]), []) or "") for f in facts if f.get("id")}
    panel = Q.select_topic_panel(facts, count=12, seed="writer-v21-quality-proof-v1", treatment_by_id=tmap)
    check(len(panel) == 12, "real production bank yields 12 eligible bakeoff topics")
    check(not ({x["topic_id"] for x in panel} & blocked), "real panel excludes quarantined topics")
    check(len({x.get("planned_treatment") for x in panel if x.get("planned_treatment")}) >= 5,
          "real panel covers at least five Writer V2.1 treatments")
    print("REAL PANEL", json.dumps([(x["topic_id"], x["domain"], x.get("planned_treatment")) for x in panel]))


def test_blinding_and_fail_closed_verdicts():
    rows = [result("x", "legacy"), result("x", "v21", treatment="A")]
    packets, keys, excluded = Q.build_blind_packets(rows, seed="s")
    check(len(packets) == len(keys) == 1 and not excluded, "clean pair produces one blind packet")
    text = json.dumps(packets[0]).lower()
    check("legacy" not in text and "v21" not in text, "public blind packet does not leak system identity")
    check(set(keys[0]["aliases"].values()) == {"legacy", "v21"}, "system mapping exists only in private key")
    packet = packets[0]
    verdict = {
        "pair_id": packet["pair_id"], "winner": "A", "confidence": "HIGH",
        "criterion_winners": {c: "A" for c in Q.CRITERIA},
        "postable_A": True, "postable_B": False, "decisive_reasons": ["better"],
    }
    mapped_v = Q.map_verdict(verdict, keys[0])
    check(mapped_v["winner_side"] in {"legacy", "v21"}, "blind verdict maps only after judging")
    bad = dict(verdict); bad["criterion_winners"] = {"opening_pull": "A"}
    try:
        Q.parse_verdict(bad)
    except Q.BakeoffProtocolError:
        check(True, "partial criterion verdict fails closed")
    else:
        check(False, "partial criterion verdict must fail")


def test_noncomparable_is_excluded():
    bad = result("x", "v21", generated=False, validate=False)
    bad["script"] = ""
    packets, keys, excluded = Q.build_blind_packets([result("x", "legacy"), bad, result("y", "legacy")])
    check(not packets and not keys, "missing/noncomparable pairs cannot enter editorial judging")
    check({e["reason"] for e in excluded} == {"candidate_not_comparable", "missing_side"},
          "exclusions remain explicit")


def test_sign_test_and_promotion():
    check(abs(Q.one_sided_sign_test_p(9, 3) - 0.072998046875) < 1e-12,
          "exact one-sided sign test matches 9-3 binomial tail")
    verdicts = [mapped(f"t{i}", "v21") for i in range(9)] + [mapped(f"t{i}", "legacy") for i in range(9, 12)]
    report = Q.aggregate_promotion(verdicts, generation_panel())
    check(report["verdict"] == "PROMOTION_READY_FOR_HUMAN_AUTHORIZATION",
          "9-3 clean blind win reaches promotion readiness, not auto-activation")
    check(report["wins"] == {"v21": 9, "legacy": 3, "ties": 0}, "win counts are preserved")


def test_integrity_and_quality_guardrails_block():
    verdicts = [mapped(f"t{i}", "v21") for i in range(10)] + [mapped(f"t{i}", "legacy") for i in range(10, 12)]
    report = Q.aggregate_promotion(verdicts, generation_panel(bad_integrity=True))
    check(report["verdict"] == "NOT_PROMOTION_READY", "one V2.1 integrity failure blocks promotion")
    rows = generation_panel()
    rows[1]["integrity_clean"] = None; rows[1]["semantic_verified"] = None
    report = Q.aggregate_promotion(verdicts, rows)
    check(report["verdict"] == "NOT_PROMOTION_READY", "unknown integrity on generated V2.1 output fails closed")
    report = Q.aggregate_promotion(
        [mapped(f"t{i}", "v21") for i in range(9)] + [mapped(f"t{i}", "legacy") for i in range(9, 12)],
        generation_panel(repair_topics=4),
    )
    check(report["verdict"] == "NOT_PROMOTION_READY", "repair regressions above 25 percent block promotion")
    naturalness_loses = []
    for i in range(9):
        crit = {c: "v21" for c in Q.CRITERIA}; crit["spoken_naturalness"] = "legacy"
        naturalness_loses.append(mapped(f"t{i}", "v21", crit=crit))
    naturalness_loses += [mapped(f"t{i}", "legacy") for i in range(9, 12)]
    report = Q.aggregate_promotion(naturalness_loses, generation_panel())
    check(report["verdict"] == "NOT_PROMOTION_READY", "overall wins cannot hide spoken-naturalness regression")


def test_underpowered_sample_expands():
    rows = []
    for i, treatment in enumerate(("A", "B", "C", "D", "E", "F")):
        rows.extend([result(f"u{i}", "legacy"), result(f"u{i}", "v21", treatment=treatment)])
    report = Q.aggregate_promotion([mapped(f"u{i}", "v21") for i in range(6)], rows)
    check(report["verdict"] == "EXPAND_SAMPLE", "strong but undersized evidence expands instead of false promotion")


def test_live_runner_and_workflow_secret_boundary():
    import wr21_quality_generate as L
    check("generate" not in sys.modules, "live runner import does not import provider-aware generate.py")
    old = os.environ.pop(L.LIVE_ENV, None)
    try:
        rc = L.main(["--plan", "definitely-missing-plan.json"])
        check(rc == 3 and "generate" not in sys.modules, "missing double opt-in refuses before provider-aware import")
    finally:
        if old is not None:
            os.environ[L.LIVE_ENV] = old
    text = (ROOT / ".github/workflows/wr21_quality_bakeoff.yml").read_text(encoding="utf-8")
    check("workflow_dispatch:" in text and "pull_request:" not in text and "\n  push:" not in text and "schedule:" not in text,
          "provider-backed bakeoff workflow is manual-only")
    check("github.ref == 'refs/heads/main'" in text and "ref: ${{ github.sha }}" in text,
          "provider workflow is main-only and exact-SHA checkout")
    check("persist-credentials: false" in text and "permissions:\n  contents: read" in text,
          "provider workflow has no retained checkout credential and read-only permissions")
    check("ref: ${{ inputs." not in text and "github.head_ref" not in text,
          "provider workflow cannot checkout a user-selected branch")
    generation_step = text.split("- name: Generate paired scripts only", 1)[1].split("- name: Build identity-blind editorial packets", 1)[0]
    before = text.split("- name: Generate paired scripts only", 1)[0]
    after = text.split("- name: Build identity-blind editorial packets", 1)[1]
    check("secrets." in generation_step and "secrets." not in before and "secrets." not in after,
          "provider secrets are scoped only to fixed generation step")
    check("--allow-provider-calls" in generation_step and "WR21_QUALITY_BAKEOFF_LIVE: I_ACCEPT_PROVIDER_CALLS" in generation_step,
          "workflow satisfies runner double opt-in explicitly")


def main():
    test_panel_determinism_and_balance()
    test_real_bank_panel()
    test_blinding_and_fail_closed_verdicts()
    test_noncomparable_is_excluded()
    test_sign_test_and_promotion()
    test_integrity_and_quality_guardrails_block()
    test_underpowered_sample_expands()
    test_live_runner_and_workflow_secret_boundary()
    print(f"{PASS} quality-bakeoff checks passed")


if __name__ == "__main__":
    main()
