#!/usr/bin/env python3
"""ONE deterministic Writer-repair correction that survives a disproven hypothesis.

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

WITHDRAWN — the initialism fix. An earlier version of this release also taught
traceability that a cited multi-word entity's initialism counts as that entity,
so "United States" would support "U.S.". Adversarial review killed it, and it
deserved to die twice over:

1. **It opened a hole in the HARD provenance gate.** Initials are a lossy hash,
   so a FABRICATED entity passes whenever its initials collide with an unrelated
   cited one. That is the exact class of guardrail this system exists to
   enforce, traded for a convenience.

   *A correction to how this was first written up.* The repro that raised it was
   "The US government funded this secret ice mission" against a cited
   "Ultraviolet Sensor", which returns zero hard violations. It does — but NOT
   because of the initialism rule. "us" is in `_CONNECTIVE_STOPWORDS` (it is a
   pronoun), so "US" is filtered out before any entity check runs; that line
   returns zero on plain main too, with the fix absent. The hole is real all the
   same, and `test_6` demonstrates it with an acronym that is not a stopword.
2. **Its stated justification was mis-attributed.** I claimed two deterministic
   gates were fighting -- that `deterministic_mechanical_trim` abbreviated the
   hook and provenance then rejected it. `deterministic_mechanical_trim`
   explicitly refuses to touch the hook or payoff and never invents text. The
   abbreviation came from an LLM repair round, so there was no gate conflict to
   resolve in the first place.

Traceability is therefore byte-identical to main. `test_5` pins that, including
that "U.S." is still rejected -- a known, accepted false positive, failing
CLOSED, which is the correct direction for a factual gate.

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
def test_5_traceability_is_unchanged_and_still_fails_closed():
    """The withdrawn initialism fix must not be here, in any form."""
    src = (ROOT / "writer_v2_repair.py").read_text(encoding="utf-8")
    check("_initialism" not in src and "_entity_supported" not in src,
          "the initialism helpers are gone from production")

    inv = _inventory()
    cid = inv["claims"][0]["claim_id"]
    check(not _hard_for("A shark born before the United States existed.", inv, cid),
          "a verbatim cited entity is supported, exactly as on main")
    check(_hard_for("A shark born before Atlantis existed.", inv, cid),
          "a fabricated entity fails closed")
    check(_hard_for("A shark born before the U.S. existed.", inv, cid),
          "and an abbreviation is still REJECTED -- a known false positive that "
          "fails closed, which is the correct direction for a factual gate")


# 6 ----------------------------------------------------------------------------
def test_6_an_initialism_collision_cannot_admit_a_fabricated_entity():
    """The hole the withdrawn fix opened. This is the regression that keeps it shut.

    Initials are a lossy hash. Cite "Deep Nautical Analysis" and its initials are
    "DNA" -- so the withdrawn rule accepted a wholly fabricated "DNA" as though
    the claims supported it. Verified against a faithful reconstruction of the
    withdrawn helpers below, so this test proves the hole was real AND that it is
    now shut, rather than asserting an absence nobody demonstrated.

    The acronym here is deliberately NOT a stopword, and it is placed MID-
    SENTENCE. Both matter, and both are why the original repro proved nothing:
    "us" is a pronoun in `_CONNECTIVE_STOPWORDS` so "US" never reaches the entity
    check at all, and a single-word entity in sentence-initial position is
    classified WEAK and reported soft by design (see `_check_line`'s docstring --
    that ambiguity is deliberate V2.1 behaviour, not a gap this release touches).
    """
    inv = {"claims": [{"claim_id": "c1",
                       "claim_text": "The Deep Nautical Analysis dated the wreck.",
                       "allowed_entities": ["Deep Nautical Analysis"], "allowed_terms": [],
                       "allowed_numbers": [], "allowed_units": []}],
           "key_terms": []}

    # The withdrawn rule, reconstructed verbatim from the reverted diff.
    import re as _re

    def _withdrawn_supported(entity, allowed_entities):
        e = (entity or "").strip().lower()
        if not e:
            return True
        if e in allowed_entities or R._strip_possessive(e) in allowed_entities:
            return True
        compact = _re.sub(r"[^a-z]", "", e).upper()
        if len(compact) >= 2:
            for allowed in allowed_entities:
                words = [w for w in _re.findall(r"[A-Za-z]+", allowed or "") if w]
                if len(words) >= 2 and "".join(w[0] for w in words).upper() == compact:
                    return True
        return False

    cited = {"deep nautical analysis"}
    check(_withdrawn_supported("DNA", cited),
          "the withdrawn rule DID admit a fabricated acronym -- the hole was real")
    check(not _withdrawn_supported("Atlantis", cited),
          "(it was not simply admitting everything)")

    hard = _hard_for("The wreck was exposed as a forgery by DNA.", inv, "c1")
    check(hard, "and today that same fabricated acronym FAILS the hard gate")
    check(any(v.kind == "unsupported_entity" and v.value == "DNA" for v in hard),
          f"failing specifically as an unsupported entity ({[v.value for v in hard]})")

    check(not _hard_for("The Deep Nautical Analysis dated the wreck.", inv, "c1"),
          "while the verbatim cited entity is still supported")


# 7 ----------------------------------------------------------------------------
def test_7_must_preserve_cannot_contradict_the_repair_it_rides_with():
    """The second defect adversarial review found in fix A.

    The critic writes `must_preserve` from a craft reading and never sees the
    mechanical traceability pass. Carried into tier 1 unfiltered, it produced
    "remove Atlantis, it is unsupported" and "MUST PRESERVE EXACTLY: Atlantis"
    in the same prompt -- a contradiction main could not produce, because tier 1
    never received this list.
    """
    v = R.TraceabilityViolation(1, "unsupported_entity", "Atlantis", ["c1"],
                                detail="fabricated", severity="hard")
    plan = R.classify_repair([v], [], None,
                             {"must_preserve": ["Atlantis", "the transition in beat 2"]},
                             3, narration_contract=None, writer_out=None)
    check("Atlantis" not in plan["must_preserve"],
          "the flagged text is dropped from must_preserve")
    check("the transition in beat 2" in plan["must_preserve"],
          "while the critic's unrelated, still-valid entry survives")

    wo = {"hook": "x", "beats": [{"voiceover": "a"}, {"voiceover": "Atlantis was found"},
                                 {"voiceover": "c"}], "payoff": "d"}
    prompt = R.build_repair_prompt(wo, {"claims": []}, "TREATMENT", plan)
    check("Atlantis" in prompt, "the diagnosis still names what must change")
    preserve_line = [ln for ln in prompt.splitlines() if "MUST PRESERVE EXACTLY" in ln]
    check(preserve_line and "Atlantis" not in preserve_line[0],
          f"but the preserve line no longer demands keeping it ({preserve_line})")


# 8 ----------------------------------------------------------------------------
def test_8_substring_overlap_counts_as_contradiction():
    """A partial name is still the thing the diagnosis says must go."""
    v = R.TraceabilityViolation(1, "unsupported_entity", "United States", ["c1"],
                                detail="x", severity="hard")
    plan = R.classify_repair([v], [], None,
                             {"must_preserve": ["the United States comparison", "pacing"]},
                             3, narration_contract=None, writer_out=None)
    check("the United States comparison" not in plan["must_preserve"],
          "an entry CONTAINING the flagged text is dropped")
    check("pacing" in plan["must_preserve"], "an unrelated entry is kept")


# 9 ----------------------------------------------------------------------------
def test_9_malformed_and_bloated_must_preserve_is_handled():
    v = R.TraceabilityViolation(1, "unsupported_entity", "Atlantis", ["c1"],
                                detail="x", severity="hard")
    plan = R.classify_repair(
        [v], [], None,
        {"must_preserve": [None, "", "keep this", "keep this", "KEEP THIS", 42, {"a": 1}]},
        3, narration_contract=None, writer_out=None)
    mp = plan["must_preserve"]
    check(None not in mp and "" not in mp, "None/empty entries are dropped")
    check(sum(1 for x in mp if str(x).strip().lower() == "keep this") == 1,
          f"case-insensitive duplicates collapse to one ({mp})")
    wo = {"hook": "x", "beats": [{"voiceover": "a"}], "payoff": "d"}
    prompt = R.build_repair_prompt(wo, {"claims": []}, "T", plan)
    check("keep this" in prompt, "and a non-string entry does not crash the builder")


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
    test_5_traceability_is_unchanged_and_still_fails_closed()
    test_6_an_initialism_collision_cannot_admit_a_fabricated_entity()
    test_7_must_preserve_cannot_contradict_the_repair_it_rides_with()
    test_8_substring_overlap_counts_as_contradiction()
    test_9_malformed_and_bloated_must_preserve_is_handled()
    test_10_no_factual_semantic_or_quality_gate_changed()
    print("deterministic repair fix tests: PASS")
