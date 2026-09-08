#!/usr/bin/env python3
"""Zero-call capability preflight for Content Render's integrated quality tools.

Answers a different question from `quality_stack.integration_status()`:
not just "is the module on disk?" but "does this runner appear to have the
credential/binary needed to execute that lane?". No API request is made.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import importlib.util
import os
import shutil
from typing import Callable, Mapping


@dataclass(frozen=True)
class Capability:
    name: str
    status: str  # ready | partial | blocked | runtime_check
    requirements: tuple[str, ...]
    missing: tuple[str, ...] = ()
    note: str = ""

    @property
    def usable_without_runtime_check(self) -> bool:
        return self.status == "ready"


def _has(env: Mapping[str, str], *names: str) -> bool:
    return any(bool(str(env.get(name, "")).strip()) for name in names)


def _bin(which: Callable[[str], str | None], name: str) -> bool:
    try:
        return bool(which(name))
    except Exception:
        return False


def inspect(env: Mapping[str, str] | None = None, which: Callable[[str], str | None] = shutil.which) -> dict[str, Capability]:
    e = dict(os.environ if env is None else env)
    ffmpeg = _bin(which, "ffmpeg")
    edge = _bin(which, "edge-tts")
    fal_pkg = importlib.util.find_spec("fal_client") is not None
    fal_key = _has(e, "FAL_KEY", "FAL_API_KEY")
    groq = _has(e, "GROQ_API_KEY")
    gemini = _has(e, "GEMINI_API_KEY")
    eleven = _has(e, "ELEVENLABS_API_KEY")
    cartesia = _has(e, "CARTESIA_API_KEY")
    you = _has(e, "YOU_API_KEY")
    pexels = _has(e, "PEXELS_API_KEY")

    out: dict[str, Capability] = {}

    out["you_grounded_research"] = Capability(
        "you_grounded_research", "ready" if you else "blocked", ("YOU_API_KEY",),
        () if you else ("YOU_API_KEY",), "source-backed You Answer lane"
    )
    out["compound_mini_research"] = Capability(
        "compound_mini_research", "runtime_check" if groq else "blocked", ("GROQ_API_KEY", "inspectable executed_tools evidence"),
        () if groq else ("GROQ_API_KEY",), "key presence is not proof that Compound returns load-bearing source bindings"
    )
    out["nasa_svs"] = Capability("nasa_svs", "ready", ("outbound HTTPS",), note="no API key")
    out["pubchem"] = Capability("pubchem", "ready", ("outbound HTTPS",), note="no API key")
    out["rcsb_molecular"] = Capability("rcsb_molecular", "ready", ("outbound HTTPS",), note="no API key")
    out["science_motion"] = Capability(
        "science_motion", "ready" if ffmpeg else "blocked", ("ffmpeg",), () if ffmpeg else ("ffmpeg",),
        "deterministic local visual generation"
    )
    out["existing_real_footage"] = Capability(
        "existing_real_footage", "ready" if pexels else "partial", ("PEXELS_API_KEY optional", "public fallback sources"),
        () if pexels else ("PEXELS_API_KEY for Pexels lane",), "Wikimedia/iNaturalist/Openverse/Archive can still provide fallback coverage"
    )

    fal_missing = tuple(x for x, ok in (("FAL_KEY/FAL_API_KEY", fal_key), ("fal-client package", fal_pkg)) if not ok)
    fal_status = "ready" if not fal_missing else "blocked"
    for name in ("still_model_lab", "image_to_video_lab", "fal_video_lab", "video_repair"):
        out[name] = Capability(name, fal_status, ("FAL_KEY or FAL_API_KEY", "fal-client package"), fal_missing)

    out["qwen_asset_vision"] = Capability(
        "qwen_asset_vision", "ready" if groq else "blocked", ("GROQ_API_KEY",), () if groq else ("GROQ_API_KEY",)
    )
    out["gemini_asset_vision"] = Capability(
        "gemini_asset_vision", "ready" if gemini else "blocked", ("GEMINI_API_KEY",), () if gemini else ("GEMINI_API_KEY",)
    )

    voice_missing = []
    if not edge: voice_missing.append("edge-tts executable for baseline")
    if not groq: voice_missing.append("GROQ_API_KEY for Orpheus")
    if not cartesia: voice_missing.append("CARTESIA_API_KEY for Sonic 3.6")
    if not eleven: voice_missing.append("ELEVENLABS_API_KEY for Eleven v3")
    out["voice_lab"] = Capability(
        "voice_lab",
        "ready" if not voice_missing else ("partial" if edge or groq or cartesia or eleven else "blocked"),
        ("edge-tts", "GROQ_API_KEY", "CARTESIA_API_KEY", "ELEVENLABS_API_KEY"),
        tuple(voice_missing),
        "Orpheus additionally may require account model-terms acceptance; verify only during an explicitly authorized lab run",
    )
    out["sound_brain"] = Capability(
        "sound_brain", "ready" if eleven and ffmpeg else "blocked", ("ELEVENLABS_API_KEY", "ffmpeg"),
        tuple(x for x, ok in (("ELEVENLABS_API_KEY", eleven), ("ffmpeg", ffmpeg)) if not ok)
    )
    final_ready = ffmpeg and (groq or gemini)
    out["final_video_qa"] = Capability(
        "final_video_qa", "ready" if final_ready else "blocked", ("ffmpeg", "GROQ_API_KEY or GEMINI_API_KEY"),
        tuple(x for x, ok in (("ffmpeg", ffmpeg), ("GROQ_API_KEY or GEMINI_API_KEY", groq or gemini)) if not ok)
    )
    return out


def summary(env: Mapping[str, str] | None = None, which: Callable[[str], str | None] = shutil.which) -> dict:
    caps = inspect(env, which)
    return {
        "capabilities": {name: asdict(cap) for name, cap in caps.items()},
        "ready": sorted(name for name, cap in caps.items() if cap.status == "ready"),
        "partial": sorted(name for name, cap in caps.items() if cap.status == "partial"),
        "blocked": sorted(name for name, cap in caps.items() if cap.status == "blocked"),
        "runtime_check": sorted(name for name, cap in caps.items() if cap.status == "runtime_check"),
        "provider_calls_made": 0,
    }
