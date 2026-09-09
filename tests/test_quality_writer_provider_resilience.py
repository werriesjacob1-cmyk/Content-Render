#!/usr/bin/env python3
"""Zero-network regressions for flagship Writer provider resilience."""
from __future__ import annotations

import io
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_writer_provider_resilience as R


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _http_error(code: int, body: str):
    return urllib.error.HTTPError(
        "https://api.groq.com/openai/v1/chat/completions",
        code,
        "test",
        {},
        io.BytesIO(body.encode("utf-8")),
    )


def test_20b_is_flagship_fallback_not_primary_peer():
    original = lambda p, m: p == "cerebras"
    check(R.certification_is_weak_model("groq", "openai/gpt-oss-20b", original),
          "Groq 20B is a weak/fallback writer in flagship certification")
    check(not R.certification_is_weak_model("groq", "openai/gpt-oss-120b", original),
          "Groq 120B remains a primary flagship writer")
    check(R.certification_is_weak_model("cerebras", "gemma-4-31b", original),
          "existing weak-provider classification is preserved")


def test_groq_capacity_check_reserves_full_structured_completion_budget():
    check(R.GROQ_COMPLETION_RESERVE == 3000,
          "Groq capacity reserve matches generate.py structured max_tokens=3000")

    # estimate_tokens is len//4. At 5,000 estimated prompt tokens, the request
    # plus the 3,000-token structured completion ceiling exactly fills 8k and
    # remains eligible. One additional estimated prompt token must fail closed.
    exact_prompt = "x" * (5000 * 4)
    fits, est = R.groq_request_fits(exact_prompt)
    check(fits and est == 5000, "exact 8k request boundary remains Groq-eligible")

    over_prompt = "x" * (5001 * 4)
    fits, est = R.groq_request_fits(over_prompt)
    check(not fits and est == 5001,
          "one token beyond prompt+completion 8k boundary skips Groq")


def test_oversize_request_skips_strict_and_loose_groq_but_restores_key():
    old_key = R.G.GROQ_KEY
    old_call = R.G._call_openai_compat_structured
    old_fallback = R.G.call_groq
    old_working = R.G._WORKING_MODEL
    strict_calls = []
    fallback_key_seen = []
    R.G.GROQ_KEY = "test"

    def forbidden_structured(*args, **kwargs):
        strict_calls.append(True)
        raise AssertionError("oversize request must not reach strict Groq")

    def fake_fallback(prompt):
        fallback_key_seen.append(R.G.GROQ_KEY)
        R.G._WORKING_MODEL = ("gemini", "test-gemini")
        return '{"ok":true}'

    R.G._call_openai_compat_structured = forbidden_structured
    R.G.call_groq = fake_fallback
    try:
        debug = []
        huge = "x" * (R.GROQ_TPM_LIMIT * 4)
        raw, structured = R.resilient_structured_call(huge, {"type": "object"}, "test", debug)
        restored_inside = R.G.GROQ_KEY
    finally:
        R.G.GROQ_KEY = old_key
        R.G._call_openai_compat_structured = old_call
        R.G.call_groq = old_fallback
        R.G._WORKING_MODEL = old_working

    check(raw == '{"ok":true}' and structured is False,
          "oversize request falls through to cross-provider chain")
    check(not strict_calls, "oversize request makes zero strict Groq calls")
    check(fallback_key_seen == [""], "loose fallback sees Groq disabled for the oversize request")
    check(restored_inside == "test", "Groq key is restored immediately after fallback")
    skips = [d for d in debug if d.get("skipped")]
    check(len(skips) == 1 and skips[0].get("provider") == "groq",
          "debug evidence records one explicit Groq capacity skip")


