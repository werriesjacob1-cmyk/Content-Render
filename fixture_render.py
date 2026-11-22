#!/usr/bin/env python3
"""Local, offline fixture render: the REAL voice -> whisper_align -> split_audio ->
build_ass -> caption burn-in code from main.py, over synthetic scene footage.

It exists to look at captions/timing/frames without triggering a real render
(no providers, no stock footage, no publishing). Footage is a labelled colour
gradient per scene, so what you see in the frames is the caption layer and the
cut timing, not B-roll quality -- it proves nothing about footage relevance.

    KOKORO_MODEL=... KOKORO_VOICES=... python fixture_render.py OUTDIR [manifest.json]
Writes OUTDIR/captioned.mp4, OUTDIR/captions.ass, OUTDIR/frames/*.png.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

os.environ.setdefault("GROQ_API_KEY", "x")
import main as M

DEFAULT = {
    "title": "Fixture", "keyword": "honey fungus",
    "hook": "The biggest living thing on Earth is a fungus you have walked over.",
    "scenes": [
        {"voiceover": "The biggest living thing on Earth is a fungus you have walked over.", "search_query": "forest floor"},
        {"voiceover": "It sits under a forest in Oregon and covers about four square miles.", "search_query": "oregon forest"},
        {"voiceover": "So is it one animal, or thousands of separate ones?", "search_query": "mushrooms"},
        {"voiceover": "Genetic tests say every thread shares exactly the same DNA.", "search_query": "dna strand"},
        {"voiceover": "It spreads by growing a little further each year, for thousands of years.", "search_query": "roots soil"},
        {"voiceover": "And what does it do to the trees above it?", "search_query": "dying trees"},
        {"voiceover": "It slowly rots their roots from the inside, one tree at a time.", "search_query": "tree roots"},
        {"voiceover": "Scientists still argue whether that counts as one creature or a colony.", "search_query": "microscope"},
    ],
}
COLORS = ["0x1f3b4d", "0x3d2b56", "0x2b4d3a", "0x4d3b1f", "0x1f4d4a", "0x4d1f3b", "0x3a4d1f", "0x1f2b56"]


def build(outdir, manifest):
    work, out = os.path.join(outdir, "work"), os.path.join(outdir, "out")
    for d in (work, out):
        os.makedirs(d, exist_ok=True)
    M.WORK, M.OUT = work, out
    m = manifest
    M._apply_vibe(m.get("vibe", "awe"))
    script = M.spoken_text(m)
    mp3 = os.path.join(work, "full_vo.mp3")
    assert M.tts_full(script, mp3, M.PROFILE.get("edge_voice", "en-GB-RyanNeural"), M.EDGE_RATE), "no voice engine worked"
    if not M.WORD_TIMINGS:
        M.WORD_TIMINGS[:] = M.whisper_align(mp3, script)
    segments = M.split_audio(mp3, m["scenes"], work)
    files = []
    for i, (sc, (seg, dur)) in enumerate(zip(m["scenes"], segments), 1):
        p = os.path.join(work, f"s{i}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"gradients=s={M.W}x{M.H}:d={dur:.3f}:c0={COLORS[i % 8]}:c1=0x101010:speed=0.02:r=30",
                        "-i", seg, "-t", f"{dur:.3f}", "-map", "0:v", "-map", "1:a", "-pix_fmt", "yuv420p",
                        "-c:v", "libx264", "-c:a", "aac", "-shortest", p], check=True)
        files.append(p)
    body = os.path.join(work, "body.mp4")
    M.build_body_concat(files, body)
    actual = [M.ffprobe_dur(f) for f in files]
    M._KEYWORD_TOKENS = {M.re.sub(r"[^A-Z0-9]", "", w.upper()) for w in M.re.findall(r"[A-Za-z0-9']+", m.get("keyword", "")) if len(w) > 2}
    ass = os.path.join(outdir, "captions.ass")
    M.build_ass(m["scenes"], segments, actual, ass, headline=m.get("hook_headline", ""))
    cap = os.path.join(outdir, "captioned.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", body, "-vf", f"ass='{ass}':fontsdir='{M.FONTS_DIR}'",
                    "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", cap], check=True)
    return cap, ass, segments


def frames(video, outdir, times):
    fd = os.path.join(outdir, "frames"); os.makedirs(fd, exist_ok=True)
    for t in times:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                        os.path.join(fd, f"t{t:05.2f}.png")], check=True)
    return fd


if __name__ == "__main__":
    outdir = sys.argv[1]
    man = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else DEFAULT
    cap, ass, seg = build(outdir, man)
    dur = M.ffprobe_dur(cap)
    print(json.dumps({"video": cap, "ass": ass, "duration_s": round(dur, 2)}))
