#!/usr/bin/env python3
"""Blind zero-paid-call voice bakeoff for the private flagship certification lane.

This compares the TWO narration engines the current renderer can actually use
without paid TTS credentials:

- Edge TTS using the active page profile voice/rate;
- Piper using the same offline model, length scale, and sentence silence as main.py.

The input is ALWAYS ``narration.spoken_text(manifest)`` so the listening test is
performed on the exact canonical Writer V2.1 spoken contract rather than the
legacy ``manifest['script']`` convenience field. Provider originals are retained
and every candidate is normalized to the same mono 48-kHz PCM WAV / -16 LUFS
review surface before blind A/B labeling.

No winner is selected automatically. No paid provider secret is read. A result
with only one surviving engine is useful availability evidence but is explicitly
marked ``comparison_ready=false``; two surviving engines are required for a real
blind comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from narration import spoken_text
import profiles


DEFAULT_EDGE_RATE = "-5%"
DEFAULT_PIPER_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices", "voice.onnx")
DEFAULT_PIPER_LENGTH_SCALE = "1.25"
DEFAULT_PIPER_SENTENCE_SILENCE = "0.35"


def _canonical_text(manifest_path: str) -> str:
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    text = spoken_text(manifest).strip()
    if not text:
        raise ValueError("canonical spoken_text(manifest) is empty")
    return text


def _profile_edge_voice() -> str:
    profile, _page = profiles.get_profile()
    return str(profile.get("edge_voice") or "en-GB-RyanNeural")


def generate_edge(text: str, dest: str, voice: str, rate: str) -> dict[str, Any]:
    subprocess.run(
        ["edge-tts", "--voice", voice, f"--rate={rate}", "--text", text, "--write-media", dest],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if not os.path.isfile(dest) or os.path.getsize(dest) < 1000:
        raise RuntimeError("Edge TTS produced no usable audio")
    return {"provider": "edge", "model": "edge-tts", "voice": voice, "rate": rate}


def generate_piper(
    text: str,
    dest: str,
    model: str,
    length_scale: str,
    sentence_silence: str,
) -> dict[str, Any]:
    if not os.path.isfile(model) or os.path.getsize(model) < 1000:
        raise FileNotFoundError(f"Piper model missing/unusable: {model}")
    subprocess.run(
        [
            "piper", "-m", model, "-f", dest,
            "--length-scale", str(length_scale),
            "--sentence-silence", str(sentence_silence),
        ],
        input=text,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if not os.path.isfile(dest) or os.path.getsize(dest) < 1000:
        raise RuntimeError("Piper produced no usable WAV")
    return {
        "provider": "piper",
        "model": os.path.basename(model),
        "length_scale": str(length_scale),
        "sentence_silence": str(sentence_silence),
    }


def normalize_for_blind(src: str, dest: str) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", src, "-vn",
            "-af", "loudnorm=I=-16:LRA=7:TP=-1.5",
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", dest,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=180,
    )
    if not os.path.isfile(dest) or os.path.getsize(dest) < 1000:
        raise RuntimeError("blind normalization produced no usable WAV")


def _blind_order(text: str, labels: list[str]) -> list[str]:
    """Deterministic but narration-dependent order so Edge is not always sample A."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return sorted(labels, key=lambda label: hashlib.sha256(digest + label.encode("utf-8")).digest())


def review_stub(letter: str) -> dict[str, Any]:
    return {
        "sample": letter,
        "naturalness_0_10": None,
        "scientific_pronunciation_0_10": None,
        "pacing_0_10": None,
        "emotional_fit_0_10": None,
        "breath_pause_quality_0_10": None,
        "sounds_ai_0_10": None,
        "would_use_in_final": None,
        "notes": "",
    }


def build_plan(
    text: str,
    edge_voice: str,
    edge_rate: str,
    piper_model: str,
    piper_length_scale: str,
    piper_sentence_silence: str,
) -> dict[str, Any]:
    return {
        "schema": "quality-free-voice-bakeoff-v1",
        "script_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "script_chars": len(text),
        "script_words": len(text.split()),
        "canonical_spoken_text": True,
        "paid_provider_calls_allowed": False,
        "automatic_winner_selection": False,
        "providers": [
            {
                "provider": "edge",
                "voice": edge_voice,
                "rate": edge_rate,
                "requires_network": True,
                "paid": False,
            },
            {
                "provider": "piper",
                "model": piper_model,
                "length_scale": str(piper_length_scale),
                "sentence_silence": str(piper_sentence_silence),
                "requires_network": False,
                "paid": False,
            },
        ],
    }


