#!/usr/bin/env python3
"""Private, manual Voice Lab 2.0 for Content Render.

Compares identical narration across current TTS providers without changing
production voice. Originals are retained, then normalized into opaque blind
A/B/C/... 48-kHz WAV files so loudness/filename bias does not decide the test.

Provider contracts verified 2026-09-03:
- Groq Orpheus V1 English (terms acceptance may block account access)
- Cartesia Sonic 3.6 via POST /tts/bytes, Cartesia-Version 2026-03-01
- ElevenLabs Eleven v3 via POST /v1/text-to-speech/:voice_id
- Edge TTS as the current free baseline

No provider call occurs in --plan-only mode. Missing provider credentials or
voice IDs are reported as blockers instead of silently substituting a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import wave

ORPHEUS_MODEL = "canopylabs/orpheus-v1-english"
ORPHEUS_URL = "https://api.groq.com/openai/v1/audio/speech"
ALLOWED_ORPHEUS_VOICES = {"autumn", "diana", "hannah", "austin", "daniel", "troy"}
# Backward-compatible public name retained for the original PR #43 regression
# suite and any external diagnostic scripts built before Voice Lab 2.0.
ALLOWED_VOICES = ALLOWED_ORPHEUS_VOICES

CARTESIA_MODEL = "sonic-3.6"
CARTESIA_URL = "https://api.cartesia.ai/tts/bytes"
CARTESIA_VERSION = "2026-03-01"

ELEVEN_MODEL = "eleven_v3"
ELEVEN_BASE = "https://api.elevenlabs.io/v1/text-to-speech"

PROVIDER_ORDER = ("edge", "orpheus", "cartesia", "eleven")
VERIFIED_ON = "2026-09-03"


def split_for_orpheus(text: str, direction: str = "", hard_limit: int = 200):
    """Split text into <=200-char Orpheus inputs without chopping words."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []
    prefix = f"[{direction.strip()}] " if direction.strip() else ""
    room = hard_limit - len(prefix)
    if room < 40:
        raise ValueError("direction is too long for Orpheus's 200-character input limit")
    chunks = []
    rest = text
    while rest:
        if len(rest) <= room:
            part, rest = rest, ""
        else:
            window = rest[: room + 1]
            cut = -1
            for pat in (r"[.!?](?=\s)", r"[,;:](?=\s)", r"\s"):
                ms = list(re.finditer(pat, window))
                if ms:
                    m = ms[-1]
                    cut = m.end() if pat != r"\s" else m.start()
                    break
            if cut <= 0:
                cut = room
            part = rest[:cut].strip()
            rest = rest[cut:].strip()
        if part:
            chunks.append(prefix + part)
    if any(len(c) > hard_limit for c in chunks):
        raise AssertionError("Orpheus chunk exceeded 200 chars")
    return chunks


def _http_audio(url: str, body: dict, headers: dict, timeout: float = 90.0) -> bytes:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    if len(data) < 256:
        raise ValueError("TTS provider returned implausibly small audio")
    return data


def _groq_speech(text: str, voice: str, api_key: str) -> bytes:
    return _http_audio(
        ORPHEUS_URL,
        {"model": ORPHEUS_MODEL, "input": text, "voice": voice, "response_format": "wav"},
        {"Authorization": f"Bearer {api_key}", "User-Agent": "content-render/voice-lab"},
    )