def test_short_120b_throttle_waits_and_retries_same_strict_model():
    old_key = R.G.GROQ_KEY
    old_models = list(R.G.MODEL_CHAIN)
    old_call = R.G._call_openai_compat_structured
    old_fallback = R.G.call_groq
    old_sleep = R.time.sleep
    calls = []
    sleeps = []
    R.G.GROQ_KEY = "test"
    R.G.MODEL_CHAIN = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]

    def fake_structured(url, key, model, prompt, schema, schema_name="x"):
        calls.append(model)
        if len(calls) == 1:
            raise _http_error(429, "Rate limit. Please try again in 0.20s.")
        return '{"ok":true}', {"total_tokens": 10}

    R.G._call_openai_compat_structured = fake_structured
    R.G.call_groq = lambda prompt: (_ for _ in ()).throw(AssertionError("loose fallback should not run"))
    R.time.sleep = lambda s: sleeps.append(s)
    try:
        debug = []
        raw, structured = R.resilient_structured_call("p", {"type": "object"}, "test", debug)
    finally:
        R.G.GROQ_KEY = old_key
        R.G.MODEL_CHAIN = old_models
        R.G._call_openai_compat_structured = old_call
        R.G.call_groq = old_fallback
        R.time.sleep = old_sleep

    check(raw == '{"ok":true}' and structured is True,
          "short 120B throttle recovers in strict-schema mode")
    check(calls == ["openai/gpt-oss-120b", "openai/gpt-oss-120b"],
          "resilience retries 120B itself instead of instantly degrading to 20B")
    check(len(sleeps) == 1 and sleeps[0] > 0,
          "server retry hint causes exactly one bounded sleep")
    check(debug and debug[0]["model"] == "openai/gpt-oss-120b",
          "debug records the actual successful strict writer")


def test_hard_120b_failure_tries_20b_strict_before_loose_chain():
    old_key = R.G.GROQ_KEY
    old_models = list(R.G.MODEL_CHAIN)
    old_call = R.G._call_openai_compat_structured
    old_fallback = R.G.call_groq
    calls = []
    R.G.GROQ_KEY = "test"
    R.G.MODEL_CHAIN = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]

    def fake_structured(url, key, model, prompt, schema, schema_name="x"):
        calls.append(model)
        if "120b" in model:
            raise _http_error(400, "unsupported on this request")
        return '{"ok":true}', {"total_tokens": 8}

    R.G._call_openai_compat_structured = fake_structured
    R.G.call_groq = lambda prompt: (_ for _ in ()).throw(AssertionError("loose fallback should not run"))
    try:
        debug = []
        raw, structured = R.resilient_structured_call("p", {"type": "object"}, "test", debug)
    finally:
        R.G.GROQ_KEY = old_key
        R.G.MODEL_CHAIN = old_models
        R.G._call_openai_compat_structured = old_call
        R.G.call_groq = old_fallback

    check(raw == '{"ok":true}' and structured is True,
          "20B strict-schema output can rescue a hard 120B failure")
    check(calls == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
          "both Groq models are tried in strict mode before loose fallback")


def test_context_restores_generate_globals():
    orig_structured = R.G._v2_structured_call
    orig_weak = R.G._is_weak_model
    with R.certification_provider_policy():
        check(R.G._v2_structured_call is R.resilient_structured_call,
              "certification context installs resilient structured caller")
        check(R.G._is_weak_model("groq", "openai/gpt-oss-20b") is True,
              "certification context demotes 20B inside the flagship run")
    check(R.G._v2_structured_call is orig_structured and R.G._is_weak_model is orig_weak,
          "certification context restores normal production provider policy")


if __name__ == "__main__":
    test_20b_is_flagship_fallback_not_primary_peer()
    test_groq_capacity_check_reserves_full_structured_completion_budget()
    test_oversize_request_skips_strict_and_loose_groq_but_restores_key()
    test_short_120b_throttle_waits_and_retries_same_strict_model()
    test_hard_120b_failure_tries_20b_strict_before_loose_chain()
    test_context_restores_generate_globals()
    print("quality_writer_provider_resilience tests: PASS")