def run_bakeoff(
    manifest_path: str,
    out_dir: str,
    *,
    edge_voice: str,
    edge_rate: str,
    piper_model: str,
    piper_length_scale: str,
    piper_sentence_silence: str,
    plan_only: bool = False,
) -> dict[str, Any]:
    text = _canonical_text(manifest_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    plan = build_plan(
        text, edge_voice, edge_rate, piper_model,
        piper_length_scale, piper_sentence_silence,
    )
    (out / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (out / "script.txt").write_text(text + "\n", encoding="utf-8")
    if plan_only:
        return {**plan, "plan_only": True, "candidate_count": 0, "comparison_ready": False}

    candidates: dict[str, tuple[str, dict[str, Any]]] = {}
    blocked: list[dict[str, str]] = []

    edge_src = str(out / "original_edge.mp3")
    try:
        candidates["edge"] = (
            edge_src,
            generate_edge(text, edge_src, edge_voice, edge_rate),
        )
    except Exception as exc:  # noqa: BLE001 -- preserve Piper comparison evidence
        blocked.append({"provider": "edge", "error": f"{type(exc).__name__}: {exc}"})

    piper_src = str(out / "original_piper.wav")
    try:
        candidates["piper"] = (
            piper_src,
            generate_piper(
                text, piper_src, piper_model,
                piper_length_scale, piper_sentence_silence,
            ),
        )
    except Exception as exc:  # noqa: BLE001 -- preserve Edge comparison evidence
        blocked.append({"provider": "piper", "error": f"{type(exc).__name__}: {exc}"})

    ordered = _blind_order(text, list(candidates))
    blind_review: list[dict[str, Any]] = []
    blind_key: dict[str, Any] = {}
    for idx, provider in enumerate(ordered):
        letter = chr(ord("A") + idx)
        src, meta = candidates[provider]
        dest = str(out / f"blind_{letter}.wav")
        normalize_for_blind(src, dest)
        blind_review.append(review_stub(letter))
        blind_key[letter] = {
            "provider": provider,
            "source_file": os.path.basename(src),
            **meta,
        }

    (out / "blind_review.json").write_text(json.dumps(blind_review, indent=2), encoding="utf-8")
    (out / "blind_key.json").write_text(json.dumps(blind_key, indent=2), encoding="utf-8")
    report = {
        **plan,
        "plan_only": False,
        "candidate_count": len(candidates),
        "comparison_ready": len(candidates) >= 2,
        "blocked": blocked,
        "blind_samples": [f"blind_{row['sample']}.wav" for row in blind_review],
        "human_review_required": True,
        "production_voice_changed": False,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not candidates:
        raise RuntimeError("neither free narration engine generated a usable candidate")
    return report


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--out-dir", default="artifacts/quality_certification/voice_bakeoff")
    p.add_argument("--edge-voice", default="")
    p.add_argument("--edge-rate", default=os.getenv("EDGE_RATE", DEFAULT_EDGE_RATE))
    p.add_argument("--piper-model", default=os.getenv("PIPER_MODEL", DEFAULT_PIPER_MODEL))
    p.add_argument("--piper-length-scale", default=os.getenv("PIPER_LENGTH_SCALE", DEFAULT_PIPER_LENGTH_SCALE))
    p.add_argument("--piper-sentence-silence", default=os.getenv("PIPER_SENTENCE_SILENCE", DEFAULT_PIPER_SENTENCE_SILENCE))
    p.add_argument("--plan-only", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    edge_voice = args.edge_voice.strip() or _profile_edge_voice()
    try:
        report = run_bakeoff(
            args.manifest,
            args.out_dir,
            edge_voice=edge_voice,
            edge_rate=args.edge_rate,
            piper_model=args.piper_model,
            piper_length_scale=args.piper_length_scale,
            piper_sentence_silence=args.piper_sentence_silence,
            plan_only=args.plan_only,
        )
    except Exception as exc:
        print(f"FREE VOICE BAKEOFF FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
