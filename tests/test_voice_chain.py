#!/usr/bin/env python3
"""Zero-network regressions for the free-voice chain: Kokoro -> edge-tts -> Piper.

No model, no network, no ffmpeg: the three synthesizers are stubbed so only the
ROUTING decisions are tested (which engine runs first, what falls through, and
that Kokoro's missing word timings are handed to whisper_align).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")
os.environ.pop("ELEVENLABS_API_KEY", None)

import main as M


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _route(engine, kokoro_ok, edge_ok, piper_ok):
    calls = []
    saved = (M._kokoro_tts, M._piper_tts, M._edge_tts_with_timings, M.run,
             M.os.path.getsize, M.WORD_TIMINGS[:], os.environ.get("VOICE_ENGINE"))
    M.WORD_TIMINGS[:] = [("stale", 0.0, 0.1)]

    def kokoro(text, out):
        calls.append("kokoro"); return kokoro_ok

    def piper(text, out):
        calls.append("piper"); return piper_ok

    def edge(text, voice, rate, out):
        calls.append("edge")
        if not edge_ok:
            raise RuntimeError("edge down")
        return [("a", 0.0, 0.1)]

    def cli(cmd, *a, **k):          # the edge-tts CLI fallback inside _try_edge
        if cmd and cmd[0] == "edge-tts":
            calls.append("edge-cli"); raise RuntimeError("edge cli down")
        return ""

    M._kokoro_tts, M._piper_tts, M._edge_tts_with_timings, M.run = kokoro, piper, edge, cli
    M.os.path.getsize = lambda p: 5000
    if engine is None:
        os.environ.pop("VOICE_ENGINE", None)
    else:
        os.environ["VOICE_ENGINE"] = engine
    try:
        ok = M.tts_full("One. Two.", "/tmp/x.mp3", "en-GB-RyanNeural", "-5%")
        return ok, calls, list(M.WORD_TIMINGS)
    finally:
        (M._kokoro_tts, M._piper_tts, M._edge_tts_with_timings, M.run, M.os.path.getsize) = saved[:5]
        M.WORD_TIMINGS[:] = saved[5]
        if saved[6] is None:
            os.environ.pop("VOICE_ENGINE", None)
        else:
            os.environ["VOICE_ENGINE"] = saved[6]


def test_order_function():
    check(M._voice_order(None) == ["kokoro", "edge", "piper"], "default order is Kokoro, edge-tts, Piper")
    check(M._voice_order("auto") == ["kokoro", "edge", "piper"], "'auto' is the default order")
    check(M._voice_order("edge") == ["edge", "piper"], "'edge' keeps the old edge-first order (no Kokoro)")
    check(M._voice_order("piper") == ["piper", "edge"], "'piper' keeps Piper first (offline proof)")
    check(M._voice_order("nonsense") == ["kokoro", "edge", "piper"], "an unknown value means auto")


def test_routing():
    ok, calls, wt = _route(None, True, True, True)
    check(ok and calls == ["kokoro"], f"Kokoro succeeds -> nothing else is tried ({calls})")
    check(wt == [], "Kokoro success clears word timings so whisper_align supplies them")
    ok, calls, wt = _route(None, False, True, True)
    check(ok and calls == ["kokoro", "edge"], f"Kokoro unavailable -> edge-tts next ({calls})")
    ok, calls, _ = _route(None, False, False, True)
    check(ok and calls[0] == "kokoro" and calls[-1] == "piper", f"both down -> Piper last ({calls})")
    ok, calls, _ = _route(None, False, False, False)
    check(not ok, "every engine down -> tts_full reports failure (caller makes the silent track)")
    ok, calls, _ = _route("edge", True, True, True)
    check(ok and "kokoro" not in calls and calls[0] == "edge", f"VOICE_ENGINE=edge never touches Kokoro ({calls})")
    ok, calls, _ = _route("piper", True, True, True)
    check(ok and calls == ["piper"], f"VOICE_ENGINE=piper is Piper-only when it works ({calls})")


def test_sentence_split_and_missing_model():
    check(M._split_sentences("One thing. Is it two? Yes!  Fine") == ["One thing.", "Is it two?", "Yes!", "Fine"],
          "narration splits into sentences so a pause can be inserted between them")
    check(M._split_sentences("") == [] and M._split_sentences(" . ") == [], "empty/punctuation-only input is safe")
    old = (M.KOKORO_MODEL, M.KOKORO_VOICES)
    M.KOKORO_MODEL = M.KOKORO_VOICES = "/nonexistent/none"
    try:
        check(M._kokoro_tts("Hello there.", "/tmp/never.mp3") is False,
              "missing model files -> False (falls through), never an exception")
    finally:
        M.KOKORO_MODEL, M.KOKORO_VOICES = old


def test_delivery_decision_not_forked():
    """The audio rate/bitrate stay ONE decision (delivery_contract). Adding a 24 kHz
    local voice must not introduce a second rate/bitrate anywhere in main.py."""
    import re
    import delivery_contract as D
    src = open(M.__file__).read()
    check("from delivery_contract import delivery_audio_encode_args" in src,
          "main.py still takes the delivery encode from delivery_contract")
    check(not re.search(r"['\"]-ar['\"]\s*,\s*['\"]\d", src) and "192000" not in src and "48000" not in src,
          "main.py hard-codes no second sample rate")
    args = D.delivery_audio_encode_args()
    check("48000" in args and any(a.endswith("k") for a in args), f"the shared contract still pins rate+bitrate ({args})")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
