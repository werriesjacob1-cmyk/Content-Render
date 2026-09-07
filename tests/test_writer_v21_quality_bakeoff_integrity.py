#!/usr/bin/env python3
"""Adversarial zero-network tests for Mission 2 evidence-chain integrity."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import wr21_quality_bakeoff as C  # noqa: E402

PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def write(path: Path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seal_plan(topics):
    protocol = {
        "protocol_version": "test",
        "min_comparable_pairs": 2,
        "min_decisive_pairs": 1,
        "min_v21_editorial_win_share": 0.0,
        "max_one_sided_sign_test_p": 1.0,
        "min_v21_postable_rate": 0.0,
        "max_v21_integrity_failures": 0,
        "min_v21_generation_success_rate": 0.0,
        "max_v21_success_rate_drop_vs_legacy": 1.0,
        "min_distinct_v21_treatments": 1,
        "max_single_treatment_share": 1.0,
        "max_repair_regression_topic_share": 1.0,
        "same_draft_model_min_pairs_for_guardrail": 99,
        "same_draft_model_min_v21_win_share": 0.0,
    }
    doc = {
        "experiment": "writer-v21-quality-proof",
        "protocol": protocol,
        "seed": "sealed-test",
        "topic_count": len(topics),
        "topics": [
            {"topic_id": t, "domain": "test", "fact": f"fact {t}", "planned_treatment": "HIDDEN_MECHANISM"}
            for t in topics
        ],
    }
    doc["plan_sha256"] = C._digest(doc)
    return doc


def result(topic, side):
    return {
        "topic_id": topic,
        "side": side,
        "script": f"A clean anonymous script for {topic} on side {side}.",
        "generated": True,
        "validate_clean": True,
        "integrity_clean": True if side == "v21" else None,
        "semantic_verified": True if side == "v21" else None,
        "treatment": "HIDDEN_MECHANISM" if side == "v21" else "",
        "draft_provider_model": "same/model",
        "calls": 1,
        "repair_regression_flags": [],
        "dossier_sha256": f"dossier-{topic}",
        "generation_order": ["legacy", "v21"],
    }


def seal_results(plan, rows):
    doc = {
        "experiment": "writer-v21-quality-proof-live-generation",
        "plan_sha256": plan["plan_sha256"],
        "seed": plan["seed"],
        "script_only": True,
        "rendered": False,
        "published": False,
        "results": rows,
    }
    doc["results_sha256"] = C._digest(rows)
    return doc


def verdict(pair_id):
    import writer_v21_quality_bakeoff as Q
    return {
        "pair_id": pair_id,
        "winner": "A",
        "confidence": "HIGH",
        "criterion_winners": {c: "A" for c in Q.CRITERIA},
        "postable_A": True,
        "postable_B": True,
        "decisive_reasons": ["stronger anonymous script"],
    }


def run_blind(plan_path, results_path, public_path, key_path):
    return C.main([
        "blind", "--plan", str(plan_path), "--results", str(results_path),
        "--seed", "sealed-test", "--public-out", str(public_path), "--key-out", str(key_path),
    ])


def run_score(plan_path, results_path, key_path, verdicts_path, report_path):
    return C.main([
        "score", "--plan", str(plan_path), "--results", str(results_path),
        "--key", str(key_path), "--verdicts", str(verdicts_path), "--out", str(report_path),
    ])


def main():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        plan_p, results_p = d / "plan.json", d / "results.json"
        public_p, key_p = d / "public.json", d / "key.json"
        verdicts_p, report_p = d / "verdicts.json", d / "report.json"
        plan = seal_plan(["t0", "t1"])
        rows = [result(t, s) for t in ("t0", "t1") for s in ("legacy", "v21")]
        results = seal_results(plan, rows)
        write(plan_p, plan); write(results_p, results)

        check(run_blind(plan_p, results_p, public_p, key_p) == 0,
              "sealed complete plan/results produce blind packets")
        public = json.loads(public_p.read_text())
        key = json.loads(key_p.read_text())
        check(public["plan_sha256"] == plan["plan_sha256"] == key["plan_sha256"],
              "public and private blind artifacts stay bound to frozen plan")
        check(public["results_sha256"] == results["results_sha256"] == key["results_sha256"],
              "public and private blind artifacts stay bound to exact generation evidence")

        full_verdicts = [verdict(k["pair_id"]) for k in key["keys"]]
        write(verdicts_p, full_verdicts)
        check(run_score(plan_p, results_p, key_p, verdicts_p, report_p) != 3,
              "complete verdict coverage reaches promotion evaluation")

        write(verdicts_p, full_verdicts[:-1])
        check(run_score(plan_p, results_p, key_p, verdicts_p, report_p) == 3,
              "omitting one unfavorable-capable pair fails closed instead of shrinking denominator")
        extra = full_verdicts + [dict(full_verdicts[0], pair_id="pair_unknown")]
        write(verdicts_p, extra)
        check(run_score(plan_p, results_p, key_p, verdicts_p, report_p) == 3,
              "unknown extra verdict cannot enter promotion evidence")

        tampered = copy.deepcopy(results)
        tampered["results"][0]["script"] = "quietly altered after sealing"
        write(results_p, tampered)
        check(run_blind(plan_p, results_p, public_p, key_p) == 3,
              "post-seal generation-result mutation is detected")

        bad_dossier = copy.deepcopy(results)
        bad_dossier["results"][1]["dossier_sha256"] = "different-dossier"
        bad_dossier["results_sha256"] = C._digest(bad_dossier["results"])
        write(results_p, bad_dossier)
        check(run_blind(plan_p, results_p, public_p, key_p) == 3,
              "paired systems cannot quietly receive different research dossiers")

        duplicate = copy.deepcopy(results)
        duplicate["results"].append(copy.deepcopy(duplicate["results"][0]))
        duplicate["results_sha256"] = C._digest(duplicate["results"])
        write(results_p, duplicate)
        check(run_blind(plan_p, results_p, public_p, key_p) == 3,
              "duplicate topic/side generation row fails closed")

        missing_side = copy.deepcopy(results)
        missing_side["results"] = missing_side["results"][:-1]
        missing_side["results_sha256"] = C._digest(missing_side["results"])
        write(results_p, missing_side)
        check(run_blind(plan_p, results_p, public_p, key_p) == 3,
              "missing planned side fails before editorial judging")

        treatment_drift = copy.deepcopy(results)
        treatment_drift["results"][1]["treatment"] = "CASE_FILE"
        treatment_drift["results_sha256"] = C._digest(treatment_drift["results"])
        write(results_p, treatment_drift)
        check(run_blind(plan_p, results_p, public_p, key_p) == 3,
              "generated V2.1 treatment cannot drift from preregistered panel")

        # Restore clean evidence and private key, then prove both envelopes are checked.
        write(results_p, results)
        check(run_blind(plan_p, results_p, public_p, key_p) == 0, "clean evidence restores blind build")
        key_doc = json.loads(key_p.read_text())
        key_doc["keys"][0]["topic_id"] = "tampered-topic"
        write(key_p, key_doc)
        write(verdicts_p, full_verdicts)
        check(run_score(plan_p, results_p, key_p, verdicts_p, report_p) == 3,
              "post-seal private answer-key mutation is detected")

        check(run_blind(plan_p, results_p, public_p, key_p) == 0, "private key restored from clean evidence")
        plan_bad = copy.deepcopy(plan)
        plan_bad["topics"][0]["fact"] = "altered preregistration"
        write(plan_p, plan_bad)
        check(run_blind(plan_p, results_p, public_p, key_p) == 3,
              "post-seal frozen-plan mutation is detected")

    print(f"{PASS} sealed-evidence checks passed")


if __name__ == "__main__":
    main()
