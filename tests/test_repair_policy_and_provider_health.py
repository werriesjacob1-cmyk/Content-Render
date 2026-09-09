#!/usr/bin/env python3
"""Flagship #6 regressions: repair-policy composition (C7) + provider health (S9).

Every failure class here is taken from run 34305189931, not invented:

  candidate 1 -- provenance repair ran 3 times while the SAME "only 1/3
                 mandatory key terms" rejection survived rounds 0, 1 and 2;
  candidate 2 -- a repair produced a 17-word hook, then two more rounds chased
                 semantics while that hook stayed 17 words;
  candidate 3 -- a repair cleared the hook and reintroduced "Thus".

The common cause was structural: classify_repair() returned ONE plan and
discarded validate_err whenever tier 1 fired -- 8 of 9 rounds. These tests pin
that the deterministic contract now rides with the primary target at every
tier, WITHOUT changing tier priority, round budget or any gate.

Zero network, zero providers.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import generate as G
import writer_v2_repair as R


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


class _V:
    """Stand-in for a TraceabilityViolation / semantic violation."""
    def __init__(self, beat_index, kind="semantic_unsupported_addition", value="x"):
        self.beat_index, self.kind, self.value = beat_index, kind, value


FACT = {"key_terms": ["around 400 years", "Greenland shark", "longest-lived vertebrate"]}
KEY_TERM_ERR = ("only 1/3 mandatory key terms named (['Greenland shark']) — the script must "
                "explicitly say at least 2 of ['around 400 years', 'Greenland shark', "
                "'longest-lived vertebrate']")


def _contract(fact=FACT):
    return G.narration_deterministic_contract(fact, spoken_lines=8)


def _writer_out(hook="Your morning coffee is younger than a Greenland shark.",
                payoff="Your lifespan is a blink."):
    return {"hook": hook,
            "beats": [{"voiceover": "It drifts in cold dark water."} for _ in range(6)],
            "payoff": payoff}


def _plan(validate_err, semantic=(0,), hard=(), fact=FACT, writer_out=None):
    return R.classify_repair(
        [_V(i, kind="unsupported_entity") for i in hard],
        [_V(i) for i in semantic],
        validate_err, {}, 6,
        narration_contract=_contract(fact),
        writer_out=_writer_out() if writer_out is None else writer_out,
    )


def _joined(plan):
    return " ".join(plan.get("must_also_satisfy") or [])


# --- C7: the three real failure classes ------------------------------------

def test_1_provenance_repair_still_carries_the_key_term_defect():
    """Candidate 1: 3 provenance rounds, key-term defect never once targeted."""
    plan = _plan(KEY_TERM_ERR, semantic=(0, 1, 2))
    check(plan["tier"] == 1 and plan["repair_type"] == "PROVENANCE",
          "an unsupported claim still outranks a mechanical defect -- tier priority unchanged")
    check("mandatory key terms" in _joined(plan),
          "but the key-term rejection now reaches the repair instead of being discarded")
    check("around 400 years" in _joined(plan) and "longest-lived vertebrate" in _joined(plan),
          "the exact missing terms are named, not just the fact that some are missing")
    check("Greenland shark" in (plan["must_preserve"] or []),
          "the term the script ALREADY says is protected, so a rewrite cannot make it worse")


def test_2_provenance_repair_is_told_the_hook_is_overlong():
    """Candidate 2: r1 made a 17-word hook; r2 chased semantics and kept it."""
    plan = _plan("hook length 17 words out of range", semantic=(4,))
    check(plan["tier"] == 1, "semantic violation still wins the primary target")
    j = _joined(plan)
    check("hook length 17 words out of range" in j,
          "the failing hook length is stated to the repair that is about to rewrite narration")
    check(f"{G.HOOK_WORD_LO}-{G.HOOK_WORD_HI} words" in j,
          "and the allowed range is stated, so the rewrite has a target not just a complaint")


def test_3_repair_clearing_the_hook_is_still_told_about_connectors():
    """Candidate 3: r1 fixed the hook, r2 brought "Thus" back."""
    plan = _plan("hook length 18 words out of range", semantic=())
    check(plan["tier"] == 2 and plan["repair_type"] == "HOOK",
          "with tier 1 clean the hook is the primary target, exactly as before")
    j = _joined(plan).lower()
    for word in ("thus", "however", "consequently"):
        check(word in j, f"the forbidden connector {word!r} is stated on a HOOK repair too")


def test_4_deterministic_constraints_never_replace_the_factual_target():
    """A mechanical constraint must not be able to demote a provenance repair."""
    plan = _plan("hook length 17 words out of range", semantic=(3,), hard=(1,))
    check(plan["tier"] == 1 and plan["repair_type"] == "PROVENANCE",
          "hard + semantic violations still take the primary target")
    check(1 in plan["target_beats"] and 3 in plan["target_beats"],
          "and the factual beats are what gets rewritten")
    check(plan.get("must_also_satisfy"),
          "the mechanical contract rides alongside rather than competing for the slot")


def test_5_length_constraints_are_present_so_a_fix_cannot_blow_the_budget():
    plan = _plan(KEY_TERM_ERR, semantic=(0,))
    j = _joined(plan)
    check(f"{G.SCENE_WORD_CAP} words" in j, "the per-scene cap is stated")
    check(f"{G.WORD_HARD_LO}-{G.WORD_HARD_HI}" in j,
          "the total-word hard range is stated, so working a term in cannot silently overrun it")


def test_6_malformed_inputs_never_raise():
    for bad in (None, "", 0, [], {}):
        plan = R.classify_repair([], [], bad if isinstance(bad, str) else None, bad if isinstance(bad, dict) else {},
                                 6, narration_contract=None, writer_out=None)
        check(isinstance(plan, dict) and "must_also_satisfy" in plan,
              f"a plan is still produced for malformed input {bad!r}")
    check(R.derive_must_also_satisfy(None, None, None) == [],
          "no contract and no error yields no constraints rather than an exception")
    check(R.classify_repair([], [_V(0)], KEY_TERM_ERR, {}, 6,
                            narration_contract=_contract(), writer_out={"beats": "not-a-list"}),
          "a malformed writer_out degrades gracefully instead of failing the round")


def test_the_contract_matches_what_validate_enforces():
    """Anti-drift: the prompt's numbers ARE the validator's numbers."""
    c = _contract()
    check((c["hook_word_lo"], c["hook_word_hi"]) == (G.HOOK_WORD_LO, G.HOOK_WORD_HI),
          "hook range comes from the constants validate() uses")
    check(c["scene_word_cap"] == G.SCENE_WORD_CAP, "per-scene cap is validate()'s cap")
    check((c["word_hard_lo"], c["word_hard_hi"]) == (G.WORD_HARD_LO, G.WORD_HARD_HI),
          "total-word hard range is validate()'s range")
    check(tuple(c["forbidden_connectors"]) == tuple(G.FORBIDDEN_CONNECTORS),
          "the connector list is the same tuple FORMAL_CONNECTOR_RE is built from")
    for w in G.FORBIDDEN_CONNECTORS:
        check(G.FORMAL_CONNECTOR_RE.search(f"and {w} it happened"),
              f"validate() actually rejects {w!r} that the contract promises it rejects")
    check(c["mandatory_key_terms_min"] == G.KEY_TERMS_MIN_NAMED,
          "the stated minimum is the minimum validate() requires")


def test_the_repair_prompt_actually_renders_the_contract():
    plan = _plan(KEY_TERM_ERR, semantic=(0,))
    prompt = R.build_repair_prompt(_writer_out(), {"claims": []}, "INSIDE_THE_SYSTEM", plan)
    check("MECHANICALLY CHECKED" in prompt,
          "the repair prompt carries the deterministic contract, not just the diagnosis")
    check("Greenland shark" in prompt, "and the preserved term appears in the prompt")
    check("around 400 years" in prompt, "and the missing term is named in the prompt")
    check("naturally" in prompt.lower() and "do not bolt" in prompt.lower(),
          "terms are demanded naturally, not keyword-stuffed")


def test_gates_and_budget_are_unchanged():
    check(R.MAX_REPAIR_ROUNDS == 2, "repair budget is still 2 rounds -- no extra rounds bought")
    check((G.WORD_HARD_LO, G.WORD_HARD_HI) == (68, 108), "word limits unchanged")
    check(G.SCENE_WORD_CAP == 25, "per-scene cap unchanged")
    check(G.QUALITY_HARD_FLOOR == 6.8, "quality floor unchanged")


# --- S9: provider session health -------------------------------------------

def test_7_authoritative_rate_limit_starts_a_bounded_cooldown():
    G._provider_health_reset()
    wait = G.note_provider_rate_limited("groq", "m1", retry_after_s=8.0, now=1000.0)
    check(wait == 8.0, "the provider's OWN stated delay is used, not an invented penalty")
    skip, remaining = G.should_skip_provider("groq", "m1", now=1001.0)
    check(skip and 6.9 < remaining < 7.1, f"still cooling 7s later (got {remaining})")
    check(not G.should_skip_provider("groq", "other-model", now=1001.0)[0],
          "cooldown is per (provider, model) -- one model does not mute the whole provider")


def test_8_a_cooling_model_cannot_be_reached_through_another_path():
    G._provider_health_reset()
    G.note_provider_rate_limited("groq", "m1", retry_after_s=30.0, now=2000.0)
    check(G.should_skip_provider("groq", "m1", now=2001.0)[0],
          "the strict certification loop skips it")
    check(G.should_skip_provider("groq", "m1", now=2002.0)[0],
          "and the loose fallback chain skips it too -- not two doors into the same model")
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "quality_writer_provider_resilience.py"), encoding="utf-8").read()
    check("should_skip_provider(" in src,
          "the certification strict loop consults provider health")
    check("note_provider_rate_limited(" in src,
          "and records its own 429s into the same session state")


def test_9_a_provider_recovers_and_is_never_permanently_disabled():
    G._provider_health_reset()
    G.note_provider_rate_limited("groq", "m1", retry_after_s=5.0, now=3000.0)
    check(not G.should_skip_provider("groq", "m1", now=3006.0)[0],
          "once the cooldown expires the provider is tried again on its own merits")
    G.note_provider_rate_limited("groq", "m1", retry_after_s=5.0, now=3010.0)
    G.note_provider_healthy("groq", "m1")
    check(not G.should_skip_provider("groq", "m1", now=3011.0)[0],
          "a success clears the cooldown immediately")
    check(G.note_provider_rate_limited("groq", "m1", retry_after_s=99999.0, now=3020.0)
          <= G.PROVIDER_COOLDOWN_MAX_S,
          "an absurd retry-after is clamped -- a provider cannot remove itself for the session")


def test_10_every_skip_and_recovery_is_recorded():
    G._provider_health_reset()
    G.note_provider_rate_limited("groq", "m1", retry_after_s=9.0, now=4000.0)
    G.should_skip_provider("groq", "m1", now=4001.0)
    G.note_provider_healthy("groq", "m1")
    events = G.provider_health_events()
    kinds = [e["event"] for e in events]
    check(kinds == ["rate_limited", "skipped_cooling", "recovered"],
          f"the full lifecycle is visible in order (got {kinds})")
    check(all(e.get("provider") == "groq" and e.get("model") == "m1" for e in events),
          "each event names the exact provider and model")
    check(events[0]["retry_after_reported"] is True,
          "whether the wait came from the provider or from our default is recorded")
    check(events[1]["remaining_s"] > 0, "a skip records how much cooldown was left")


def test_health_evidence_is_kept_out_of_debug_calls():
    """debug_calls is read as the record of calls MADE; a skip is not a call.

    wr21_quality_generate reads calls[0] as the draft model and
    quality_learning_ledger reads the last entry with a truthy provider as the
    provider used -- a skip entry carrying "provider": "groq" would be reported
    as the model that wrote the script.
    """
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "generate.py"), encoding="utf-8").read()
    health = src.split("def should_skip_provider(", 1)[1].split("\ndef ", 1)[0]
    check("debug_calls" not in health, "the skip path never appends to debug_calls")
    check("_PROVIDER_HEALTH_EVENTS" in health,
          "it records to the separate provider-health channel instead")


def test_all_three_groq_entry_points_consult_health():
    """There are THREE independent doors into Groq, not two.

    _walk (the fallback chain), the certification strict loop, and
    _v2_structured_call -- which calls Groq directly and is the door the
    production orchestrator uses for every draft, critic and repair round. A
    cooldown honoured by only some of them is not a cooldown.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gen = open(os.path.join(root, "generate.py"), encoding="utf-8").read()
    cert = open(os.path.join(root, "quality_writer_provider_resilience.py"),
                encoding="utf-8").read()

    walk = gen.split("def _walk(", 1)[1].split("return None, None, None", 1)[0]
    structured = gen.split("def _v2_structured_call(", 1)[1].split("\ndef ", 1)[0]
    for name, src in (("_walk", walk), ("_v2_structured_call", structured),
                      ("certification strict loop", cert)):
        check("should_skip_provider(" in src, f"{name} checks provider health")
        check("note_provider_rate_limited(" in src,
              f"{name} records its own 429s into the shared session state")
    check("note_provider_healthy(" in structured,
          "_v2_structured_call clears the cooldown when Groq answers successfully")


