#!/usr/bin/env python3
"""Measure caption sync against the audio, independently of the pipeline.

The pipeline times captions from ONE whisper pass over the raw narration
(main.whisper_align, model "base") and then shifts them per scene. That has never
been checked against what a viewer actually hears in the FINISHED video. This tool
does: it decodes the audio of a rendered mp4, transcribes it with a DIFFERENT
faster-whisper model (default "small"), and compares every caption event's start
to the independently measured onset of the same word.

    python measure_caption_sync.py out/final.mp4 work/captions.ass [--model small]

Positive delta = the caption appears AFTER the word is spoken (late); negative =
the caption leads the voice (the worse failure: the eye gets ahead of the ear).
Pure helpers (parse_ass, summarize, match_events) are unit-tested without audio.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile

_NAME_RE = re.compile(r"w(\d+)")


def _ass_seconds(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _norm(w):
    return re.sub(r"[^a-z0-9]", "", (w or "").lower())


def parse_ass(text):
    """[(start_s, end_s, active_word_key, all_words)] for every Dialogue event.

    The ACTIVE word of an event is named in the Name field ("w2" = third word) by
    phrase captions; for one-word captions it is the event's first word."""
    out = []
    for line in text.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        raw = parts[9]
        plain = re.sub(r"\{[^}]*\}", "", raw).strip()
        words = [_norm(w) for w in plain.split() if _norm(w)]
        if not words:
            continue
        nm = _NAME_RE.fullmatch(parts[4].strip())
        active = words[min(int(nm.group(1)), len(words) - 1)] if nm else words[0]
        out.append((_ass_seconds(parts[1]), _ass_seconds(parts[2]), active, words))
    return out


def match_events(events, heard):
    """Align caption events to independently-heard words by CONTENT.
    events: parse_ass output; heard: [(word, start, end)]. Returns
    [(event_start, heard_start, key)] for the matched events."""
    ev_keys = [e[2] for e in events]
    h_keys = [_norm(h[0]) for h in heard]
    sm = difflib.SequenceMatcher(None, ev_keys, h_keys, autojunk=False)
    out = []
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            out.append((events[a + k][0], heard[b + k][1], ev_keys[a + k]))
    return out


def summarize(pairs, n_events):
    """Delta statistics (seconds) for matched (event_start, heard_start, key)."""
    d = sorted(e - h for e, h, _ in pairs)
    if not d:
        return {"events": n_events, "matched": 0}

    def pct(p):
        return d[min(len(d) - 1, int(round(p * (len(d) - 1))))]

    return {
        "events": n_events, "matched": len(d),
        "median_s": round(statistics.median(d), 3), "mean_s": round(statistics.fmean(d), 3),
        "p05_s": round(pct(0.05), 3), "p95_s": round(pct(0.95), 3),
        "min_s": round(d[0], 3), "max_s": round(d[-1], 3),
        "lead_gt_0.10s": sum(1 for x in d if x < -0.10),   # caption BEFORE the voice
        "late_gt_0.25s": sum(1 for x in d if x > 0.25),    # caption noticeably after
    }


def transcribe(video, model_name):
    from faster_whisper import WhisperModel
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav],
                       check=True)
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segs, _ = model.transcribe(wav, word_timestamps=True, language="en")
        return [(w.word.strip(), float(w.start), float(w.end)) for s in segs for w in (s.words or [])]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("ass")
    ap.add_argument("--model", default="small")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    events = parse_ass(open(a.ass).read())
    heard = transcribe(a.video, a.model)
    rep = summarize(match_events(events, heard), len(events))
    rep["measured_with"] = f"faster-whisper {a.model}"
    print(json.dumps(rep, indent=None if a.json else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
