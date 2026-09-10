#!/usr/bin/env python3
"""Factual repair must fix the defect without dismantling the script.

WHAT THE CORPUS ACTUALLY SHOWS (read this before strengthening any claim here)

The flagship #7 brief asserted "every scored repair reduced quality". Extracting
all 36 parent->child round pairs from `tests/fixtures/writer_corpus/` shows that
is not a claim the data can carry:

    both parent and child scored .................  1 of 36  (2.8%)
    unscored on at least one side ................ 35 of 36  (97%)
    bucket A (factual gain + craft gain) .........  0
    bucket C (factual gain + craft LOSS) .........  0
    bucket E (repair introduced a NEW violation) ..  8 of 36  (22%)

`score` is populated iff `validate_err` is null, so "mechanical improvement" and
"both sides scored" NEVER co-occur (0 of 36). The hypothesis that provenance
repair trades craft for factual safety is therefore **structurally unmeasurable**
with the current instrumentation -- bucket C cannot be populated even in
principle. Craft degradation is **NOT** established as systematic, and these
tests deliberately do not assert that it is.

What IS established, and what these tests pin:

1. The corpus's ONE measurable pair got worse on BOTH axes at once (overall
   5.57 -> 4.14, coherence 7 -> 2, AND a brand-new hard violation). That is a bad
   repair, not a trade-off.
2. Its mechanism is visible in the text. The repair targeted beats [1, 3, 4] and
   changed exactly those, every other beat byte-identical -- and beat 1 went from
   "The journey belongs to a single protein locked inside its eye" to "This
   eye-lens protein ... makes the Greenland shark the longest-lived vertebrate":
   it imported the PAYOFF's conclusion into line two, so the payoff then restated
   it. Told only to make a line supported, the cheapest move is to quote the most
   quotable claim -- which is usually the ending.
3. Three structural defects made that the path of least resistance, and those are
   code facts rather than statistics:
   - the critic is asked for `must_preserve` ("things ... the rewrite must not
     disturb") and `classify_repair` used it on tier 3 ONLY, discarding it on
     tier 1 (unsupported claim) and tier 2 (validate failure) -- the tiers that
     fire in nearly every real round;
   - the PROVENANCE instruction ended with an explicit licence to flatten
     ("It is fine for a rewritten beat to be more general/qualitative...");
   - the beat's narrative role never reached the repairer at all.

Zero network, zero providers, zero LLM calls.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import writer_v2 as W2
import writer_v2_repair as R

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


class _V:
    """Minimal stand-in for a hard TraceabilityViolation."""

    def __init__(self, beat_index, kind, value):
        self.beat_index, self.kind, self.value, self.severity = beat_index, kind, value, "hard"


def _script(num_beats=6):
    return {
        "hook": "A Greenland shark swimming today was born before America existed.",
        "hook_source_claim_ids": ["base_001"],
        "beats": [{"voiceover": f"beat {i} text", "source_claim_ids": ["base_001"]}
                  for i in range(1, num_beats + 1)],
        "payoff": "That tiny cellular relic outlasted every human empire founded since it formed.",
        "payoff_source_claim_ids": ["base_001"],
    }


def _plan(targets, critic_preserve=(), num_beats=6, validate_err=None, critic=None):
    verdict = {"must_preserve": list(critic_preserve)}
    if critic:
        verdict.update(critic)
    return R.classify_repair(
        [_V(t, "unsupported_entity", "X") for t in targets] if not validate_err else [],
        [], validate_err, verdict, num_beats,
        narration_contract={"mandatory_key_terms": ["Greenland shark"]},
        writer_out=_script(num_beats),
    )


# 1 ---------------------------------------------------------------------------
def test_1_the_critic_preservation_signal_survives_every_tier():
    """The discarded-signal defect. Tier 1 and 2 used to drop this on the floor."""
    keep = "the setup in beat 1 that does not reveal the ending"
    t1 = _plan([1], critic_preserve=[keep])
    check(t1["tier"] == 1, f"an unsupported claim is still tier 1 ({t1['tier']})")
    check(keep in t1["must_preserve"],
          "tier 1 (PROVENANCE) now carries the critic's must_preserve")
    t2 = _plan([], critic_preserve=[keep], validate_err="hook length 18 words out of range")
    check(t2["tier"] == 2, f"a validate failure is still tier 2 ({t2['tier']})")
    check(keep in t2["must_preserve"],
          "tier 2 (validate) now carries the critic's must_preserve too")
    check("Greenland shark" in t1["must_preserve"],
          "and the mandatory key terms are still preserved alongside it")


# 2 ---------------------------------------------------------------------------
def test_2_every_targeted_beat_is_told_what_it_is_for():
    plan = _plan([0, 2, 7])
    joined = "\n".join(plan["narrative_contract"])
    check("beat_index 0 is the HOOK" in joined, "the hook is named as the hook")
    check("beat_index 2 is the MIDDLE BEAT" in joined, "a middle beat is named as one")
    check("beat_index 7 is the PAYOFF" in joined, "the payoff is named as the payoff")


def test_2b_the_contract_takes_the_beat_purpose_from_THIS_treatment():
    """The first version asserted one house style over all eight treatments.

    It said a hook must open on "the most surprising concrete image". Five of
    eight treatments deliberately open ORDINARY -- HIDDEN_MECHANISM on "the
    ordinary, visible thing exactly as everyone already knows it", MYTH_AUTOPSY
    on "the common belief stated plainly", SCALE_REVEAL on "an ordinary,
    familiar reference point" -- and VISUAL_EXPERIMENT opens on a question, not
    an image. A repair prompt asserting the opposite would fight the treatment
    system and flatten the variety it exists to create.
    """
    wo = _script()
    openings = {}
    for name in ("HIDDEN_MECHANISM", "MYTH_AUTOPSY", "VISUAL_EXPERIMENT", "SCALE_REVEAL"):
        line = R.narrative_function_contract(wo, [0], 6, name, W2.TREATMENTS)[0]
        openings[name] = line
        expected = W2.TREATMENTS[name]["beats"][0]
        check(expected[:40] in line,
              f"{name}: the contract quotes THIS treatment's own opening")
    check(len(set(openings.values())) == len(openings),
          "and four treatments get four different opening instructions")
    joined = "\n".join(openings.values())
    check("most surprising concrete image" not in joined,
          "no single house style is asserted over the treatment bank")

    # Fallback when the treatment is unknown must still say something useful.
    fallback = R.narrative_function_contract(wo, [0], 6, "NOT_A_TREATMENT", W2.TREATMENTS)[0]
    check("HOOK" in fallback, "an unknown treatment still yields the structural role")


# 3 ---------------------------------------------------------------------------
def test_3_a_beat_is_told_not_to_steal_the_payoff():
    """The exact mechanism behind the corpus's one measured craft collapse."""
    plan = _plan([1])
    joined = "\n".join(plan["narrative_contract"])
    check("NOT yours to rewrite" in joined,
          "repairing a middle beat names the payoff as off-limits")
    check("outlasted every human empire" in joined,
          "and quotes the payoff's actual point, so the model can avoid saying it")
    check("must not say it first" in joined,
          "with the obligation stated, not implied")


