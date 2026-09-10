#!/usr/bin/env python3
"""Two deterministic Writer-repair corrections that survive a disproven hypothesis.

BACKGROUND, STATED HONESTLY

These fixes were found while investigating "provenance repair systematically
degrades craft". **That hypothesis is NOT supported.** A deterministic rescore of
all 36 parent->child repair pairs in the corpus
(`reports/flagship_craft_rescore.md`, zero LLM, zero network) found that among
the 24 pairs where repair improved factual/mechanical state, craft went 10
improved / 5 flat / 9 degraded — approximately neutral. Flagship #7's craft
collapse is a real single case, not a measured epidemic.

The behavioural craft intervention that hypothesis motivated is therefore NOT in
production; it stays on PR #82 as an unmerged experiment. The two fixes covered
here are different in kind: they are deterministic control-plumbing and
traceability defects that are wrong regardless of what the craft answer turned
out to be.

FIX 1 — the critic's own preservation list was discarded where it matters most.
`build_critic_prompt` asks the critic for `must_preserve`: "a short list of
specific things in the beats you are NOT flagging that the rewrite must not
disturb (a phrase, a fact, a transition that already works)". `classify_repair`
used it on tier 3 only. Tier 1 (an unsupported claim) and tier 2 (a validate
failure) computed it and dropped it — and those two tiers fire in nearly every
real repair round.

FIX 2 — two deterministic gates fought over an abbreviation.
`deterministic_mechanical_trim` shortened "the United States" to "the U.S." to
fit a hook word cap, changing nothing else. The provenance checker then flagged
"U.S" as unsupported: semantic violations 0 -> 5 plus a new hard violation. That
manufactured a PROVENANCE repair — the type that rewrites factual content — for
a defect that did not exist. The verbatim form was always clean.

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
    def __init__(self, beat_index, kind, value):
        self.beat_index, self.kind, self.value, self.severity = beat_index, kind, value, "hard"


def _script(num_beats=6):
    return {
        "hook": "A Greenland shark swimming today was born before America existed.",
        "hook_source_claim_ids": ["base_001"],
        "beats": [{"voiceover": f"beat {i} text", "source_claim_ids": ["base_001"]}
                  for i in range(1, num_beats + 1)],
        "payoff": "That relic outlasted every empire founded since it formed.",
        "payoff_source_claim_ids": ["base_001"],
    }


def _plan(*, hard=(), validate_err=None, critic=None, num_beats=6, terms=("Greenland shark",)):
    return R.classify_repair(
        list(hard), [], validate_err, critic or {}, num_beats,
        narration_contract={"mandatory_key_terms": list(terms)},
        writer_out=_script(num_beats),
    )


KEEP = "the transition in beat 2 that already works"


# 1 ----------------------------------------------------------------------------
def test_1_tier1_carries_critic_must_preserve():
    plan = _plan(hard=[_V(1, "unsupported_entity", "X")],
                 critic={"must_preserve": [KEEP]})
    check(plan["tier"] == 1, f"an unsupported claim is tier 1 (got {plan['tier']})")
    check(plan["repair_type"] == "PROVENANCE", "and routes to PROVENANCE")
    check(KEEP in plan["must_preserve"],
          "tier 1 now carries the critic's must_preserve instead of discarding it")


# 2 ----------------------------------------------------------------------------
def test_2_tier2_carries_critic_must_preserve():
    plan = _plan(validate_err="hook length 18 words out of range",
                 critic={"must_preserve": [KEEP]})
    check(plan["tier"] == 2, f"a validate failure is tier 2 (got {plan['tier']})")
    check(KEEP in plan["must_preserve"],
          "tier 2 now carries the critic's must_preserve too")


# 3 ----------------------------------------------------------------------------
def test_3_tier3_behaviour_is_unchanged():
    plan = _plan(critic={"must_preserve": [KEEP], "repair_type": "ESCALATION",
                         "target_beats": [2], "diagnosis": "beat 2 does not escalate"})
    check(plan["tier"] == 3, f"a craft-only verdict is still tier 3 (got {plan['tier']})")
    check(plan["repair_type"] == "ESCALATION", "the critic's repair_type still drives tier 3")
    check(plan["target_beats"] == [2], "and its target_beats still drive the targeting")
    check(KEEP in plan["must_preserve"], "with must_preserve still present, as before")


# 4 ----------------------------------------------------------------------------
def test_4_key_terms_still_compose_with_the_critic_list():
    """Neither source may shadow the other, and neither may duplicate."""
    plan = _plan(hard=[_V(1, "unsupported_entity", "X")],
                 critic={"must_preserve": [KEEP]})
    mp = plan["must_preserve"]
    check(KEEP in mp, "the critic's entry survives")
    check("Greenland shark" in mp, "the mandatory key term named in the script survives")
    check(len(mp) == len(set(mp)), f"and nothing is duplicated ({mp})")

    dupe = _plan(hard=[_V(1, "unsupported_entity", "X")],
                 critic={"must_preserve": ["Greenland shark"]})
    check(dupe["must_preserve"].count("Greenland shark") == 1,
          "a term named by BOTH sources appears exactly once")

    none_critic = _plan(hard=[_V(1, "unsupported_entity", "X")])
    check("Greenland shark" in none_critic["must_preserve"],
          "and with no critic list at all, key-term preservation still works")


# --- fixture-backed traceability cases ----------------------------------------
def _inventory():
    tb = json.loads((ROOT / "topic_bank.json").read_text(encoding="utf-8"))
    items = tb if isinstance(tb, list) else (tb.get("facts") or tb.get("topics") or [])
    fact = next(t for t in items if t.get("id") == "greenland_shark_age")
    return W2.build_claim_inventory(fact)


def _hard_for(text, inv, cid):
    wo = {"hook": text, "hook_source_claim_ids": [cid], "beats": [],
          "payoff": "", "payoff_source_claim_ids": []}
    return R.hard_violations(R.check_traceability(wo, inv))


# 5 ----------------------------------------------------------------------------
def test_5_united_states_supports_u_s():
    inv = _inventory()
    cid = inv["claims"][0]["claim_id"]
    check(not _hard_for("A shark born before the United States existed.", inv, cid),
          "the verbatim cited entity was already clean -- it was never the bug")
    check(not _hard_for("A shark born before the U.S. existed.", inv, cid),
          "and its initialism is now recognised as the same entity")


# 6 ----------------------------------------------------------------------------
def test_6_a_generic_multiword_entity_supports_its_real_initialism():
    """Nothing about this is Greenland- or America-specific."""
    inv = {"claims": [{"claim_id": "c1", "claim_text": "x",
                       "allowed_entities": ["World Health Organization"],
                       "allowed_terms": [], "allowed_numbers": [], "allowed_units": []}],
           "key_terms": []}
    check(not _hard_for("The World Health Organization said so.", inv, "c1"),
          "the verbatim multi-word entity is supported")
    check(not _hard_for("The WHO said so.", inv, "c1"),
          "and so is its genuine initialism")
    check(R._initialism("World Health Organization") == "WHO",
          "the initialism is computed from the entity, not looked up in a list")


# 7 ----------------------------------------------------------------------------
def test_7_a_fabricated_entity_does_not_become_supported():
    inv = _inventory()
    cid = inv["claims"][0]["claim_id"]
    check(_hard_for("A shark born before Atlantis existed.", inv, cid),
          "an invented entity still fails closed")
    check(_hard_for("A shark born before the U.K. existed.", inv, cid),
          "and an initialism of something NOT in the cited claim is still rejected")
    check(_hard_for("A shark studied by NASA scientists.", inv, cid),
          "an unrelated real acronym is not admitted either")


# 8 ----------------------------------------------------------------------------
def test_8_a_single_word_entity_yields_no_bogus_initialism():
    check(R._initialism("Greenland") == "",
          "a one-word entity produces no initialism, so nothing is loosened")
    check(R._initialism("") == "" and R._initialism(None) == "",
          "and empty/None input is handled without inventing one")
    inv = {"claims": [{"claim_id": "c1", "claim_text": "x", "allowed_entities": ["Greenland"],
                       "allowed_terms": [], "allowed_numbers": [], "allowed_units": []}],
           "key_terms": []}
    check(_hard_for("A shark seen near Antarctica.", inv, "c1"),
          "a different entity is not matched against a single-word claim entity")


# 9 ----------------------------------------------------------------------------
def test_9_punctuation_and_case_variants():
    inv = {"claims": [{"claim_id": "c1", "claim_text": "x",
                       "allowed_entities": ["United States"],
                       "allowed_terms": [], "allowed_numbers": [], "allowed_units": []},],
           "key_terms": []}
    for variant in ("U.S.", "US", "U.S", "u.s."):
        check(R._entity_supported(variant, {"united states"}),
              f"{variant!r} resolves to the cited 'United States'")
    check(not R._entity_supported("U.S.A.", {"united states"}),
          "but a three-letter initialism does NOT match a two-word entity")
    check(not R._entity_supported("X", {"united states"}),
          "and a single letter is too short to match anything")


# 10 ---------------------------------------------------------------------------
def test_10_no_factual_semantic_or_quality_gate_changed():
    import generate as G
    check(G.QUALITY_HARD_FLOOR == 6.8, "the quality floor is still 6.8")
    check(R.MAX_REPAIR_ROUNDS == 2, "the repair budget is still 2 rounds")
    check(R.SEMANTIC_UNSUPPORTED_VERDICTS == {"UNSUPPORTED_ADDITION", "CONTRADICTED"},
          "the semantic taxonomy is unchanged -- no SUPPORTED_INFERENCE added")
    check(G.QUALITY_CRITERION_FLOORS["coherence"] == 7
          and G.QUALITY_CRITERION_FLOORS["hook"] == 6,
          "the per-criterion floors are unchanged")

    # The behavioural experiment must NOT be in production.
    src = (ROOT / "writer_v2_repair.py").read_text(encoding="utf-8")
    for marker in ("narrative_function_contract", "beat_purpose", "BEAT_ROLE",
                   "WHAT THESE BEATS ARE FOR", "generalising is the last resort"):
        check(marker not in src,
              f"the craft experiment stays out of production ({marker!r} absent)")
    check("It is fine for a rewritten beat to be more general" in src,
          "and the PROVENANCE instruction is byte-for-byte the shipped one, "
          "not the experiment's rewrite")

    orch = (ROOT / "writer_v21_orchestrator.py").read_text(encoding="utf-8")
    check("treatments=getattr" not in orch,
          "no treatment plumbing leaked into the orchestrator -- it existed only "
          "to feed the experiment")


if __name__ == "__main__":
    test_1_tier1_carries_critic_must_preserve()
    test_2_tier2_carries_critic_must_preserve()
    test_3_tier3_behaviour_is_unchanged()
    test_4_key_terms_still_compose_with_the_critic_list()
    test_5_united_states_supports_u_s()
    test_6_a_generic_multiword_entity_supports_its_real_initialism()
    test_7_a_fabricated_entity_does_not_become_supported()
    test_8_a_single_word_entity_yields_no_bogus_initialism()
    test_9_punctuation_and_case_variants()
    test_10_no_factual_semantic_or_quality_gate_changed()
    print("deterministic repair fix tests: PASS")
