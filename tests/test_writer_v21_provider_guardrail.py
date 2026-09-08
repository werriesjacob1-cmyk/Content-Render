#!/usr/bin/env python3
"""Zero-network tests that provider/model confounding cannot produce promotion."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import wr21_quality_bakeoff as C  # noqa: E402
import wr21_quality_preregister as R  # noqa: E402
import writer_v21_provider_guardrail as P  # noqa: E402
import writer_v21_quality_bakeoff as Q  # noqa: E402

PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        raise AssertionError(label)
    PASS += 1
    print(f"PASS {label}")


def mapped(topic, winner="v21", *, same=True, critical_winner=None):
    crit = {c: winner for c in Q.CRITERIA}
    if critical_winner is not None:
        for c in Q.CRITICAL_CRITERIA:
            crit[c] = critical_winner
    return {
        "pair_id": f"pair_{topic}",
        "topic_id": topic,
        "winner_side": winner,
        "criterion_winner_sides": crit,
        "postable_by_side": {"v21": True, "legacy": True},
        "same_draft_model": same,
    }


def base_report():
    return {
        "verdict": "PROMOTION_READY_FOR_HUMAN_AUTHORIZATION",
        "checks": [],
        "external_factual_audit": {"excluded_pairs": []},
    }


def test_preregistration():
    plan = {
        "experiment": "writer-v21-quality-proof",
        "protocol": dict(Q.DEFAULT_PROTOCOL),
        "seed": "s",
        "topic_count": 2,
        "topics": [
            {"topic_id": "a", "domain": "x", "fact": "fact a"},
            {"topic_id": "b", "domain": "x", "fact": "fact b"},
        ],
    }
    plan["plan_sha256"] = C._digest(plan)
    sha = "a" * 40
    sealed = R.preregister(plan, sha)
    check(sealed["execution_sha"] == sha, "preregistered plan records exact trusted execution SHA")
    check(sealed["protocol"]["provider_guardrail_version"] == P.VERSION,
          "preregistered plan records provider guardrail version")
    check(all(sealed["protocol"][k] == v for k, v in P.DEFAULTS.items()),
          "preregistered plan freezes every provider-causal threshold")
    C._verify_envelope_hash(sealed, "plan_sha256")
    check(True, "preregistered plan is resealed after execution/threshold stamp")

    altered = copy.deepcopy(sealed)
    altered["protocol"]["min_same_draft_model_pairs"] = 1
    try:
        C._verify_envelope_hash(altered, "plan_sha256")
    except Q.BakeoffProtocolError:
        check(True, "post-preregistration threshold tampering breaks plan seal")
    else:
        check(False, "threshold tampering must break plan seal")

    try:
        R.preregister(plan, "not-a-git-sha")
    except Q.BakeoffProtocolError:
        check(True, "preregistration rejects non-exact execution SHA")
    else:
        check(False, "invalid execution SHA must fail")

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "plan.json"
        p.write_text(json.dumps(plan), encoding="utf-8")
        check(R.main(["--plan", str(p), "--execution-sha", sha]) == 0,
              "preregistration CLI seals a real plan file zero-network")
        disk = json.loads(p.read_text(encoding="utf-8"))
        check(disk["execution_sha"] == sha and disk["protocol"]["provider_guardrail_version"] == P.VERSION,
              "preregistration CLI persists exact causal contract")


def main():
    rows = [mapped(f"t{i}", "v21" if i < 9 else "legacy", same=i < 4) for i in range(12)]
    report = P.apply_provider_guardrail(base_report(), rows)
    check(report["verdict"] == "EXPAND_SAMPLE",
          "strong overall result cannot promote with only four same-draft-model pairs")
    check(report["causal_provider_guardrail"]["provider_mismatched_pairs"] == 8,
          "mismatched provider/model pairs stay visible as system-level rather than causal evidence")

    rows = [mapped(f"t{i}", "v21" if i < 6 else "legacy", same=i < 8) for i in range(12)]
    report = P.apply_provider_guardrail(base_report(), rows)
    check(report["causal_provider_guardrail"]["same_draft_model_pairs"] == 8,
          "eight same-draft-model pairs satisfy matched sample floor")
    check(report["causal_provider_guardrail"]["wins"] == {"v21": 6, "legacy": 2, "ties": 0},
          "matched-model win counts are isolated from mismatched pairs")
    check(report["verdict"] == "PROMOTION_READY_FOR_HUMAN_AUTHORIZATION",
          "6-2 same-model matched win with p<=0.20 can preserve an otherwise qualifying result")

    rows = [mapped(f"t{i}", "v21" if i < 4 else "legacy", same=i < 8) for i in range(12)]
    report = P.apply_provider_guardrail(base_report(), rows)
    check(report["verdict"] == "NOT_PROMOTION_READY",
          "matched-model 4-4 result blocks promotion despite any unmatched system-level wins")

    rows = [mapped(f"t{i}", "v21" if i < 6 else "legacy", same=i < 8) for i in range(12)]
    for i in range(5):
        rows[i]["criterion_winner_sides"]["spoken_naturalness"] = "legacy"
    report = P.apply_provider_guardrail(base_report(), rows)
    check(report["verdict"] == "NOT_PROMOTION_READY",
          "same-model overall wins cannot hide a spoken-naturalness regression")

    clean = [mapped(f"t{i}", "v21" if i < 6 else "legacy", same=i < 8) for i in range(12)]
    r = base_report()
    r["external_factual_audit"] = {
        "excluded_pairs": [{"pair_id": "pair_t0"}, {"pair_id": "pair_t1"}, {"pair_id": "pair_t2"}]
    }
    report = P.apply_provider_guardrail(r, clean)
    check(report["verdict"] == "EXPAND_SAMPLE",
          "factually excluded pairs cannot count toward same-model causal sample size")

    preblocked = base_report()
    preblocked["verdict"] = "NOT_PROMOTION_READY"
    report = P.apply_provider_guardrail(preblocked, [mapped(f"t{i}") for i in range(12)])
    check(report["verdict"] == "NOT_PROMOTION_READY",
          "provider guardrail never upgrades a result blocked by another hard gate")

    check(P.DEFAULTS["min_same_draft_model_pairs"] == 8 and P.DEFAULTS["max_same_draft_model_sign_test_p"] == 0.20,
          "causal matched-provider thresholds are explicit and version-controlled before live evidence")
    test_preregistration()
    print(f"{PASS} provider-guardrail checks passed")


if __name__ == "__main__":
    main()
