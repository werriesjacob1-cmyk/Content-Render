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

def groq_request_fits(prompt: str) -> tuple[bool, int]:
    """Delegate to the single shared capability gate.

    This module previously carried its own GROQ_TPM_LIMIT/COMPLETION_RESERVE
    copy -- a third implementation of one decision, which is exactly how the
    reserve silently drifts out of step with the max_tokens actually sent.
    generate owns the ceiling table and the completion reserve now; both remain
    env-overridable there.
    """
    est = int(G.estimate_tokens(prompt))
    return G._provider_can_serve("groq", est), est


def install_capability_guard():
    original = G.call_groq

    def guarded(prompt):
        fits, est = groq_request_fits(prompt)
        if G.GROQ_KEY and not fits:
            print(
                f"  [provider-router] skipping Groq for this request: estimated {est} + "
                f"{G.STRUCTURED_MAX_OUTPUT_TOKENS} reserve > "
                f"{G._provider_token_ceiling('groq')} request ceiling; continuing provider chain"
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
