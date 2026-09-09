#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

os.environ.setdefault("GROQ_API_KEY", "x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_production_generate as P


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label)


def test_capacity_boundary_uses_completion_reserve():
    old_est = P.G.estimate_tokens
    P.G.estimate_tokens = lambda prompt: 5000 if prompt == "fit" else 5001
    try:
        check(P.groq_request_fits("fit")[0] is True, "5000 + 3000 fits 8k envelope exactly")
        check(P.groq_request_fits("over")[0] is False, "5001 + 3000 is structurally impossible")
    finally:
        P.G.estimate_tokens = old_est


def test_guard_disables_groq_only_for_oversize_call_and_restores_key():
    old_key = P.G.GROQ_KEY
    old_call = P.G.call_groq
    old_est = P.G.estimate_tokens
    seen = []
    P.G.GROQ_KEY = "secret"
    P.G.estimate_tokens = lambda prompt: 7000 if prompt == "large" else 100

    def fake(prompt):
        seen.append((prompt, P.G.GROQ_KEY))
        return "{}"

    P.G.call_groq = fake
    original = P.install_capability_guard()
    try:
        P.G.call_groq("large")
        check(P.G.GROQ_KEY == "secret", "Groq key restored immediately after oversized routing")
        P.G.call_groq("small")
    finally:
        P.G.call_groq = old_call
        P.G.GROQ_KEY = old_key
        P.G.estimate_tokens = old_est
    check(seen == [("large", ""), ("small", "secret")], "only structurally impossible request skips Groq")
    check(original is fake, "guard preserves underlying provider chain exactly")


if __name__ == "__main__":
    test_capacity_boundary_uses_completion_reserve()
    test_guard_disables_groq_only_for_oversize_call_and_restores_key()
    print("quality_production_generate tests: PASS")
