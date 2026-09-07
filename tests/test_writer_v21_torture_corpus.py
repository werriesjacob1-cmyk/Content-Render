#!/usr/bin/env python3
"""Zero-network checks for the permanent Writer V2.1 torture corpus."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_v21_torture_corpus as T


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_required_failure_classes_are_permanent():
    ids = set(T.case_index())
    required = {
        "mantis_shrimp_blender",
        "neutron_star_invented_mechanism",
        "mauna_kea_invented_framing",
        "lightning_duration_inflation",
        "chess_magnitude_only",
        "stomach_clinical_repair",
    }
    check(required.issubset(ids), "all known overnight failure classes are preserved")
    check(len(ids) == len(T.CASES), "torture case ids are unique")


def test_guard_coverage_spans_hard_semantic_editorial_repair():
    guards = T.cases_by_guard()
    for guard in ("hard_traceability", "semantic_support", "editorial_quality", "repair_regression_pairwise"):
        check(guard in guards and guards[guard], f"corpus contains {guard} cases")


def test_semantic_cases_have_real_unsupported_propositions():
    cases = T.live_semantic_cases()
    check(len(cases) >= 3, "semantic critic gets multiple no-number/proper-noun torture cases")
    blob = " ".join(c["hook"] + " " + " ".join(c["beats"]) for c in cases).lower()
    check("blender" in blob and "geologists" in blob and "energy devices" in blob,
          "live semantic payload preserves observed unsupported additions")
    check(all(c["expected_outcome"] == "reject" for c in cases),
          "semantic torture cases are expected to reject")


def test_editorial_corpus_surfaces_known_ai_moralizing():
    chess = T.case_index()["chess_magnitude_only"]
    report = T.deterministic_editorial_probe(chess)
    check("generic_ai_moralizing" in report["warning_kinds"],
          "magnitude-only chess payoff triggers generic AI moralizing telemetry")

    mantis = T.case_index()["mantis_shrimp_blender"]
    report = T.deterministic_editorial_probe(mantis)
    check("generic_ai_moralizing" in report["warning_kinds"],
          "danger-hides-in-plain-sight payoff remains a known-bad warning")


def test_clinical_repair_records_craft_regression_evidence():
    case = T.case_index()["stomach_clinical_repair"]
    report = T.repair_regression_probe(case)
    check(report is not None, "stomach repair has before/after regression probe")
    changes = report["line_changes"]
    hook = next(x for x in changes if x["beat_index"] == 0)
    check(hook["after_words"] > hook["before_words"],
          "clinical repair preserves hook word inflation evidence")
    check(report["gating"] is False, "torture repair probe cannot alter selection")


def test_corpus_never_fabricates_acceptance():
    check(all(case.expected_outcome != "accept" for case in T.CASES),
          "known-bad corpus cannot silently become positive acceptance fixtures")


if __name__ == "__main__":
    test_required_failure_classes_are_permanent()
    test_guard_coverage_spans_hard_semantic_editorial_repair()
    test_semantic_cases_have_real_unsupported_propositions()
    test_editorial_corpus_surfaces_known_ai_moralizing()
    test_clinical_repair_records_craft_regression_evidence()
    test_corpus_never_fabricates_acceptance()
    print("writer_v21_torture_corpus tests: PASS")