# 4 ---------------------------------------------------------------------------
def test_4_the_payoff_is_not_told_to_both_rewrite_and_preserve_itself():
    """Contradictory instructions are worse than none."""
    plan = _plan([1, 7])
    joined = "\n".join(plan["narrative_contract"])
    check("beat_index 7 is the PAYOFF" in joined, "the payoff is still given its role")
    check("NOT yours to rewrite" not in joined,
          "but is NOT simultaneously declared off-limits when it is a target")


# 5 ---------------------------------------------------------------------------
def test_5_the_licence_to_flatten_is_gone_and_a_better_move_is_named():
    prompt = R.build_repair_prompt(
        _script(), {"claims": [{"claim_id": "base_001", "claim_text": "c"}]},
        "ONE_OBJECT_JOURNEY", _plan([1]))
    check("It is fine for a rewritten beat to be more general" not in prompt,
          "the blanket licence to generalise is removed")
    check("generalising is the last resort" in prompt,
          "generalising is explicitly demoted to a last resort")
    check("DIFFERENT specific that IS supported" in prompt,
          "and swapping in another SUPPORTED specific is named as the first move "
          "(the evidence contained one in the real case, and repair did not use it)")
    check("do not borrow a later line's point" in prompt.lower(),
          "with evidence gravity called out directly")


# 6 ---------------------------------------------------------------------------
def test_6_the_repair_prompt_still_carries_the_deterministic_contract():
    """Craft guidance must not have displaced the mechanical constraints."""
    plan = _plan([1])
    plan["must_also_satisfy"] = ["Total spoken words must stay within 68-108."]
    prompt = R.build_repair_prompt(
        _script(), {"claims": [{"claim_id": "base_001", "claim_text": "c"}]},
        "ONE_OBJECT_JOURNEY", plan)
    check("68-108" in prompt, "the deterministic word budget still reaches the repairer")
    check("MECHANICALLY CHECKED" in prompt, "framed as a check, not a preference")
    check("ONLY rewrite beat_index" in prompt, "the do-not-touch-others instruction survives")
    check("DIAGNOSIS:" in prompt, "and so does the factual diagnosis")


