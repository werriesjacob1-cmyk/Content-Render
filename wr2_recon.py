#!/usr/bin/env python3
"""ONE-OFF live reconnaissance for the V2 writer experiment (WRITER_V2 mission,
2026-09-03). Not part of the production pipeline -- run manually via
.github/workflows/writer_v2_recon.yml on this experiment branch only. Tests,
against the REAL GROQ_API_KEY:

  1. Real token usage (Groq's own reported usage.prompt_tokens) for the
     LEGACY prompt vs the V2 prompt, on the same real fact -- the
     authoritative number, not the chars/4 estimate.
  2. Structured JSON-schema output (response_format=json_schema, strict) on
     openai/gpt-oss-120b with the real V2 prompt + WRITER_V2_SCHEMA.
  3. Groq Compound / Compound Mini availability as a dedicated research stage
     (does it actually do web search? are citations/executed_tools present?).
  4. Orpheus voice (canopylabs/orpheus-v1-english) reconnaissance via Groq's
     /openai/v1/audio/speech endpoint.

Prints plain-text results only -- no files written, no manifest produced.
"""
import json
import os
import sys
import urllib.error
import urllib.request

import generate as G
import writer_v2 as W2

GROQ_KEY = os.environ.get("GROQ_API_KEY", "").strip()
CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
SPEECH_URL = "https://api.groq.com/openai/v1/audio/speech"


def _post(url, payload, timeout=90):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST",
        headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json",
                 "User-Agent": "content-render/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        return None, {"error": str(e)}


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    if not GROQ_KEY:
        print("NO GROQ_API_KEY -- aborting recon"); return 1

    bank = G.load_bank()
    fact = bank[10]
    print(f"Using fact: {fact['id']} ({fact.get('domain')})")

    # ------------------------------------------------------------------
    # 1. REAL token usage: legacy prompt vs V2 prompt, same fact
    # ------------------------------------------------------------------
    section("1. REAL prompt_tokens usage -- legacy vs V2 (same fact, same model)")
    dossier = G.research_dossier(fact)
    print(f"research_dossier() returned {len(dossier)} facts (grounded={bool(dossier)})")

    legacy_prompt = G.build_prompt("CURIOSITY_ITCH", G.VIEWER_JOBS[0][1], "none", fact=fact,
                                   avoid_openers=None, cta_style="SAVE_WORTHY",
                                   dossier=dossier, hook_frame=G.HOOK_FRAMES[0])
    treatment = W2.select_treatment(fact["id"])
    packet = W2.build_story_packet(fact, dossier_facts=dossier, grounded=bool(dossier))
    v2_prompt = W2.build_writer_prompt_v2(treatment, packet, avoid_topics="none",
                                          visual_evidence=fact.get("queries"))
    print(f"legacy prompt: {len(legacy_prompt)} chars, est. {G.estimate_tokens(legacy_prompt)} tokens")
    print(f"v2 prompt ({treatment}): {len(v2_prompt)} chars, est. {W2.estimate_tokens(v2_prompt)} tokens")

    model = G.MODEL_CHAIN[0]
    for label, p in (("legacy", legacy_prompt), ("v2", v2_prompt)):
        status, data = _post(CHAT_URL, {"model": model, "messages": [{"role": "user", "content": p}],
                                        "temperature": 0.7, "max_tokens": 1,
                                        "response_format": {"type": "json_object"}})
        usage = data.get("usage") if isinstance(data, dict) else None
        print(f"  [{label}] HTTP {status} usage={usage} error={data.get('error') if status != 200 else ''}")

    # ------------------------------------------------------------------
    # 2. Structured JSON-schema output on the real V2 prompt
    # ------------------------------------------------------------------
    section("2. Structured output (response_format=json_schema, strict) -- real V2 prompt")
    status, data = _post(CHAT_URL, {
        "model": model,
        "messages": [{"role": "user", "content": v2_prompt}],
        "temperature": 0.7, "max_tokens": 2000,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "writer_v2_output", "schema": W2.WRITER_V2_SCHEMA, "strict": True}},
    })
    print(f"HTTP {status}")
    if status == 200:
        msg = data["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning") or ""
        print(f"usage: {data.get('usage')}")
        print(f"raw content (first 2000 chars):\n{content[:2000]}")
        try:
            parsed = json.loads(content)
            ok = all(k in parsed for k in ("title", "hook", "beats", "payoff"))
            print(f"parsed OK, has all required keys: {ok}, beat count: {len(parsed.get('beats', []))}")
        except Exception as e:  # noqa: BLE001
            print(f"FAILED to parse structured output as JSON: {e}")
    else:
        print(f"error body: {json.dumps(data)[:1000]}")

    # ------------------------------------------------------------------
    # 3. Groq Compound / Compound Mini as a research stage
    # ------------------------------------------------------------------
    section("3. Groq Compound / Compound Mini -- dedicated research stage viability")
    research_prompt = (
        f'Research this science fact for a short video script: "{fact["fact"]}"\n'
        f"Give me: the central claim, the mechanism (how/why it works), 3 supporting facts, "
        f"a surprising implication, and any caveat/uncertainty. Cite real sources if you can. "
        f'Return ONLY JSON: {{"central_claim":"...","mechanism":"...","supporting_facts":["...","...","..."],'
        f'"surprising_implication":"...","caveat":"...","sources":["..."]}}'
    )
    for cmodel in ("groq/compound", "groq/compound-mini"):
        status, data = _post(CHAT_URL, {"model": cmodel,
                                        "messages": [{"role": "user", "content": research_prompt}],
                                        "temperature": 0.3, "max_tokens": 1500})
        print(f"\n  [{cmodel}] HTTP {status}")
        if status == 200:
            msg = data["choices"][0]["message"]
            print(f"  usage: {data.get('usage')}")
            print(f"  has 'executed_tools' field: {'executed_tools' in msg}")
            if "executed_tools" in msg:
                print(f"  executed_tools: {json.dumps(msg['executed_tools'])[:800]}")
            content = msg.get("content") or ""
            print(f"  content (first 1200 chars):\n{content[:1200]}")
        else:
            print(f"  error body: {json.dumps(data)[:500]}")

    # ------------------------------------------------------------------
    # 4. Orpheus voice reconnaissance (do NOT wire into production)
    # ------------------------------------------------------------------
    section("4. canopylabs/orpheus-v1-english -- TTS endpoint reconnaissance only")
    body = json.dumps({"model": "canopylabs/orpheus-v1-english",
                       "input": "This is a short reconnaissance test of the Orpheus voice.",
                       "voice": "troy", "response_format": "wav"}).encode()
    req = urllib.request.Request(SPEECH_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json",
                 "User-Agent": "content-render/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            audio = r.read()
            print(f"HTTP {r.status}, received {len(audio)} bytes of audio "
                  f"(content-type: {r.headers.get('Content-Type')})")
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode()
        except Exception:
            err_body = "<unreadable>"
        print(f"HTTP {e.code}: {err_body[:500]}")
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
