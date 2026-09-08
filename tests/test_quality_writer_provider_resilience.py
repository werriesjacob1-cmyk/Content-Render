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
    test_short_120b_throttle_waits_and_retries_same_strict_model()
    test_hard_120b_failure_tries_20b_strict_before_loose_chain()
    test_context_restores_generate_globals()
    print("quality_writer_provider_resilience tests: PASS")
