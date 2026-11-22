#!/usr/bin/env python3
"""Offline REHEARSAL of a whole render: the real main() with the network stubbed out.

A real render costs ~15-25 minutes of CI and real provider credit, and a crash in new
rendering code only shows up at the end. This runs the SAME main() locally -- real
Kokoro voice, real whisper alignment, real ffmpeg, real caption/cut/audit/mix code -- with
only the footage providers replaced by local synthetic clips and stills, so the paths that
matter are all exercised: multi-source cuts, a black-headed clip, a still scene, a card
scene, the timer card, the sound bed, the audit.

    KOKORO_MODEL=... KOKORO_VOICES=... python rehearsal.py manifests/human_vacuum_v2.json OUTDIR

It proves the code RUNS and the shot logic behaves; it proves nothing about real stock
footage relevance.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

os.environ.setdefault("GROQ_API_KEY", "x")
for k in ("ELEVENLABS_API_KEY", "FAL_KEY", "GEMINI_API_KEY", "PEXELS_API_KEY"):
    os.environ.pop(k, None)
import main as M


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def make_pool(d):
    pool = []
    # bright, high-contrast, moving synthetic footage (testsrc2) with a different hue per clip, so a
    # cut between two of them is a real visual change like a cut between two different stock shots
    for i, (hue, dur) in enumerate(((0, 8), (60, 6), (120, 9), (180, 5), (240, 7), (300, 6))):
        p = os.path.join(d, f"pool{i}.mp4")
        _ff("-f", "lavfi", "-i", f"testsrc2=s=540x960:r=30:d={dur},hue=h={hue},eq=brightness=0.12",
            "-pix_fmt", "yuv420p", p)
        pool.append(p)
    black_head = os.path.join(d, "blackhead.mp4")                 # 2.5 s of black, then picture
    _ff("-f", "lavfi", "-i", "color=c=black:s=540x960:d=2.5:r=30",
        "-f", "lavfi", "-i", "testsrc2=s=540x960:r=30:d=6,hue=h=90,eq=brightness=0.12",
        "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", black_head)
    still = os.path.join(d, "still.jpg")
    _ff("-f", "lavfi", "-i", "testsrc2=s=1080x1620:r=1:d=1,hue=h=30", "-frames:v", "1", still)
    return pool, black_head, still


def rehearse(manifest_path, outdir):
    os.makedirs(outdir, exist_ok=True)
    pool, black_head, still = make_pool(outdir)
    M.WORK, M.OUT = os.path.join(outdir, "work"), os.path.join(outdir, "out")
    m = json.load(open(manifest_path))
    n = len(m["scenes"])
    # scene i (1-based) -> behaviour; picks exercise every path
    mode = {}
    for i in range(1, n + 1):
        mode[i] = "clip"
    mode[3] = "still"          # no stock clip -> stills path
    mode[5] = "card"           # nothing at all -> whole-scene card
    mode[6] = "blackhead"      # a source whose first 2.5 s is black
    state = {"calls": 0}

    def scene_no(query):
        for i, s in enumerate(m["scenes"], 1):
            if s["search_query"] == query:
                return i
        return 0

    def fetch_clip(query, dest, intent=None, accept_best=False):
        i = scene_no(query)
        md = mode.get(i, "clip")
        if md in ("still", "card"):
            return (False, None)
        src = black_head if md == "blackhead" else pool[i % len(pool)]
        shutil.copy(src, dest)
        return (True, 7)

    def extra(scene, need, exclude, prefix):
        i = scene_no(scene.get("search_query", ""))
        k = {1: 0, 2: 1, 4: 2, 8: 2, 9: 1}.get(i, 0)
        out = []
        for j in range(min(k, need)):
            p = f"{prefix}_{j}.mp4"
            shutil.copy(pool[(i + j + 1) % len(pool)], p)
            out.append(p)
        return out

    calls = {"ov": 0}

    def openverse(q, dest, skip=None):
        if scene_no_q(q) == 3 and calls["ov"] < 1:
            calls["ov"] += 1
            shutil.copy(still, dest)
            if skip is not None:
                skip.add(f"u{calls['ov']}")
            return True
        return False

    def scene_no_q(q):
        s3 = m["scenes"][2]["search_query"].split()[0]
        return 3 if q.split()[0] == s3 else 0

    M.fetch_clip, M._extra_scene_clips = fetch_clip, extra
    M._inaturalist_image = lambda q, dest: False
    M._openverse_image, M._wikimedia_image = openverse, lambda q, dest, skip=None: False
    M._pollinations_image = lambda scene, dest: False
    M._gemini_image = lambda scene, dest: False
    M._final_qa_check = lambda video, mm: {"ran": True, "audio_judged": False, "footage_matches_narration": 8,
                                           "visual_variety": 8, "caption_legible": 10, "narration_flow": 8,
                                           "biggest_issue": "rehearsal stub"}
    M._persist_qa_to_memory = lambda *a, **k: None
    M.save_used_footage = lambda: None
    sys.argv = ["main.py", manifest_path]
    M.main()
    return os.path.join(M.OUT, "final.mp4")


if __name__ == "__main__":
    path = rehearse(sys.argv[1], sys.argv[2])
    print("REHEARSAL OK ->", path)
