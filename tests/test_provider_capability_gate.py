#!/usr/bin/env python3
"""Regressions for the two corrections to capability-aware provider routing.

Flagship run #5 burned ~60s of throttle backoff re-attempting a request Groq
can never serve: every strict schema call returned HTTP 413 "Requested 10126,
Limit 8000". A 413 is structural -- unlike a 429, no amount of waiting fixes it.

Two things had to be true for the gate to actually stop that, and neither was
true in the first cut:

1. It must count the RESERVED OUTPUT budget. Groq bills max_tokens against the
   same per-minute envelope. The live writer prompt is only ~2.3k estimated
   tokens, so a prompt-only comparison never fires -- the gate would have been
   inert against the exact failure it was written for.
2. It must be consulted on the path that actually failed. The certification
   writer in quality_writer_provider_resilience.py calls
   generate._call_openai_compat_structured DIRECTLY, so it does not inherit the
   gate inside generate._v2_structured_call. That cert path is where every one
   of run #5's 413s came from.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import generate as G
import quality_writer_provider_resilience as Q

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_reserved_output_budget_counts_toward_the_ceiling():
    ceiling = G._provider_token_ceiling("groq")
    reserve = G.STRUCTURED_MAX_OUTPUT_TOKENS
    check(ceiling == 8000, f"groq ceiling on record is 8000 (got {ceiling})")
    check(reserve > 0, "a non-zero output budget is reserved on structured calls")

    # Exactly at the combined ceiling is still eligible.
    check(G._provider_can_serve("groq", ceiling - reserve),
          "prompt + reservation exactly at the ceiling remains eligible")
    check(not G._provider_can_serve("groq", ceiling - reserve + 1),
          "one token past the combined ceiling is refused")

    # The regression that made the first cut inert: a prompt comfortably under
    # 8000 on its own, but over once the reservation is counted.
    prompt_only_ok = ceiling - 1000          # 7000 -- passes a prompt-only test
    check(prompt_only_ok < ceiling, "fixture prompt is under the ceiling on its own")
    check(not G._provider_can_serve("groq", prompt_only_ok),
          "a prompt that only fits when the reserved output is ignored is REFUSED")


def test_the_real_run5_request_is_refused_and_a_real_small_one_is_not():
    # ~7127 prompt tokens + 3000 reserved == the 10126 Groq itself reported.
    check(not G._provider_can_serve("groq", 7127),
          "run #5's actual request shape is refused (10126 > 8000)")
    # The live initial writer prompt measures ~2.3k; Groq's schema-enforced
    # structured output is genuinely valuable there and must still be used.
    check(G._provider_can_serve("groq", 2347),
          "the real initial writer prompt still routes to groq structured output")


def test_gate_still_fails_open_on_anything_unprovable():
    for bad in (None, 0, -1, "abc", True, [], {}):
        check(G._provider_can_serve("groq", bad) is True,
              f"unusable estimate {bad!r} fails OPEN rather than blocking the call")
    check(G._provider_can_serve("a-provider-with-no-ceiling", 10 ** 9) is True,
          "a provider with no ceiling on record is never pre-emptively skipped")
    check(G._provider_can_serve("groq", 100, reserved_output_tokens=0) is True,
          "a caller that reserves no output is judged on its prompt alone")


def test_certification_path_consults_the_gate():
    """The path that produced every observed 413 must be gated, not just the
    general one -- otherwise the fix is in the wrong function."""
    src = open(os.path.join(ROOT, "quality_writer_provider_resilience.py"),
               encoding="utf-8").read()
    check("_provider_can_serve" in src,
          "certification strict-writer path consults the capability gate")
    gate_pos = src.index("_provider_can_serve")
    loop_pos = src.index("for model in list(G.MODEL_CHAIN)")
    check(gate_pos < loop_pos,
          "the gate is evaluated BEFORE the strict-model retry loop, not inside it")
    check("STRUCTURAL" in src and "413" in src,
          "the skip log explains this is structural, not a throttle worth retrying")
    check("estimate_tokens" in src, "the cert path measures the request it is about to send")


if __name__ == "__main__":
    test_reserved_output_budget_counts_toward_the_ceiling()
    test_the_real_run5_request_is_refused_and_a_real_small_one_is_not()
    test_gate_still_fails_open_on_anything_unprovable()
    test_certification_path_consults_the_gate()
    print("provider capability gate tests: PASS")
