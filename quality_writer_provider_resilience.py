#!/usr/bin/env python3
"""Certification-only provider resilience for Writer V2.1.

The private flagship lane has a different objective from unattended production:
wait briefly for the strongest currently-available writer instead of immediately
falling through to a materially smaller model, while preserving the exact same
Writer V2.1 schemas, semantic verification, factual gates, validator, and quality
floors.

This module makes ZERO provider calls on import.  ``certification_provider_policy``
patches generate.py only inside a bounded context and restores every function on
exit, so the normal production provider policy is unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
import time
import urllib.error

import generate as G
import writer_v2 as W


STRICT_429_MAX_WAIT_S = 15.0


def certification_is_weak_model(provider: str, model: str, original=None) -> bool:
    """Treat Groq 20B as a fallback, not a peer of 120B, for flagship writing."""
    p = (provider or "").lower()
    m = (model or "").lower()
    if p == "groq" and "gpt-oss-20b" in m:
        return True
    if original is not None:
        return bool(original(provider, model))
    return bool(G._is_weak_model(provider, model))


def _http_detail(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", "replace")[:600]
    except Exception:  # noqa: BLE001
        return ""


def resilient_structured_call(prompt, schema, schema_name, debug_calls):
    """Try both Groq OSS models in strict schema mode before loose fallback.

    The live 2026-09-08 flagship run hit a ~6s TPM throttle on 120B during the
    critic.  The old code immediately abandoned strict mode and accepted 20B as a
    primary plain-json writer; a later 20B call then failed provider-side JSON
    validation.  Here a short, explicit 120B retry is cheaper and higher quality.
    If 120B is genuinely unavailable, 20B gets one strict-schema chance.  Only
    then do we invoke the normal cross-provider fallback chain.
    """
    # Capability gate FIRST. This certification path calls
    # G._call_openai_compat_structured directly, so it does not inherit the gate
    # in G._v2_structured_call -- and this is the path that produced flagship
    # run #5's entire 413 storm: every strict attempt returned "Requested 10126,
    # Limit 8000" and was then retried with throttle backoff, burning ~60s per
    # run on a request Groq can never serve. A 413 is structural; no amount of
    # waiting fixes it.
    est_tokens = W.estimate_tokens(prompt)
    groq_fits = G._provider_can_serve("groq", est_tokens)
    if G.GROQ_KEY and not groq_fits:
        print(
            f"  [writer-v2-cert] skipping strict groq schema writers: request is ~{est_tokens} est. "
            f"prompt tokens + {G.STRUCTURED_MAX_OUTPUT_TOKENS} reserved output vs groq's "
            f"{G._provider_token_ceiling('groq')}-token ceiling -- STRUCTURAL (HTTP 413), not a "
            f"throttle, so retrying with backoff cannot help; going straight to the fallback chain"
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
