#!/usr/bin/env python3
"""Zero-provider regressions for Writer V2.1's runtime narration contract.

Two independent investigations of flagship runs #2-#5 reached the same root
cause: the Writer was validated against a word window and a per-scene cap its
prompt never carried, and the base prompt also OFFERED a question-mark hook that
validate() hard-rejects. This file keeps the resulting behaviour locked down.

The behaviours asserted here originate from the PR #73 runtime-contract work.
The implementation that survived integration is PR #75's: the contract is built
once by generate.writer_length_contract() from the SAME constants validate()
enforces, rendered by writer_v2.render_length_contract(), and injected by the
orchestrator into BOTH the initial draft and every repair call. The duplicate
_runtime_narration_contract() implementation was not carried over -- only its
proven requirements, restated against the surviving architecture.
"""
import inspect
import os
import sys

os.environ.setdefault("GROQ_API_KEY", "x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate as G
import writer_v2 as W
import writer_v21_orchestrator as O


def _contract_text(treatment="INSIDE_THE_SYSTEM"):
    beats = len((W.TREATMENTS.get(treatment) or {}).get("beats") or [])
    return W.render_length_contract(G.writer_length_contract(spoken_lines=beats + 2))


def test_contract_reflects_active_runtime_limits():
    treatment = "INSIDE_THE_SYSTEM"
    beat_count = len((W.TREATMENTS.get(treatment) or {}).get("beats") or [])
    contract = _contract_text(treatment)
    assert f"aim {G.WORD_LO}-{G.WORD_HI}" in contract
    assert f"Hard limits {G.WORD_HARD_LO}-{G.WORD_HARD_HI}" in contract
    assert f"exceed {G.SCENE_WORD_CAP} words" in contract
    # the per-line budget is derived from the real spoken-scene count
    assert f"{beat_count + 2} lines" in contract


def test_contract_updates_when_runtime_window_changes():
    saved = (G.WORD_LO, G.WORD_HI, G.WORD_HARD_LO, G.WORD_HARD_HI, G.SCENE_WORD_CAP)
    try:
        G.WORD_LO, G.WORD_HI = 91, 109
        G.WORD_HARD_LO, G.WORD_HARD_HI = 82, 117
        G.SCENE_WORD_CAP = 23
        contract = _contract_text("CASE_FILE")
        assert "aim 91-109" in contract
        assert "Hard limits 82-117" in contract
        assert "exceed 23 words" in contract
    finally:
        G.WORD_LO, G.WORD_HI, G.WORD_HARD_LO, G.WORD_HARD_HI, G.SCENE_WORD_CAP = saved


def test_contract_resolves_live_hook_and_craft_conflicts():
    """The prompt must not offer options validate() rejects."""
    static = W.WRITER_V2_STATIC
    # The original contradiction: the CURIOSITY GAP rule used to say the "?" may
    # go on "the hook OR one of the first 3 beats", while validate() rejects ANY
    # question-mark hook. The model took the offered option 4 times in the corpus.
    assert "the hook OR one of the first 3 beats" not in static
    assert "The HOOK is never the question" in static
    assert "Never open ON a question mark" in static
    # craft rules covering the remaining observed failure families
    assert "EVERY BEAT MUST ADVANCE" in static
    assert "the same thing, worded differently" in static
    assert "A REAL QUESTION, NOT A QUESTION MARK" in static
    assert "PLAIN WORDS" in static
    assert "THE PAYOFF MUST BE CONCRETE" in static


def test_contract_is_load_bearing_on_initial_and_repair_calls():
    source = inspect.getsource(O.generate_candidate_v21)
    assert "length_contract=length_contract" in source
    assert "prompt = W.build_writer_prompt_v2(" in source
    # The SAME budget rides on every repair call too: a repair rewrites
    # narration, so a repair prompt without the budget just re-creates the
    # over-length draft the round existed to fix.
    assert "repair_contract_block = W.render_length_contract(" in source
    assert "R.build_repair_prompt(" in source
    assert "+ repair_contract_block" in source


def test_runtime_limits_are_recorded_in_debug_evidence():
    source = inspect.getsource(O.generate_candidate_v21)
    for field in ("runtime_length_mode", "runtime_word_target",
                  "runtime_word_hard", "runtime_scene_word_cap",
                  "length_contract_on_repair_calls"):
        assert field in source, field


def run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = []
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures.append((fn.__name__, exc))
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"RESULT: {len(tests) - len(failures)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