def test_the_chain_consults_health_before_spending_a_request():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "generate.py"), encoding="utf-8").read()
    walk = src.split("def _walk(", 1)[1].split("return None, None, None", 1)[0]
    check("should_skip_provider(" in walk,
          "the provider loop checks health BEFORE issuing the request")
    skip_at = walk.find("should_skip_provider(")
    call_at = walk.find("_call_gemini(")
    check(0 < skip_at < call_at,
          "the check happens before the first provider call, not after paying for one")
    check("note_provider_rate_limited(" in walk,
          "and a 429 in the chain records the cooldown")


if __name__ == "__main__":
    test_1_provenance_repair_still_carries_the_key_term_defect()
    test_2_provenance_repair_is_told_the_hook_is_overlong()
    test_3_repair_clearing_the_hook_is_still_told_about_connectors()
    test_4_deterministic_constraints_never_replace_the_factual_target()
    test_5_length_constraints_are_present_so_a_fix_cannot_blow_the_budget()
    test_6_malformed_inputs_never_raise()
    test_the_contract_matches_what_validate_enforces()
    test_the_repair_prompt_actually_renders_the_contract()
    test_gates_and_budget_are_unchanged()
    test_7_authoritative_rate_limit_starts_a_bounded_cooldown()
    test_8_a_cooling_model_cannot_be_reached_through_another_path()
    test_9_a_provider_recovers_and_is_never_permanently_disabled()
    test_10_every_skip_and_recovery_is_recorded()
    test_health_evidence_is_kept_out_of_debug_calls()
    test_all_three_groq_entry_points_consult_health()
    test_the_chain_consults_health_before_spending_a_request()
    print("repair policy + provider health tests: PASS")
