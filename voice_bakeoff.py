#!/usr/bin/env python3
"""voice_bakeoff.py — private, manual TTS comparison for Content Render.

Generates the same narration with Groq Orpheus voices and (optionally) the
current Edge voice. Nothing here is wired into production rendering.

Orpheus V1 English currently limits each request to 200 input characters, so
the script splits narration at natural sentence/phrase boundaries and joins
the returned WAV chunks losslessly when their PCM parameters match.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
import wave

ORPHEUS_MODEL = "canopylabs/orpheus-v1-english"
ORPHEUS_URL = "https://api.groq.com/openai/v1/audio/speech"
ALLOWED_VOICES = {"autumn", "diana", "hannah", "austin", "daniel", "troy"}


def split_for_orpheus(text: str, direction: str = "", hard_limit: int = 200):
    """Split text into <=200-char Orpheus inputs without chopping words.

    Direction is prepended to every chunk, so its characters count toward the
    API limit. Prefer sentence endings, then clause punctuation, then spaces.
    """
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
            # Natural sentence boundary first.
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
        raise AssertionError("internal split error: Orpheus chunk exceeded 200 chars")
    return chunks


def _groq_speech(text: str, voice: str, api_key: str, timeout: float = 60.0):
    body = json.dumps({
        "model": ORPHEUS_MODEL,
        "input": text,
        "voice": voice,
        "response_format": "wav",
    }).encode("utf-8")
    req = urllib.request.Request(
        ORPHEUS_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "content-render/voice-bakeoff",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if not data.startswith(b"RIFF") or b"WAVE" not in data[:16]:
        raise ValueError("Orpheus response was not a WAV file")
    return data


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
    if voice not in ALLOWED_VOICES:
        raise ValueError(f"unsupported Orpheus voice {voice!r}")
    chunks = split_for_orpheus(text, direction=direction)
    if not chunks:
        raise ValueError("empty narration")
    tmp = []
    try:
        for i, chunk in enumerate(chunks):
            data = _groq_speech(chunk, voice, api_key)
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
    return {"voice": voice, "chunks": len(chunks), "characters": len(text)}


def generate_edge(text: str, dest: str, voice: str = "en-GB-RyanNeural", rate: str = "-5%"):
    """Generate the current free baseline with edge-tts CLI."""
    subprocess.run(
        ["edge-tts", "--voice", voice, f"--rate={rate}", "--text", text, "--write-media", dest],
        check=True,
    )


def _load_text(args):
    if args.text.strip():
        return args.text.strip()
    with open(args.manifest) as f:
        m = json.load(f)
    text = str(m.get("script") or "").strip()
    if not text:
        text = " ".join(str(s.get("voiceover") or "") for s in (m.get("scenes") or [])).strip()
    if not text:
        raise ValueError("manifest contains no script/voiceover text")
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="manifest.json")
    ap.add_argument("--text", default="")
    ap.add_argument("--voices", default="troy,daniel,austin")
    ap.add_argument("--direction", default="")
    ap.add_argument("--out-dir", default="voice_bakeoff")
    ap.add_argument("--edge", action="store_true")
    ap.add_argument("--edge-voice", default="en-GB-RyanNeural")
    ap.add_argument("--edge-rate", default="-5%")
    args = ap.parse_args()

    text = _load_text(args)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "script.txt"), "w") as f:
        f.write(text + "\n")

    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise SystemExit("GROQ_API_KEY is required for Orpheus bakeoff")

    report = {"model": ORPHEUS_MODEL, "direction": args.direction, "script_chars": len(text), "outputs": []}
    voices = []
    for raw in args.voices.split(","):
        v = raw.strip().lower()
        if v and v not in voices:
            voices.append(v)

    for v in voices:
        dest = os.path.join(args.out_dir, f"orpheus_{v}.wav")
        meta = generate_orpheus(text, v, dest, key, direction=args.direction)
        meta["file"] = os.path.basename(dest)
        report["outputs"].append(meta)
        print(f"[orpheus] {v}: {meta['chunks']} chunks -> {dest}")

    if args.edge:
        edge_dest = os.path.join(args.out_dir, "edge_current.mp3")
        generate_edge(text, edge_dest, voice=args.edge_voice, rate=args.edge_rate)
        report["outputs"].append({
            "voice": args.edge_voice,
            "provider": "Edge TTS",
            "file": os.path.basename(edge_dest),
        })
        print(f"[edge] {args.edge_voice} -> {edge_dest}")

    with open(os.path.join(args.out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
