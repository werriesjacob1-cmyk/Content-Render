#!/usr/bin/env python3
"""Capability-aware wrapper around legacy unattended ``generate.py``.

No generation policy is weakened. The wrapper only prevents a known impossible
Groq call when estimated prompt + conservative completion reserve exceeds the
known 8k TPM envelope. Other providers in generate.call_groq remain available,
and short Groq calls still run normally.
"""
from __future__ import annotations

import os
import sys

import generate as G

GROQ_TPM_LIMIT = int(os.getenv("GROQ_TPM_LIMIT", "8000"))
COMPLETION_RESERVE = int(os.getenv("GROQ_COMPLETION_RESERVE", "3000"))


def groq_request_fits(prompt: str) -> tuple[bool, int]:
    est = int(G.estimate_tokens(prompt))
    return est + COMPLETION_RESERVE <= GROQ_TPM_LIMIT, est


def install_capability_guard():
    original = G.call_groq

    def guarded(prompt):
        fits, est = groq_request_fits(prompt)
        if G.GROQ_KEY and not fits:
            print(
                f"  [provider-router] skipping Groq for this request: estimated {est} + "
                f"{COMPLETION_RESERVE} reserve > {GROQ_TPM_LIMIT} TPM; continuing provider chain"
            )
            old = G.GROQ_KEY
            G.GROQ_KEY = ""
            try:
                return original(prompt)
            finally:
                G.GROQ_KEY = old
        return original(prompt)

    G.call_groq = guarded
    return original


def main() -> int:
    original = install_capability_guard()
    try:
        if G.GEN_MODE == "dequeue":
            return int(G.dequeue_to(G.OUT_MANIFEST))
        if G.GEN_MODE == "record":
            return int(G.record_perf(G._ARGV))
        G.main()
        return 0
    finally:
        G.call_groq = original


if __name__ == "__main__":
    raise SystemExit(main())
