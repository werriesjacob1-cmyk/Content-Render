#!/usr/bin/env python3
"""Zero-network regressions for the Writer V2.1 length contract + craft rules.

ROOT CAUSE THIS LOCKS DOWN (flagship runs #2-#5, 36 replayed rounds):
the V2.1 writer prompt never stated a total word budget or the per-scene word
cap. LENGTH_HINT/WORDS_PER_SCENE only ever reached the LEGACY build_prompt() in
generate.py, so the certification writer was rejected 18 times out of 36 rounds
(50%) for limits it was never told existed. The bug was not model weakness; it
was a prompt/validator contract break, and nothing in the suite could see it.

The load-bearing test here is the drift test: the numbers the writer is TOLD
must be literally the numbers validate() ENFORCES.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import generate as G
import writer_v2 as W

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _prompt(spoken_lines=8):
    inventory = {
        "claims": [{"claim_id": "claim_001", "claim_text": "a sealed evidence claim"}],
        "key_terms": ["Greenland shark"],
        "provenance_note": "grounded",
    }
    return W.build_writer_prompt_v2(
        "INSIDE_THE_SYSTEM", inventory,
        length_contract=G.writer_length_contract(spoken_lines=spoken_lines),
    )


def test_writer_is_told_the_exact_limits_validate_enforces():
    """The drift test. If these ever disagree again, this fails loudly."""
    c = G.writer_length_contract(spoken_lines=8)
    check(c["word_lo"] == G.WORD_LO and c["word_hi"] == G.WORD_HI,
          "contract soft window is generate's own WORD_LO/WORD_HI")
    check(c["word_hard_lo"] == G.WORD_HARD_LO and c["word_hard_hi"] == G.WORD_HARD_HI,
          "contract hard window is generate's own WORD_HARD_LO/WORD_HARD_HI")
    check(c["scene_word_cap"] == G.SCENE_WORD_CAP,
          "contract per-scene cap is generate's own SCENE_WORD_CAP")

    text = _prompt()
    for field in ("word_lo", "word_hi", "word_hard_lo", "word_hard_hi", "scene_word_cap"):
        check(str(c[field]) in text,
              f"the assembled writer prompt literally states {field}={c[field]}")


def test_prompt_states_a_total_word_budget_at_all():
    """The exact historical gap: no total-word budget anywhere in the prompt."""
    text = _prompt()
    check("LENGTH CONTRACT" in text, "prompt carries an explicit LENGTH CONTRACT block")
    check(re.search(r"TOTAL spoken words", text), "prompt states a TOTAL spoken-word budget")
    check(re.search(r"NO single spoken line may exceed \d+ words", text),
          "prompt states the per-line word cap the validator enforces")
    check("COUNT the words you actually wrote" in text,
          "prompt tells the writer to count before answering, not to rely on trimming")
    check("nothing does" in text,
          "prompt corrects the false assumption that something downstream trims overlength text")


def test_length_contract_is_actually_wired_into_the_orchestrator():
    """A perfect contract that no caller passes is still the same outage."""
    src = open(os.path.join(ROOT, "writer_v21_orchestrator.py"), encoding="utf-8").read()
    check("length_contract=" in src, "orchestrator passes length_contract into the writer prompt")
    check("writer_length_contract" in src,
          "orchestrator sources the contract from generate's single source of truth")
    # and the wiring must survive assembly, not just exist as a kwarg
    check("LENGTH CONTRACT" in _prompt(), "wired contract reaches the assembled prompt text")


def test_words_per_line_scales_with_the_treatment_shape():
    eight = G.writer_length_contract(spoken_lines=8)
    four = G.writer_length_contract(spoken_lines=4)
    check(four["words_per_line"] > eight["words_per_line"],
          "fewer spoken lines means a larger per-line budget, not a fixed number")
    check(eight["words_per_line"] >= 1 and G.writer_length_contract(spoken_lines=0)["words_per_line"] >= 1,
          "per-line budget never degenerates to zero or divides by zero")


def test_craft_rules_target_each_observed_failure_family():
    """Every rule here exists because the corpus shows the writer failing it."""
    text = _prompt()
    check("EVERY BEAT MUST ADVANCE" in text,
          "prompt forbids re-describing one mechanism across several beats (4 repetition "
          "+ 3 fact-restated rounds in the corpus)")
    check("what does the viewer know now that they did not know one line ago" in text,
          "prompt gives a concrete per-line test for genuine escalation")
    check("A REAL QUESTION, NOT A QUESTION MARK" in text,
          "prompt bans the declarative-plus-question-mark shape (4 corpus rounds)")
    check("statement wearing a question mark" in text,
          "prompt shows a concrete BAD example, not only an abstract ban")
    check("PLAIN WORDS" in text and "chemical chaperone" in text,
          "prompt requires plain translation and shows a jargon-gloss that does NOT count")
    check("THE PAYOFF MUST BE CONCRETE" in text,
          "prompt bans generic-uplift endings")
    check("would fit equally well at the end of ANY other science video" in text,
          "prompt gives a portable test for a weak payoff rather than a banned-phrase list only")


def test_craft_rules_are_generic_not_topic_specific():
    """The fixes must generalise; a Greenland-shark hack would be a regression."""
    static = W.WRITER_V2_STATIC.lower()
    for banned in ("greenland", "shark", "venus", "eclipse", "trimethylamine"):
        check(banned not in static,
              f"writer prompt contains no topic-specific hack for {banned!r}")


if __name__ == "__main__":
    test_writer_is_told_the_exact_limits_validate_enforces()
    test_prompt_states_a_total_word_budget_at_all()
    test_length_contract_is_actually_wired_into_the_orchestrator()
    test_words_per_line_scales_with_the_treatment_shape()
    test_craft_rules_target_each_observed_failure_family()
    test_craft_rules_are_generic_not_topic_specific()
    print("writer length-contract tests: PASS")
