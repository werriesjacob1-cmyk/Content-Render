#!/usr/bin/env python3
"""video_model_bakeoff.py — private FAL science-video model comparison.

This is NOT production routing. It generates the SAME difficult science scene
through several current FAL video models, downloads their outputs, normalizes a
9:16 review copy, and records latency/errors so humans can pick a winner.

Requires FAL_KEY. Uses fal-client so long-running queue semantics are handled
by the official client instead of reimplementing polling.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.request

try:
    import fal_client
except Exception:
    fal_client = None


MODEL_SPECS = {
    "ltx_current": {
        "model": "fal-ai/ltx-video",
        "arguments": lambda prompt, duration: {"prompt": prompt},
        "note": "current production baseline",
    },
    "hailuo23": {
        "model": "fal-ai/minimax/hailuo-2.3/standard/text-to-video",
        "arguments": lambda prompt, duration: {
            "prompt": prompt,
            "prompt_optimizer": True,
            "duration": "6" if int(duration) <= 6 else "10",
        },
        "note": "MiniMax Hailuo 2.3 Standard 768p",
    },
    "grok_imagine": {
        "model": "xai/grok-imagine-video/text-to-video",
        "arguments": lambda prompt, duration: {
            "prompt": prompt,
            "duration": max(1, int(duration)),
            "resolution": "720p",
            "aspect_ratio": "9:16",
        },
        "note": "xAI Grok Imagine Video 720p native vertical",
    },
    "seedance2_fast": {
        "model": "bytedance/seedance-2.0/fast/text-to-video",
        "arguments": lambda prompt, duration: {
            "prompt": prompt,
            "duration": max(4, min(15, int(duration))),
            "resolution": "720p",
            "aspect_ratio": "9:16",
            "generate_audio": False,
            "bitrate_mode": "high",
        },
        "note": "ByteDance Seedance 2.0 Fast 720p native vertical",
    },
}


def parse_models(raw: str):
    out = []
    for name in (raw or "").split(","):
        name = name.strip()
        if not name:
            continue
        if name not in MODEL_SPECS:
            raise ValueError(f"unknown model alias {name!r}; choose from {sorted(MODEL_SPECS)}")
        if name not in out:
            out.append(name)
    if not out:
        raise ValueError("no models selected")
    return out


def extract_video_url(result):
    """Support the common fal response shapes without model-specific parsing."""
    if not isinstance(result, dict):
        return None
    video = result.get("video")
    if isinstance(video, dict) and video.get("url"):
        return video["url"]
    videos = result.get("videos")
    if isinstance(videos, list) and videos and isinstance(videos[0], dict):
        return videos[0].get("url")
    # Some endpoints wrap actual data one level down.
    data = result.get("data")
    if isinstance(data, dict):
        return extract_video_url(data)
    return None


def download(url: str, dest: str):
    req = urllib.request.Request(url, headers={"User-Agent": "content-render/video-bakeoff"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def normalize_vertical(src: str, dest: str, duration: int):
    """Create a consistent 1080x1920 review copy; keep originals too."""
    subprocess.run([
        "ffmpeg", "-y", "-i", src, "-t", str(duration),
        "-vf",
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1",
        "-an", "-r", "30", "-pix_fmt", "yuv420p", "-c:v", "libx264", dest,
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_one(alias: str, prompt: str, duration: int, out_dir: str):
    if fal_client is None:
        raise RuntimeError("fal-client is not installed")
    spec = MODEL_SPECS[alias]
    args = spec["arguments"](prompt, duration)
    started = time.time()
    result = fal_client.subscribe(spec["model"], arguments=args, with_logs=True)
    elapsed = time.time() - started
    url = extract_video_url(result)
    if not url:
        raise RuntimeError(f"{alias} returned no video URL; keys={list(result) if isinstance(result, dict) else type(result)}")

    raw = os.path.join(out_dir, f"{alias}_original.mp4")
    review = os.path.join(out_dir, f"{alias}_review_9x16.mp4")
    download(url, raw)
    normalize_vertical(raw, review, duration)
    return {
        "alias": alias,
        "model": spec["model"],
        "note": spec["note"],
        "seconds": round(elapsed, 2),
        "arguments": args,
        "source_url": url,
        "original": os.path.basename(raw),
        "review": os.path.basename(review),
        "bytes": os.path.getsize(raw),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--duration", type=int, default=6)
    ap.add_argument("--models", default="ltx_current,hailuo23,grok_imagine,seedance2_fast")
    ap.add_argument("--out-dir", default="video_bakeoff")
    args = ap.parse_args()

    if not os.environ.get("FAL_KEY") and os.environ.get("FAL_API_KEY"):
        os.environ["FAL_KEY"] = os.environ["FAL_API_KEY"]
    if not os.environ.get("FAL_KEY"):
        raise SystemExit("FAL_KEY or FAL_API_KEY is required")
    models = parse_models(args.models)
    os.makedirs(args.out_dir, exist_ok=True)

    report = {
        "prompt": args.prompt,
        "duration": args.duration,
        "models_requested": models,
        "results": [],
        "errors": [],
    }
    with open(os.path.join(args.out_dir, "prompt.txt"), "w") as f:
        f.write(args.prompt + "\n")

    for alias in models:
        print(f"\n=== {alias}: {MODEL_SPECS[alias]['model']} ===")
        try:
            meta = run_one(alias, args.prompt, args.duration, args.out_dir)
            report["results"].append(meta)
            print(json.dumps(meta, indent=2))
        except Exception as e:
            err = {"alias": alias, "model": MODEL_SPECS[alias]["model"],
                   "error": f"{type(e).__name__}: {e}"}
            report["errors"].append(err)
            print("ERROR:", json.dumps(err))
            # Continue so one unavailable model does not waste the entire paid comparison.

    with open(os.path.join(args.out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)

    if not report["results"]:
        raise SystemExit("all requested models failed")
    print(f"\nCompleted {len(report['results'])}/{len(models)} models. Review *_review_9x16.mp4 side by side.")


if __name__ == "__main__":
    main()
