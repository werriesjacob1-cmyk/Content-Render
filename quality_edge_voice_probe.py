#!/usr/bin/env python3
"""Exercise the default free narration route used by private certification.

The private flagship does not set VOICE_ENGINE, so ``main.tts_full`` prefers the
profile's Edge neural voice before falling back to local Piper.  The 1080p Piper
proof covers the offline fallback; this small probe verifies that the *default*
Edge route is currently reachable and that production obtains a usable timing
map for captions/scene cuts.

This is not an LLM/provider call and has no publishing side effects.  Edge TTS
is an external free speech service, so network access is expected in this probe.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import main as legacy
import quality_evidence as QE


SCHEMA = "content-render-edge-voice-probe-v1"
TEXT = (
    "A real narration check should sound natural on the first listen. "
    "The voice should stay clear while the timing system follows every spoken word. "
    "This short sample proves the default free voice route before a real science video needs it."
)


def _duration(path: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        text=True, capture_output=True, check=True,
    )
    return float(p.stdout.strip())


def _timing_sanity(rows: list[tuple[str, float, float]], text: str, duration: float) -> dict[str, Any]:
    words = text.split()
    if not rows:
        raise RuntimeError("default voice route produced no usable word timing evidence")
    if abs(len(rows) - len(words)) > max(3, int(0.2 * len(words))):
        raise RuntimeError(f"timing count mismatch: {len(rows)} timings vs {len(words)} script words")
    prev = -1.0
    for i, (_, st, en) in enumerate(rows):
        st, en = float(st), float(en)
        if st < prev or en < st or st < 0:
            raise RuntimeError(f"non-monotonic timing at index {i}: {(st, en)}")
        if en > duration + 0.75:
            raise RuntimeError(f"timing extends beyond audio at index {i}: {en} > {duration}")
        prev = st
    return {
        "script_word_count": len(words),
        "timing_count": len(rows),
        "first_start_s": round(float(rows[0][1]), 3),
        "last_end_s": round(float(rows[-1][2]), 3),
    }


def probe(out_dir: str) -> dict[str, Any]:
    root = Path(out_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    mp3 = root / "edge_voice.mp3"

    # This probe must prove Edge itself, not succeed by silently dropping to
    # Piper. Track the Edge Python API and make a Piper fallback fatal.
    real_edge = legacy._edge_tts_with_timings
    real_piper = legacy._piper_tts
    edge_results: list[int] = []
    piper_attempts: list[bool] = []

    def tracked_edge(text, voice, rate, out_mp3):
        rows = real_edge(text, voice, rate, out_mp3)
        edge_results.append(len(rows or []))
        return rows

    def forbidden_piper(text, out_mp3):
        piper_attempts.append(True)
        raise RuntimeError("default Edge voice probe fell through to Piper")

    old_engine = os.environ.get("VOICE_ENGINE")
    os.environ["VOICE_ENGINE"] = "edge"
    legacy._edge_tts_with_timings = tracked_edge
    legacy._piper_tts = forbidden_piper
    legacy.WORD_TIMINGS[:] = []
    try:
        voice = legacy.PROFILE.get("edge_voice") or "en-GB-RyanNeural"
        if not legacy.tts_full(TEXT, str(mp3), voice, legacy.EDGE_RATE):
            raise RuntimeError("main.tts_full did not complete through default Edge route")
        if not edge_results:
            raise RuntimeError("Edge Python streaming API was never exercised")
        if piper_attempts:
            raise RuntimeError("Edge probe attempted Piper fallback")
        if not mp3.is_file() or mp3.stat().st_size < 1000:
            raise RuntimeError("Edge voice output is empty/trivial")
        duration = _duration(mp3)
        if duration <= 1.0:
            raise RuntimeError(f"Edge voice output duration is trivial: {duration}")

        timing_source = "edge_word_boundary"
        timings = list(legacy.WORD_TIMINGS)
        if not timings:
            # Exact production fallback: if Edge audio arrives without trusted
            # WordBoundary data, recover timing from the already-prefetched local
            # faster-whisper model. The workflow runs this with HF offline.
            timings = legacy.whisper_align(str(mp3), TEXT)
            if not timings:
                raise RuntimeError("Edge returned no trusted boundaries and Whisper alignment failed")
            timing_source = "faster_whisper_fallback"
        timing = _timing_sanity(timings, TEXT, duration)

        report = {
            "schema": SCHEMA,
            "tts_router_used": "main.tts_full",
            "requested_engine": "edge",
            "edge_voice": voice,
            "edge_rate": legacy.EDGE_RATE,
            "edge_python_api_calls": len(edge_results),
            "edge_boundary_counts_returned": edge_results,
            "piper_fallback_attempted": bool(piper_attempts),
            "timing_source": timing_source,
            "timing": timing,
            "duration_s": round(duration, 3),
            "audio_bytes": mp3.stat().st_size,
            "provider_calls_made": 0,
            "publishing_side_effects": 0,
        }
        QE.write_json(root / "edge_voice_report.json", report)
        return report
    finally:
        legacy._edge_tts_with_timings = real_edge
        legacy._piper_tts = real_piper
        legacy.WORD_TIMINGS[:] = []
        if old_engine is None:
            os.environ.pop("VOICE_ENGINE", None)
        else:
            os.environ["VOICE_ENGINE"] = old_engine


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="artifacts/production_realism_proof/edge_voice")
    args = ap.parse_args()
    print(json.dumps(probe(args.out), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
