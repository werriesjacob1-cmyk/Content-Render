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
import writer_v21_factual_audit as F  # noqa: E402
import writer_v21_quality_bakeoff as Q  # noqa: E402

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
    evidence = [f"BASE_FACT: fact {topic}", f"DOSSIER: shared support {topic}"]
    return {
        "topic_id": topic,
        "side": side,
        "script": f"A clean anonymous script for {topic} candidate {1 if side == 'legacy' else 2}.",
        "generated": True,
        "validate_clean": True,
        "integrity_clean": True if side == "v21" else None,
        "semantic_verified": True if side == "v21" else None,
        "treatment": "HIDDEN_MECHANISM" if side == "v21" else "",
        "draft_provider_model": "same/model",
        "calls": 1,
        "repair_regression_flags": [],
        "dossier_sha256": f"dossier-{topic}",
        "source_evidence": evidence,
        "source_evidence_sha256": F.evidence_sha256(evidence),
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


def verdict(key):
    return {
        "pair_id": key["pair_id"],
        "packet_sha256": key["editorial_packet_sha256"],
        "winner": "A",
        "confidence": "HIGH",
        "criterion_winners": {c: "A" for c in Q.CRITERIA},
        "postable_A": True,
        "postable_B": True,
        "decisive_reasons": ["stronger anonymous script"],
    }


def factual_verdict(key):
    return {
        "pair_id": key["pair_id"],
        "packet_sha256": key["factual_packet_sha256"],
        "status_A": "CLEAN",
        "status_B": "CLEAN",
        "unsupported_propositions_A": [],
        "unsupported_propositions_B": [],
        "notes_A": [],
        "notes_B": [],
    }


def run_blind(plan_path, results_path, public_path, key_path):
    return C.main([
        "blind", "--plan", str(plan_path), "--results", str(results_path),
        "--seed", "sealed-test", "--public-out", str(public_path), "--key-out", str(key_path),
    ])


def run_score(plan_path, results_path, public_path, key_path, verdicts_path, factual_path, report_path):
    return C.main([
        "score", "--plan", str(plan_path), "--results", str(results_path),
        "--public", str(public_path), "--key", str(key_path),
        "--verdicts", str(verdicts_path), "--factual-verdicts", str(factual_path),
        "--out", str(report_path),
    ])


def main():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        plan_p, results_p = d / "plan.json", d / "results.json"
        public_p, key_p = d / "public.json", d / "key.json"
        verdicts_p, factual_p, report_p = d / "verdicts.json", d / "factual.json", d / "report.json"
        plan = seal_plan(["t0", "t1"])
        rows = [result(t, s) for t in ("t0", "t1") for s in ("legacy", "v21")]
        results = seal_results(plan, rows)
        write(plan_p, plan); write(results_p, results)

        check(run_blind(plan_p, results_p, public_p, key_p) == 0,
              "sealed complete plan/results produce editorial and factual blind packets")
        public = json.loads(public_p.read_text())
        key = json.loads(key_p.read_text())
        check(public["plan_sha256"] == plan["plan_sha256"] == key["plan_sha256"],
              "public and private blind artifacts stay bound to frozen plan")
        check(public["results_sha256"] == results["results_sha256"] == key["results_sha256"],
              "public and private blind artifacts stay bound to exact generation evidence")
        check(public["packet_count"] == public["factual_packet_count"] == key["key_count"] == 2,
              "editorial factual and private pair coverage starts identical")
        check(all(k.get("editorial_packet_sha256") and k.get("factual_packet_sha256") for k in key["keys"]),
              "private key binds both exact judge packet types")

        full_verdicts = [verdict(k) for k in key["keys"]]
        full_factual = [factual_verdict(k) for k in key["keys"]]
        editorial_env = {"public_sha256": public["public_sha256"], "verdicts": full_verdicts}
        factual_env = {"public_sha256": public["public_sha256"], "factual_verdicts": full_factual}
        write(verdicts_p, editorial_env); write(factual_p, factual_env)
        check(run_score(plan_p, results_p, public_p, key_p, verdicts_p, factual_p, report_p) != 3,
              "complete packet-bound editorial and factual verdict coverage reaches promotion evaluation")

        missing_editorial = copy.deepcopy(editorial_env)
        missing_editorial["verdicts"] = missing_editorial["verdicts"][:-1]
        write(verdicts_p, missing_editorial)
        check(run_score(plan_p, results_p, public_p, key_p, verdicts_p, factual_p, report_p) == 3,
              "omitting one editorial pair fails closed instead of shrinking denominator")

        extra = copy.deepcopy(editorial_env)
        extra["verdicts"].append(dict(full_verdicts[0], pair_id="pair_unknown"))
        write(verdicts_p, extra)
        check(run_score(plan_p, results_p, public_p, key_p, verdicts_p, factual_p, report_p) == 3,
              "unknown extra editorial verdict cannot enter promotion evidence")

        write(verdicts_p, editorial_env)
        missing_factual = copy.deepcopy(factual_env)
        missing_factual["factual_verdicts"] = missing_factual["factual_verdicts"][:-1]
        write(factual_p, missing_factual)
        check(run_score(plan_p, results_p, public_p, key_p, verdicts_p, factual_p, report_p) == 3,
              "omitting one factual verdict fails closed")

        stale_public = copy.deepcopy(factual_env)
        stale_public["public_sha256"] = "0" * 64
        write(factual_p, stale_public)
        check(run_score(plan_p, results_p, public_p, key_p, verdicts_p, factual_p, report_p) == 3,
              "factual verdict envelope from different public artifact fails closed")

        write(factual_p, factual_env)
        stale_editorial_packet = copy.deepcopy(editorial_env)
        stale_editorial_packet["verdicts"][0]["packet_sha256"] = "0" * 64
        write(verdicts_p, stale_editorial_packet)
        check(run_score(plan_p, results_p, public_p, key_p, verdicts_p, factual_p, report_p) == 3,
              "stale editorial packet verdict fails closed even with correct pair_id")

        write(verdicts_p, editorial_env)
        stale_factual_packet = copy.deepcopy(factual_env)
        stale_factual_packet["factual_verdicts"][0]["packet_sha256"] = "0" * 64
        write(factual_p, stale_factual_packet)
        check(run_score(plan_p, results_p, public_p, key_p, verdicts_p, factual_p, report_p) == 3,
              "stale factual packet verdict fails closed even with correct pair_id")

        write(factual_p, factual_env)
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

        bad_evidence = copy.deepcopy(results)
        bad_evidence["results"][1]["source_evidence"] = ["BASE_FACT: fact t0", "DOSSIER: different support"]
        bad_evidence["results"][1]["source_evidence_sha256"] = F.evidence_sha256(bad_evidence["results"][1]["source_evidence"])
        bad_evidence["results_sha256"] = C._digest(bad_evidence["results"])
        write(results_p, bad_evidence)
        check(run_blind(plan_p, results_p, public_p, key_p) == 3,
              "paired systems cannot quietly receive different factual source evidence")

        base_fact_drift = copy.deepcopy(results)
        for r in base_fact_drift["results"][:2]:
            r["source_evidence"] = ["BASE_FACT: substituted fact", "DOSSIER: shared support t0"]
            r["source_evidence_sha256"] = F.evidence_sha256(r["source_evidence"])
        base_fact_drift["results_sha256"] = C._digest(base_fact_drift["results"])
        write(results_p, base_fact_drift)
        check(run_blind(plan_p, results_p, public_p, key_p) == 3,
              "resealed factual evidence cannot detach from frozen plan base fact")

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

        # Restore clean evidence and prove public/private/plan seals all remain live at score time.
        write(results_p, results)
        check(run_blind(plan_p, results_p, public_p, key_p) == 0, "clean evidence restores blind build")
        public = json.loads(public_p.read_text())
        key = json.loads(key_p.read_text())
        full_verdicts = [verdict(k) for k in key["keys"]]
        full_factual = [factual_verdict(k) for k in key["keys"]]
        editorial_env = {"public_sha256": public["public_sha256"], "verdicts": full_verdicts}
        factual_env = {"public_sha256": public["public_sha256"], "factual_verdicts": full_factual}
        write(verdicts_p, editorial_env); write(factual_p, factual_env)

        public_tampered = copy.deepcopy(public)
        public_tampered["packets"][0]["candidate_A"] = "altered after judging"
        write(public_p, public_tampered)
        check(run_score(plan_p, results_p, public_p, key_p, verdicts_p, factual_p, report_p) == 3,
              "post-seal public packet mutation is detected")

        write(public_p, public)
        public_resealed = copy.deepcopy(public)
        public_resealed["packets"][0]["candidate_A"] = "attacker resealed a new editorial packet"
        public_resealed["packets"][0]["packet_sha256"] = C._packet_hash(public_resealed["packets"][0])
        public_resealed.pop("public_sha256", None)
        public_resealed["public_sha256"] = C._digest(public_resealed)
        resealed_editorial_env = {"public_sha256": public_resealed["public_sha256"], "verdicts": full_verdicts}
        resealed_factual_env = {"public_sha256": public_resealed["public_sha256"], "factual_verdicts": full_factual}
        write(public_p, public_resealed); write(verdicts_p, resealed_editorial_env); write(factual_p, resealed_factual_env)
        check(run_score(plan_p, results_p, public_p, key_p, verdicts_p, factual_p, report_p) == 3,
              "resealing altered public packet still fails against private packet hashes")

        write(public_p, public); write(verdicts_p, editorial_env); write(factual_p, factual_env)
        key_doc = copy.deepcopy(key)
        key_doc["keys"][0]["topic_id"] = "tampered-topic"
        write(key_p, key_doc)
        check(run_score(plan_p, results_p, public_p, key_p, verdicts_p, factual_p, report_p) == 3,
              "post-seal private answer-key mutation is detected")

        write(key_p, key)
        plan_bad = copy.deepcopy(plan)
        plan_bad["topics"][0]["fact"] = "altered preregistration"
        write(plan_p, plan_bad)
        check(run_blind(plan_p, results_p, public_p, key_p) == 3,
              "post-seal frozen-plan mutation is detected")

    print(f"{PASS} sealed-evidence checks passed")


if __name__ == "__main__":
    main()
