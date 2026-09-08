#!/usr/bin/env python3
"""Certification-only provider resilience for Writer V2.1.

The private flagship lane has a different objective from unattended production:
wait briefly for the strongest currently-available writer instead of immediately
falling through to a materially smaller model, while preserving the exact same
Writer V2.1 schemas, semantic verification, factual gates, validator, and quality
floors.

This module makes ZERO provider calls on import. ``certification_provider_policy``
patches generate.py only inside a bounded context and restores every function on
exit, so the normal production provider policy is unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
import time
import urllib.error

import generate as G


STRICT_429_MAX_WAIT_S = 15.0
# Current Groq free-tier failures report an 8k TPM envelope. Leave a real
# completion reserve instead of treating "prompt fits by one token" as usable.
# This is certification-only routing: a request that cannot physically fit is
# skipped rather than retried/backed off before Gemini/other providers get it.
GROQ_TPM_LIMIT = 8000
GROQ_COMPLETION_RESERVE = 1024


def certification_is_weak_model(provider: str, model: str, original=None) -> bool:
    """Treat Groq 20B as a fallback, not a peer of 120B, for flagship writing."""
    p = (provider or "").lower()
    m = (model or "").lower()
    if p == "groq" and "gpt-oss-20b" in m:
        return True
    if original is not None:
        return bool(original(provider, model))
    return bool(G._is_weak_model(provider, model))


def groq_request_fits(prompt: str) -> tuple[bool, int]:
    """Pure conservative capacity check for the known Groq TPM envelope."""
    estimated = int(G.estimate_tokens(prompt))
    return estimated + GROQ_COMPLETION_RESERVE <= GROQ_TPM_LIMIT, estimated


def _http_detail(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", "replace")[:600]
    except Exception:  # noqa: BLE001
        return ""


def resilient_structured_call(prompt, schema, schema_name, debug_calls):
    """Use strict Groq only when the request can fit; otherwise skip to fallback.

    The live 2026-09-08 flagship path repeatedly sent ~10k-token structured
    requests to a Groq free-tier envelope that rejected them around 8k TPM. A
    structural size mismatch cannot heal with sleep/retry, and the old loose
    fallback could then try Groq yet again. We retain the short-throttle retry
    behavior for requests that actually fit and skip Groq entirely for requests
    that cannot, recording the reason in debug evidence.
    """
    groq_fits, estimated_prompt_tokens = groq_request_fits(prompt)
    if G.GROQ_KEY and not groq_fits:
        debug_calls.append({
            "provider": "groq",
            "model": None,
            "usage": None,
            "structured": True,
            "certification_resilience": True,
            "skipped": True,
            "skip_reason": "estimated request cannot fit Groq TPM envelope",
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "completion_reserve_tokens": GROQ_COMPLETION_RESERVE,
            "tpm_limit": GROQ_TPM_LIMIT,
        })
        print(
            f"  [writer-v2-cert] skipping Groq: estimated prompt {estimated_prompt_tokens} + "
            f"{GROQ_COMPLETION_RESERVE} completion reserve exceeds {GROQ_TPM_LIMIT} TPM envelope"
        )

    if G.GROQ_KEY and groq_fits:
        for model in list(G.MODEL_CHAIN):
            attempts = 2 if "gpt-oss-120b" in model.lower() else 1
            for attempt in range(attempts):
                try:
                    raw, usage = G._call_openai_compat_structured(
                        "https://api.groq.com/openai/v1/chat/completions",
                        G.GROQ_KEY,
                        model,
                        prompt,
                        schema,
                        schema_name=schema_name,
                    )
                    debug_calls.append({
                        "provider": "groq",
                        "model": model,
                        "usage": usage,
                        "structured": True,
                        "certification_resilience": True,
                    })
                    return raw, True
                except urllib.error.HTTPError as exc:
                    detail = _http_detail(exc)
                    wait_s = G._parse_retry_secs(detail) if exc.code == 429 else None
                    if (
                        attempt == 0
                        and attempts > 1
                        and wait_s is not None
                        and 0 < wait_s <= STRICT_429_MAX_WAIT_S
                    ):
                        pause = min(wait_s + 0.5, STRICT_429_MAX_WAIT_S)
                        print(
                            f"  [writer-v2-cert] strict {model} throttled for {wait_s:.2f}s — "
                            f"waiting {pause:.2f}s and retrying strongest schema writer once"
                        )
                        time.sleep(pause)
                        continue
                    print(
                        f"  [writer-v2-cert] strict {model} failed HTTP {exc.code}; "
                        "trying next strict model/provider"
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"  [writer-v2-cert] strict {model} failed "
                        f"({type(exc).__name__}: {str(exc)[:180]}); trying next strict model/provider"
                    )
                    break

    # call_groq() owns the cross-provider fallback chain. When the request is
    # structurally too large for Groq, temporarily blank only G.GROQ_KEY so that
    # fallback cannot waste another doomed Groq call. Always restore it.
    original_groq_key = G.GROQ_KEY
    if original_groq_key and not groq_fits:
        G.GROQ_KEY = ""
    try:
        try:
            raw = G.call_groq(prompt)
        except Exception as exc:  # noqa: BLE001
            debug_calls.append({
                "provider": None,
                "model": None,
                "usage": None,
                "structured": False,
                "certification_resilience": True,
                "error": str(exc),
            })
            return None, False
    finally:
        G.GROQ_KEY = original_groq_key

    provider, model = G._WORKING_MODEL if G._WORKING_MODEL else (None, None)
    debug_calls.append({
        "provider": provider,
        "model": model,
        "usage": None,
        "structured": False,
        "certification_resilience": True,
    })
    return raw, False


@contextmanager
def certification_provider_policy():
    """Install flagship-only provider policy and restore globals on exit."""
    original_structured = G._v2_structured_call
    original_weak = G._is_weak_model

    def _weak(provider, model):
        return certification_is_weak_model(provider, model, original=original_weak)

    G._v2_structured_call = resilient_structured_call
    G._is_weak_model = _weak
    try:
        yield
    finally:
        G._v2_structured_call = original_structured
        G._is_weak_model = original_weak