def _concat_wavs(paths, dest):
    if not paths:
        raise ValueError("no WAV chunks to concatenate")
    params = None
    frames = []
    for p in paths:
        with wave.open(p, "rb") as w:
            cur = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getcomptype())
            if params is None:
                params = cur
            elif cur != params:
                raise ValueError(f"WAV parameters changed between chunks: {params} vs {cur}")
            frames.append(w.readframes(w.getnframes()))
    channels, width, rate, comptype = params
    with wave.open(dest, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.setcomptype(comptype, "not compressed")
        for blob in frames:
            out.writeframes(blob)


def generate_orpheus(text: str, voice: str, dest: str, api_key: str, direction: str = ""):
    voice = voice.strip().lower()
    if voice not in ALLOWED_ORPHEUS_VOICES:
        raise ValueError(f"unsupported Orpheus voice {voice!r}")
    chunks = split_for_orpheus(text, direction=direction)
    if not chunks:
        raise ValueError("empty narration")
    tmp = []
    try:
        for i, chunk in enumerate(chunks):
            data = _groq_speech(chunk, voice, api_key)
            if not data.startswith(b"RIFF") or b"WAVE" not in data[:16]:
                raise ValueError("Orpheus response was not WAV")
            p = f"{dest}.part{i:02d}.wav"
            with open(p, "wb") as f:
                f.write(data)
            tmp.append(p)
        _concat_wavs(tmp, dest)
    finally:
        for p in tmp:
            try:
                os.remove(p)
            except OSError:
                pass
    return {"provider": "orpheus", "model": ORPHEUS_MODEL, "voice": voice, "chunks": len(chunks)}


def generate_cartesia(text: str, voice_id: str, dest: str, api_key: str, locale: str = "en-US"):
    if not voice_id.strip():
        raise ValueError("Cartesia voice ID required")
    data = _http_audio(
        CARTESIA_URL,
        {
            "model_id": CARTESIA_MODEL,
            "transcript": text,
            "voice": voice_id.strip(),
            "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100},
            "locale": locale,
            "generation_config": {"volume": 1, "speed": 1},
        },
        {"Authorization": f"Bearer {api_key}", "Cartesia-Version": CARTESIA_VERSION},
    )
    if not data.startswith(b"RIFF") or b"WAVE" not in data[:16]:
        raise ValueError("Cartesia response was not WAV")
    with open(dest, "wb") as f:
        f.write(data)
    return {"provider": "cartesia", "model": CARTESIA_MODEL, "voice": voice_id.strip(), "locale": locale}


def generate_eleven(text: str, voice_id: str, dest: str, api_key: str):
    if not voice_id.strip():
        raise ValueError("ElevenLabs voice ID required")
    url = f"{ELEVEN_BASE}/{urllib.parse.quote(voice_id.strip(), safe='')}?output_format=mp3_44100_128"
    data = _http_audio(
        url,
        {"text": text, "model_id": ELEVEN_MODEL},
        {"xi-api-key": api_key},
    )
    with open(dest, "wb") as f:
        f.write(data)
    return {"provider": "eleven", "model": ELEVEN_MODEL, "voice": voice_id.strip()}


def generate_edge(text: str, dest: str, voice: str = "en-GB-RyanNeural", rate: str = "-5%"):
    subprocess.run(["edge-tts", "--voice", voice, f"--rate={rate}", "--text", text, "--write-media", dest], check=True)
    return {"provider": "edge", "model": "edge-tts", "voice": voice, "rate": rate}


def normalize_for_blind(src: str, dest: str):
    """Normalize codec/sample-rate/loudness so volume does not win the bakeoff."""
    subprocess.run([
        "ffmpeg", "-y", "-i", src, "-vn",
        "-af", "loudnorm=I=-16:LRA=7:TP=-1.5",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", dest,
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(dest) or os.path.getsize(dest) < 1000:
        raise RuntimeError("blind normalization produced no usable WAV")


def provider_plan(providers, args) -> list[dict]:
    rows = []
    for p in providers:
        if p == "edge":
            rows.append({"provider": p, "model": "edge-tts", "voice": args.edge_voice, "credential": "none"})
        elif p == "orpheus":
            rows.append({"provider": p, "model": ORPHEUS_MODEL, "voices": args.orpheus_voices, "credential": "GROQ_API_KEY", "known_blocker": "Groq account may require model terms acceptance"})
        elif p == "cartesia":
            rows.append({"provider": p, "model": CARTESIA_MODEL, "voice": args.cartesia_voice_id or "REQUIRED", "credential": "CARTESIA_API_KEY", "api_version": CARTESIA_VERSION})
        elif p == "eleven":
            rows.append({"provider": p, "model": ELEVEN_MODEL, "voice": args.eleven_voice_id or "REQUIRED", "credential": "ELEVENLABS_API_KEY"})
    return rows


def parse_providers(raw: str) -> list[str]:
    out=[]
    for x in raw.split(","):
        p=x.strip().lower()
        if not p:
            continue
        if p not in PROVIDER_ORDER:
            raise ValueError(f"unknown provider {p!r}")
        if p not in out:
            out.append(p)
    if not out:
        raise ValueError("no providers selected")
    return out


def _load_text(args):
    if args.text.strip():
        return args.text.strip()
    with open(args.manifest) as f:
        m=json.load(f)
    text=str(m.get("script") or "").strip()
    if not text:
        text=" ".join(str(s.get("voiceover") or "") for s in (m.get("scenes") or [])).strip()
    if not text:
        raise ValueError("manifest contains no narration")
    return text


def review_stub(letter: str) -> dict:
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


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--manifest", default="manifest.json")
    ap.add_argument("--text", default="")
    ap.add_argument("--providers", default="edge,orpheus,cartesia,eleven")
    ap.add_argument("--orpheus-voices", default="troy")
    ap.add_argument("--direction", default="")
    ap.add_argument("--cartesia-voice-id", default="")
    ap.add_argument("--cartesia-locale", default="en-US")
    ap.add_argument("--eleven-voice-id", default="")
    ap.add_argument("--edge-voice", default="en-GB-RyanNeural")
    ap.add_argument("--edge-rate", default="-5%")
    ap.add_argument("--out-dir", default="voice_bakeoff")
    ap.add_argument("--plan-only", action="store_true")
    args=ap.parse_args()

    text=_load_text(args)
    providers=parse_providers(args.providers)
    os.makedirs(args.out_dir, exist_ok=True)
    plan={"verified_on":VERIFIED_ON,"script_chars":len(text),"providers":provider_plan(providers,args),"paid_calls":False}
    with open(os.path.join(args.out_dir,"plan.json"),"w") as f:
        json.dump(plan,f,indent=2)
    with open(os.path.join(args.out_dir,"script.txt"),"w") as f:
        f.write(text+"\n")
    if args.plan_only:
        print(json.dumps(plan,indent=2))
        print("PLAN ONLY: zero provider calls made.")
        return

    candidates=[]
    blocked=[]
    def capture(provider, label, fn, ext):
        original=os.path.join(args.out_dir,f"original_{label}.{ext}")
        try:
            meta=fn(original)
            candidates.append((provider,label,original,meta))
        except Exception as exc:
            blocked.append({"provider":provider,"label":label,"error":f"{type(exc).__name__}: {exc}"})

    if "edge" in providers:
        capture("edge","edge",lambda d:generate_edge(text,d,args.edge_voice,args.edge_rate),"mp3")
    if "orpheus" in providers:
        key=os.getenv("GROQ_API_KEY","")
        for v in [x.strip().lower() for x in args.orpheus_voices.split(",") if x.strip()]:
            if key:
                capture("orpheus",f"orpheus_{v}",lambda d,v=v:generate_orpheus(text,v,d,key,args.direction),"wav")
            else:
                blocked.append({"provider":"orpheus","label":v,"error":"GROQ_API_KEY missing"})
    if "cartesia" in providers:
        key=os.getenv("CARTESIA_API_KEY","")
        if key and args.cartesia_voice_id:
            capture("cartesia","cartesia",lambda d:generate_cartesia(text,args.cartesia_voice_id,d,key,args.cartesia_locale),"wav")
        else:
            blocked.append({"provider":"cartesia","label":"cartesia","error":"CARTESIA_API_KEY and --cartesia-voice-id required"})
    if "eleven" in providers:
        key=os.getenv("ELEVENLABS_API_KEY","")
        if key and args.eleven_voice_id:
            capture("eleven","eleven",lambda d:generate_eleven(text,args.eleven_voice_id,d,key),"mp3")
        else:
            blocked.append({"provider":"eleven","label":"eleven","error":"ELEVENLABS_API_KEY and --eleven-voice-id required"})

    blind=[]
    keymap={}
    for idx,(provider,label,src,meta) in enumerate(candidates):
        letter=chr(ord("A")+idx)
        dest=os.path.join(args.out_dir,f"blind_{letter}.wav")
        normalize_for_blind(src,dest)
        blind.append(review_stub(letter))
        keymap[letter]={"provider":provider,"label":label,"source_file":os.path.basename(src),**meta}

    with open(os.path.join(args.out_dir,"blind_review.json"),"w") as f:
        json.dump(blind,f,indent=2)
    with open(os.path.join(args.out_dir,"blind_key.json"),"w") as f:
        json.dump(keymap,f,indent=2)
    report={**plan,"paid_calls":bool(candidates),"candidate_count":len(candidates),"blocked":blocked,"blind_samples":[f"blind_{x['sample']}.wav" for x in blind]}
    with open(os.path.join(args.out_dir,"report.json"),"w") as f:
        json.dump(report,f,indent=2)
    if not candidates:
        raise SystemExit("no voice candidate generated")
    print(json.dumps(report,indent=2))

if __name__=="__main__":
    main()
