#!/usr/bin/env python3
"""Zero-network regressions for the offline Writer rejection-corpus replay.

The corpus under tests/fixtures/writer_corpus/ is REAL preserved output from
failed flagship certification runs #2-#5. It exists so a Writer/prompt/repair
change can be measured at $0 instead of costing a paid provider run per
experiment. These tests keep the replay honest: the classifier must bucket the
actual historical rejection strings, and the headline measurements must not
drift silently.

If a Writer change legitimately improves these numbers, update the expected
values DELIBERATELY and say why. Never edit the fixtures to make a test pass --
they are evidence, not inputs.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import writer_replay as R


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


# Verbatim strings taken from the real corpus.
_REAL = [
    ("script word count 118 out of range (target 78-98, hard 68-108, mode short)",
     "total_word_count", 10),
    ("script word count 141 out of range (target 78-98, hard 68-108, mode short)",
     "total_word_count", 33),
    ("scene 5 voiceover too long (30 words, cap is 25)", "scene_word_cap", 5),
    ("scene 6 voiceover too long (31 words, cap is 25)", "scene_word_cap", 6),
    ("hook length 18 words out of range", "hook_length", 0),
    ("scenes 7 and 8 too similar (repetition)", "repetition", 0),
    ("the verified fact is restated in 2 scenes [3, 4] instead of once", "fact_restated", 0),
    ("only 0/3 mandatory key terms named (none) — the script must explicitly say at least 2",
     "key_terms_missing", 0),
]


def test_classifier_buckets_the_real_historical_rejections():
    for text, family, overage in _REAL:
        got = R.classify_validate_err(text)
        check(got["family"] == family, f"{family}: classified {text[:44]!r}")
        if overage:
            check(got["overage"] == overage,
                  f"{family}: measured overage {got['overage']} == {overage}")


def test_classifier_is_total_and_never_raises():
    for junk in (None, "", "   ", "something nobody has ever seen", 0):
        got = R.classify_validate_err(junk if isinstance(junk, (str, type(None))) else str(junk))
        check(isinstance(got, dict) and "family" in got, f"classifier returns a verdict for {junk!r}")
    check(R.classify_validate_err(None)["family"] is None, "no error means no defect family")
    check(R.classify_validate_err("wholly novel failure")["family"] == "other",
          "an unrecognised rejection is surfaced as 'other', never silently dropped")


def test_tier1_clean_requires_all_three_signals():
    clean = {"mechanical_hard_count": 0, "semantic_violation_count": 0, "semantic_verified": True}
    check(R.tier1_clean(clean), "no mechanical, no semantic, verified => Tier-1 clean")
    for broken in (
        {**clean, "mechanical_hard_count": 1},
        {**clean, "semantic_violation_count": 1},
        {**clean, "semantic_verified": False},
    ):
        check(not R.tier1_clean(broken),
              f"Tier-1 dirty when {[k for k in broken if broken[k] != clean[k]]} differs")


def test_corpus_is_present_and_replays():
    corpus = R.load_corpus()
    check(len(corpus) >= 4, f"at least 4 flagship fixtures preserved (got {len(corpus)})")
    for fx in corpus:
        check(fx.get("attempts"), f"{fx['_file']} carries real attempts")
        check(fx.get("accepted") is False,
              f"{fx['_file']} is a REJECTION fixture (no accepted candidate)")


def test_measured_baseline_is_pinned():
    """These numbers are the evidence behind the whole Writer diagnosis.

    Pinned to the FIXTURES it was measured over (runs 02-05), not to whatever
    the corpus happens to hold. A later flagship adds rounds; it does not get to
    quietly restate a result taken before it existed.
    """
    t = R.replay_corpus(only=R.HISTORICAL_BASELINE_FIXTURES)["totals"]
    check(t["attempts"] == 13 and t["rounds"] == 36,
          f"runs 02-05 pinned at 13 attempts / 36 rounds (got {t['attempts']}/{t['rounds']})")
    check(t["mechanical_rounds"] == 18,
          f"18 of 36 rounds died on pure length arithmetic (got {t['mechanical_rounds']})")
    check(t["craft_rounds"] == 16,
          f"16 of 36 rounds died on craft defects (got {t['craft_rounds']})")
    # The measurement that killed the "starved repair budget" hypothesis: only
    # ONE length-blocked round ever had Tier-1 clean, so a terminal mechanical
    # salvage would have rescued nothing. Do not build that architecture.
    check(t["rounds_blocked_only_by_length"] == 1,
          f"only 1 length-blocked round had Tier-1 clean (got {t['rounds_blocked_only_by_length']})")
    check(t["salvageable_attempts"] == 0,
          f"a terminal mechanical salvage would rescue 0 historical attempts "
          f"(got {t['salvageable_attempts']}) -- repair-budget starvation is NOT the binding constraint")


FLAGSHIP_06 = ("flagship_06_fed4b0f.json",)


def _families(only):
    fams = {}
    for fx in R.load_corpus(only=only):
        for attempt in fx.get("attempts") or []:
            for row in R.replay_attempt(attempt)["rounds"]:
                if row["family"]:
                    fams[row["family"]] = fams.get(row["family"], 0) + 1
    return fams


def test_the_stated_length_contract_eliminated_length_failures():
    """Run 06 is the first flagship AFTER the length contract shipped (PR #76).

    Runs 02-05 lost 17 of 36 rounds to total-word + per-scene arithmetic. Run 06
    lost ZERO of 9. n=9 is not a statistical claim and this test does not make
    one -- it pins the measurement so a regression that reintroduces length
    failures is visible immediately rather than being rediscovered by a paid run.
    """
    old = _families(R.HISTORICAL_BASELINE_FIXTURES)
    new = _families(FLAGSHIP_06)
    old_len = old.get("total_word_count", 0) + old.get("scene_word_cap", 0)
    new_len = new.get("total_word_count", 0) + new.get("scene_word_cap", 0)
    check(old_len == 17, f"runs 02-05 lost 17 rounds to length arithmetic (got {old_len})")
    check(new_len == 0,
          f"run 06, the first with a STATED budget, lost 0 rounds to length (got {new_len})")


def test_run_06_failures_are_the_constraints_the_repair_is_never_told():
    """Why the fix is repair-prompt content, not a wider budget or more rounds.

    Every run-06 blocker is a deterministic constraint that validate() enforces
    and the repair prompt never states: hook length, mandatory key terms,
    forbidden formal connectors.
    """
    fams = _families(FLAGSHIP_06)
    check(fams.get("hook_length") == 3, f"3 hook-length rounds (got {fams.get('hook_length')})")
    check(fams.get("key_terms_missing") == 3,
          f"3 mandatory-key-term rounds (got {fams.get('key_terms_missing')})")
    check(fams.get("formal_connector") == 2,
          f"2 formal-connector rounds (got {fams.get('formal_connector')})")
    check(sum(fams.values()) == 9 - fams.get(None, 0),
          "every run-06 round is accounted for by a named family")


if __name__ == "__main__":
    test_classifier_buckets_the_real_historical_rejections()
    test_classifier_is_total_and_never_raises()
    test_tier1_clean_requires_all_three_signals()
    test_corpus_is_present_and_replays()
    test_measured_baseline_is_pinned()
    test_the_stated_length_contract_eliminated_length_failures()
    test_run_06_failures_are_the_constraints_the_repair_is_never_told()
    print("writer replay tests: PASS")