# 7 ---------------------------------------------------------------------------
def test_7_an_unsafe_candidate_can_never_win_however_good_it_reads():
    """Factual integrity stays lexicographically mandatory."""
    unsafe_brilliant = {"writer_out": {"hook": "a"}, "hard_violations": [_V(1, "k", "v")],
                        "validate_err": None, "score": 9.9, "critic_avg": 9.9}
    safe_mediocre = {"writer_out": {"hook": "b"}, "hard_violations": [],
                     "validate_err": None, "score": 7.0, "critic_avg": 6.0}
    best = R.select_best_candidate([unsafe_brilliant, safe_mediocre])
    check(best is safe_mediocre, "a 9.9 with a hard violation loses to a clean 7.0")
    invalid = {"writer_out": {}, "hard_violations": [], "validate_err": "too long",
               "score": 9.5, "critic_avg": 9.5}
    check(R.select_best_candidate([invalid]) is None,
          "and a validate failure is disqualifying no matter how it scores")
    check(R.select_best_candidate([unsafe_brilliant]) is None,
          "with nothing clean available, the run aborts rather than shipping it")


# 8 ---------------------------------------------------------------------------
def test_8_a_repair_that_bought_nothing_is_not_promoted_over_a_better_earlier_round():
    """Every round stays a candidate, so a bad repair cannot bury a good parent."""
    parent = {"writer_out": {"hook": "parent"}, "hard_violations": [], "validate_err": None,
              "score": 5.57, "critic_avg": 7.0}
    worse_child = {"writer_out": {"hook": "child"}, "hard_violations": [], "validate_err": None,
                   "score": 4.14, "critic_avg": 5.0}
    check(R.select_best_candidate([parent, worse_child]) is parent,
          "the better earlier round still wins after a degrading repair "
          "(the corpus's one measured pair, 5.57 -> 4.14)")


# 9 ---------------------------------------------------------------------------
def test_9_two_deterministic_gates_no_longer_fight_over_an_abbreviation():
    """The mechanical trim shortened 'the United States' to 'the U.S.' to fit a
    hook cap, and provenance then called the result unsupported."""
    tb = json.loads((ROOT / "topic_bank.json").read_text(encoding="utf-8"))
    items = tb if isinstance(tb, list) else (tb.get("facts") or tb.get("topics") or [])
    fact = next(t for t in items if t.get("id") == "greenland_shark_age")
    inv = W2.build_claim_inventory(fact)
    cid = inv["claims"][0]["claim_id"]

    def hard_for(text):
        wo = {"hook": text, "hook_source_claim_ids": [cid], "beats": [],
              "payoff": "", "payoff_source_claim_ids": []}
        return R.hard_violations(R.check_traceability(wo, inv))

    check(not hard_for("A shark alive today was born before the United States existed."),
          "the verbatim cited entity was already clean (it was never the bug)")
    check(not hard_for("A shark alive today was born before the U.S. existed."),
          "and its initialism is now recognised as the same entity")
    check(hard_for("A shark alive today was born before Atlantis existed."),
          "while a fabricated entity still fails closed")
    check(R._initialism("United States") == "US", "initialism is computed, not looked up")
    check(R._initialism("Greenland") == "",
          "and a single-word entity yields no initialism, so nothing is loosened there")


# 10 --------------------------------------------------------------------------
def test_10_none_of_the_gates_moved():
    check(R.MAX_REPAIR_ROUNDS == 2, "the repair budget is still 2 rounds")
    import generate as G
    check(G.QUALITY_HARD_FLOOR == 6.8, "the quality floor is still 6.8")
    check(R.SEMANTIC_UNSUPPORTED_VERDICTS == {"UNSUPPORTED_ADDITION", "CONTRADICTED"},
          "the semantic taxonomy is unchanged -- no SUPPORTED_INFERENCE escape hatch")
    # Executable code only. The docstrings quote the real corpus case on
    # purpose -- prose naming a topic is evidence, logic branching on one is a
    # bug. An `or` in this assertion once made it nearly vacuous; it now strips
    # comments and docstrings and checks what actually runs.
    import ast
    src = (ROOT / "writer_v2_repair.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body[0].value.value = ""
    code = ast.unparse(tree).lower()
    for topic in ("greenland", "shark", "venus", "ming dynasty", "topic_bank"):
        check(topic not in code,
              f"no topic-specific logic in the repair module's executable code ({topic!r})")


if __name__ == "__main__":
    test_1_the_critic_preservation_signal_survives_every_tier()
    test_2_every_targeted_beat_is_told_what_it_is_for()
    test_2b_the_contract_takes_the_beat_purpose_from_THIS_treatment()
    test_3_a_beat_is_told_not_to_steal_the_payoff()
    test_4_the_payoff_is_not_told_to_both_rewrite_and_preserve_itself()
    test_5_the_licence_to_flatten_is_gone_and_a_better_move_is_named()
    test_6_the_repair_prompt_still_carries_the_deterministic_contract()
    test_7_an_unsafe_candidate_can_never_win_however_good_it_reads()
    test_8_a_repair_that_bought_nothing_is_not_promoted_over_a_better_earlier_round()
    test_9_two_deterministic_gates_no_longer_fight_over_an_abbreviation()
    test_10_none_of_the_gates_moved()
    print("craft-preserving repair tests: PASS")
