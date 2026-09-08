#!/usr/bin/env python3
"""Zero-provider regressions for Writer V2.1's runtime narration contract."""
import inspect
import os
import sys

os.environ.setdefault("GROQ_API_KEY", "x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate as G
import writer_v2 as W
import writer_v21_orchestrator as O


def test_contract_reflects_active_runtime_limits():
    treatment = "INSIDE_THE_SYSTEM"
    contract = O._runtime_narration_contract(treatment)
    beat_count = len((W.TREATMENTS.get(treatment) or {}).get("beats") or [])
    assert f"exactly {beat_count} treatment beats" in contract
    assert f"{beat_count + 2} spoken scenes total" in contract
    assert f"target {G.WORD_LO}-{G.WORD_HI}" in contract
    assert f"hard range {G.WORD_HARD_LO}-{G.WORD_HARD_HI}" in contract
    assert f"<= {G.SCENE_WORD_CAP} words" in contract


def test_contract_updates_when_runtime_window_changes():
    saved = (G.WORD_LO, G.WORD_HI, G.WORD_HARD_LO, G.WORD_HARD_HI, G.SCENE_WORD_CAP)
    try:
        G.WORD_LO, G.WORD_HI = 91, 109
        G.WORD_HARD_LO, G.WORD_HARD_HI = 82, 117
        G.SCENE_WORD_CAP = 23
        contract = O._runtime_narration_contract("CASE_FILE")
        assert "target 91-109" in contract
        assert "hard range 82-117" in contract
        assert "<= 23 words" in contract
    finally:
        G.WORD_LO, G.WORD_HI, G.WORD_HARD_LO, G.WORD_HARD_HI, G.SCENE_WORD_CAP = saved


def test_contract_resolves_live_hook_and_craft_conflicts():
    contract = O._runtime_narration_contract("INSIDE_THE_SYSTEM")
    assert "THIS OVERRIDES ANY CONFLICTING GENERIC WORDING ABOVE" in contract
    assert "NOT a question" in contract
    assert "must not end with '?'" in contract
    assert "scene 2 or later" in contract
    assert "Never spend two consecutive beats re-explaining the same mechanism" in contract
    assert "immediately translate what it means in plain language" in contract
    assert "Never dump jargon" in contract
    assert "one concrete implication/reframe" in contract
    assert "turning a declaration into a question with punctuation alone" in contract


def test_contract_is_load_bearing_on_initial_and_repair_calls():
    source = inspect.getsource(O.generate_candidate_v21)
    assert 'prompt = W.build_writer_prompt_v2(' in source
    assert ') + "\\n\\n" + runtime_contract' in source
    assert 'repair_prompt = R.build_repair_prompt(' in source
    # The same exact runtime contract is appended to repair calls, so a
    # provenance repair cannot silently balloon back beyond the hidden limit.
    assert source.count('+ "\\n\\n" + runtime_contract') >= 2


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
