#!/usr/bin/env python3
"""Zero-network regressions for Voice Lab 2.0."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import voice_bakeoff as V


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_registry_and_orpheus_chunking():
    check(V.CARTESIA_MODEL == "sonic-3.6", "Cartesia lane pins current stable Sonic 3.6")
    check(V.CARTESIA_VERSION == "2026-03-01", "Cartesia request uses current documented API version")
    check(V.ELEVEN_MODEL == "eleven_v3", "Eleven lane uses current expressive v3 model")
    text = "One sentence with a scientific idea. " * 15
    chunks = V.split_for_orpheus(text, direction="calmly")
    check(chunks and max(map(len, chunks)) <= 200, "Orpheus input remains <=200 chars including direction")
    rebuilt = " ".join(x.removeprefix("[calmly] ") for x in chunks)
    check("One sentence" in rebuilt and "scientific idea" in rebuilt, "Orpheus chunker preserves narration content")


def test_cartesia_contract_without_network():
    captured = {}
    old = V._http_audio
    def fake(url, body, headers, timeout=90.0):
        captured.update(url=url, body=body, headers=headers)
        return b"RIFF" + b"0" * 4 + b"WAVE" + b"0" * 300
    V._http_audio = fake
    try:
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "cartesia.wav")
            meta = V.generate_cartesia("A neutron star is dense.", "voice-123", dest, "key", "en-US")
            check(os.path.getsize(dest) > 256, "Cartesia WAV response is persisted")
    finally:
        V._http_audio = old
    check(captured["url"] == "https://api.cartesia.ai/tts/bytes", "Cartesia uses bytes endpoint")
    check(captured["body"]["model_id"] == "sonic-3.6", "Cartesia request uses Sonic 3.6")
    check(captured["body"]["voice"] == "voice-123", "Cartesia uses explicit voice ID")
    check(captured["body"]["output_format"] == {"container":"wav","encoding":"pcm_s16le","sample_rate":44100}, "Cartesia requests lossless WAV")
    check(captured["headers"]["Cartesia-Version"] == "2026-03-01", "Cartesia API version header present")
    check(meta["provider"] == "cartesia", "Cartesia provenance recorded")


def test_eleven_contract_without_network():
    captured = {}
    old = V._http_audio
    def fake(url, body, headers, timeout=90.0):
        captured.update(url=url, body=body, headers=headers)
        return b"ID3" + b"0" * 300
    V._http_audio = fake
    try:
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "eleven.mp3")
            meta = V.generate_eleven("A clean narration test.", "voice id/with spaces", dest, "key")
            check(os.path.getsize(dest) > 256, "Eleven audio response is persisted")
    finally:
        V._http_audio = old
    check("voice%20id%2Fwith%20spaces" in captured["url"], "Eleven voice ID is URL-escaped safely")
    check(captured["body"]["model_id"] == "eleven_v3", "Eleven request uses v3")
    check(captured["headers"]["xi-api-key"] == "key", "Eleven API key header is correct")
    check(meta["provider"] == "eleven", "Eleven provenance recorded")


def test_plan_and_blind_review_contract():
    class A:
        edge_voice="en-GB-RyanNeural"; orpheus_voices="troy"; cartesia_voice_id=""; eleven_voice_id=""
    rows = V.provider_plan(["edge","orpheus","cartesia","eleven"], A())
    check(len(rows) == 4, "all four voice families represented in plan")
    blockers = {x["provider"]:x for x in rows}
    check(blockers["cartesia"]["voice"] == "REQUIRED", "missing Cartesia voice is explicit blocker")
    check(blockers["eleven"]["voice"] == "REQUIRED", "missing Eleven voice is explicit blocker")
    stub = V.review_stub("A")
    check(stub["would_use_in_final"] is None and stub["sounds_ai_0_10"] is None, "blind review starts unbiased")
    try:
        V.parse_providers("edge,madeup")
        raise AssertionError("unknown provider should fail")
    except ValueError:
        check(True, "unknown provider rejected")


if __name__ == "__main__":
    test_registry_and_orpheus_chunking()
    test_cartesia_contract_without_network()
    test_eleven_contract_without_network()
    test_plan_and_blind_review_contract()
    print("voice_lab tests: PASS")
