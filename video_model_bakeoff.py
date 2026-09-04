#!/usr/bin/env python3
"""Private, budget-guarded FAL science-video model lab.

This is NOT production routing.  It sends the SAME difficult science scene to
explicitly selected model/version endpoints, keeps originals, normalizes muted
9:16 review copies, and writes a human/vision-review template.

Safety properties:
- no model call occurs before the selected run passes a hard USD budget guard;
- unknown-price endpoints require a separate explicit opt-in;
- --plan-only performs zero paid calls and needs no API key;
- native audio is disabled where the endpoint exposes that switch so visual
  quality is compared independently;
- one model failure does not waste the rest of an approved comparison.

Endpoint IDs / conservative price estimates were verified against fal model
pages on 2026-09-03. Pricing can change, so the guard intentionally uses the
higher current/regular figure when launch promotions exist.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
import urllib.request

try:
    import fal_client
except Exception:
    fal_client = None


VERIFIED_ON = "2026-09-03"


def _nearest(value: int, allowed: tuple[int, ...]) -> int:
    value = int(value)
    return min(allowed, key=lambda x: (abs(x - value), x))


def _ltx23_args(prompt: str, duration: int) -> dict:
    return {
        "prompt": prompt,
        "duration": _nearest(duration, (6, 8, 10)),
        "resolution": "1080p",
        "aspect_ratio": "9:16",
        "fps": 25,
        "generate_audio": False,
    }


def _h3_args(prompt: str, duration: int) -> dict:
    return {
        "prompt": prompt,
        "duration": max(5, min(15, int(duration))),
        "resolution": "768P",
        "aspect_ratio": "9:16",
        "enable_safety_checker": True,
        "prompt_expansion_mode": "quality",
    }


def _wan30_args(prompt: str, duration: int) -> dict:
    return {
        "prompt": prompt,
        "duration": max(1, int(duration)),
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "audio": False,
        "enable_prompt_expansion": True,
    }


def _kling3_args(prompt: str, duration: int) -> dict:
    return {
        "prompt": prompt,
        "duration": str(max(3, min(15, int(duration)))),
        "generate_audio": False,
        "shot_type": "customize",
        "aspect_ratio": "9:16",
        "negative_prompt": (
            "text, subtitles, watermark, logo, extra limbs, distorted anatomy, "
            "wrong species, fantasy anatomy, low quality, blur"
        ),
    }


def _veo31_args(prompt: str, duration: int) -> dict:
    d = _nearest(duration, (4, 6, 8))
    return {
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "duration": f"{d}s",
        "resolution": "720p",
        "generate_audio": False,
        # Do not silently rewrite scientifically specific prompts at the provider.
        "auto_fix": False,
        # Keep the provider's documented default safety posture.
        "safety_tolerance": "4",
    }


def _seedance25_args(prompt: str, duration: int) -> dict:
    return {
        "prompt": prompt,
        "duration": str(max(4, min(30, int(duration)))),
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "generate_audio": False,
    }


def _grok15_args(prompt: str, duration: int) -> dict:
    return {
        "prompt": prompt,
        "duration": max(1, int(duration)),
        "resolution": "720p",
        "aspect_ratio": "9:16",
    }


# price_per_second_usd is a conservative budget-gate estimate, not accounting.
# None means the public page did not expose a figure we are willing to encode;
# such a model cannot run unless --allow-unknown-cost is explicitly supplied.
MODEL_SPECS = {
    "ltx_legacy": {
        "model": "fal-ai/ltx-video",
        "family": "LTX legacy",
        "version": "production-baseline",
        "arguments": lambda prompt, duration: {"prompt": prompt},
        "price_per_second_usd": None,
        "capabilities": ("text_to_video", "legacy_production_baseline"),
        "note": "exact current production endpoint; retained only as a legacy baseline",
    },
    "ltx23_fast": {
        "model": "fal-ai/ltx-2.3/text-to-video/fast",
        "family": "LTX",
        "version": "2.3 Fast",
        "arguments": _ltx23_args,
        "price_per_second_usd": 0.06,  # conservative vs conflicting lower table figure
        "capabilities": ("text_to_video", "vertical", "1080p", "native_audio_optional"),
        "note": "current LTX 2.3 Fast, 1080p vertical, audio disabled for visual isolation",
    },
    "h3_max": {
        "model": "minimax/h3-max/text-to-video",
        "family": "MiniMax H3",
        "version": "H3 Max",
        "arguments": _h3_args,
        "price_per_second_usd": 0.08,  # regular price; ignores temporary launch discount
        "capabilities": ("text_to_video", "vertical", "768p", "fast_inference"),
        "note": "H3 Max; regular-price guard used even during temporary promotion",
    },
    "wan30": {
        "model": "alibaba/wan-3.0/text-to-video",
        "family": "Wan",
        "version": "3.0",
        "arguments": _wan30_args,
        "price_per_second_usd": 0.10,
        "capabilities": ("text_to_video", "vertical", "720p", "native_audio_optional"),
        "note": "Wan 3.0 720p vertical; prompt expansion on, audio off",
    },
    "kling3_standard": {
        "model": "fal-ai/kling-video/v3/standard/text-to-video",
        "family": "Kling",
        "version": "3 Standard",
        "arguments": _kling3_args,
        "price_per_second_usd": 0.084,
        "capabilities": ("text_to_video", "vertical", "multi_shot", "native_audio_optional"),
        "note": "Kling 3 Standard, audio disabled; hard negative prompt for science review",
    },
    "veo31_fast": {
        "model": "fal-ai/veo3.1/fast",
        "family": "Veo",
        "version": "3.1 Fast",
        "arguments": _veo31_args,
        "price_per_second_usd": 0.10,
        "capabilities": ("text_to_video", "vertical", "720p", "1080p", "native_audio_optional"),
        "note": "Veo 3.1 Fast 720p; provider auto-fix disabled to protect prompt semantics",
    },
    "seedance25": {
        "model": "bytedance/seedance-2.5/text-to-video",
        "family": "Seedance",
        "version": "2.5",
        "arguments": _seedance25_args,
        "price_per_second_usd": 0.473,
        "capabilities": ("text_to_video", "vertical", "720p", "up_to_30s", "native_audio_optional"),
        "note": "Seedance 2.5; expensive lane kept explicit rather than silently defaulted",
    },
    "grok15": {
        "model": "xai/grok-imagine-video/v1.5/text-to-video",
        "family": "Grok Imagine",
        "version": "1.5",
        "arguments": _grok15_args,
        "price_per_second_usd": None,
        "capabilities": ("text_to_video", "vertical", "720p", "1080p"),
        "note": "Grok Imagine 1.5; public endpoint verified but cost left unknown/fail-closed",
    },
}

# Broad enough to compare different model families, cheap enough that the default
# plan is not dominated by the expensive Seedance lane. Seedance remains one
# explicit flag away when a human wants a frontier comparison.
DEFAULT_MODELS = "ltx23_fast,h3_max,wan30,kling3_standard,veo31_fast"


def parse_models(raw: str) -> list[str]:
    out: list[str] = []
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


def effective_duration(alias: str, requested_duration: int) -> int:
    args = MODEL_SPECS[alias]["arguments"]("probe", requested_duration)
    raw = args.get("duration", requested_duration)
    if isinstance(raw, str):
        raw = raw.rstrip("sS")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(requested_duration)


def estimate_run_cost(models: list[str], duration: int) -> tuple[float, tuple[str, ...]]:
    total = 0.0
    unknown: list[str] = []
    for alias in models:
        spec = MODEL_SPECS[alias]
        rate = spec["price_per_second_usd"]
        if rate is None:
            unknown.append(alias)
            continue
        total += float(rate) * effective_duration(alias, duration)
    # Round UP to cents so the guard never understates a fractional-cent total.
    total = math.ceil(total * 100.0) / 100.0
    return total, tuple(unknown)


def enforce_budget(
    models: list[str],
    duration: int,
    max_budget_usd: float,
    *,
    allow_unknown_cost: bool = False,
) -> float:
    if max_budget_usd < 0:
        raise ValueError("max budget must be non-negative")
    estimated, unknown = estimate_run_cost(models, duration)
    if unknown and not allow_unknown_cost:
        raise ValueError(
            "unknown-price model(s) selected: "
            + ", ".join(unknown)
            + "; remove them or explicitly pass --allow-unknown-cost"
        )
    if estimated > float(max_budget_usd) + 1e-9:
        raise ValueError(
            f"estimated known cost ${estimated:.2f} exceeds hard budget ${max_budget_usd:.2f}"
        )
    return estimated


def extract_video_url(result):
    """Support common fal response shapes without model-specific parsing."""
    if not isinstance(result, dict):
        return None
    video = result.get("video")
    if isinstance(video, dict) and video.get("url"):
        return video["url"]
    videos = result.get("videos")
    if isinstance(videos, list) and videos and isinstance(videos[0], dict):
        return videos[0].get("url")
    data = result.get("data")
    if isinstance(data, dict):
        return extract_video_url(data)
    return None


def download(url: str, dest: str):
    req = urllib.request.Request(url, headers={"User-Agent": "content-render/video-model-lab"})
    with urllib.request.urlopen(req, timeout=120) as response, open(dest, "wb") as f:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def normalize_vertical(src: str, dest: str, duration: int):
    """Create a consistent muted 1080x1920 review copy; keep originals too."""
    subprocess.run([
        "ffmpeg", "-y", "-i", src, "-t", str(duration),
        "-vf",
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1",
        "-an", "-r", "30", "-pix_fmt", "yuv420p", "-c:v", "libx264", dest,
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def review_stub(alias: str) -> dict:
    return {
        "alias": alias,
        "semantic_match_0_10": None,
        "scientific_plausibility_0_10": None,
        "subject_integrity_0_10": None,
        "motion_quality_0_10": None,
        "continuity_0_10": None,
        "text_hallucination": None,
        "anatomy_or_object_errors": [],
        "would_use_in_final": None,
        "human_notes": "",
        "vision_qa": None,
    }


def plan(models: list[str], prompt: str, duration: int, max_budget_usd: float, allow_unknown_cost: bool) -> dict:
    estimated, unknown = estimate_run_cost(models, duration)
    enforce_budget(
        models,
        duration,
        max_budget_usd,
        allow_unknown_cost=allow_unknown_cost,
    )
    return {
        "verified_on": VERIFIED_ON,
        "prompt": prompt,
        "requested_duration": duration,
        "max_budget_usd": max_budget_usd,
        "estimated_known_cost_usd": estimated,
        "unknown_cost_models": list(unknown),
        "models": [
            {
                "alias": alias,
                "model": MODEL_SPECS[alias]["model"],
                "family": MODEL_SPECS[alias]["family"],
                "version": MODEL_SPECS[alias]["version"],
                "effective_duration": effective_duration(alias, duration),
                "price_per_second_usd_guard": MODEL_SPECS[alias]["price_per_second_usd"],
                "capabilities": list(MODEL_SPECS[alias]["capabilities"]),
                "arguments": MODEL_SPECS[alias]["arguments"](prompt, duration),
                "note": MODEL_SPECS[alias]["note"],
            }
            for alias in models
        ],
    }


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
        raise RuntimeError(
            f"{alias} returned no video URL; keys="
            f"{list(result) if isinstance(result, dict) else type(result)}"
        )

    raw = os.path.join(out_dir, f"{alias}_original.mp4")
    review = os.path.join(out_dir, f"{alias}_review_9x16.mp4")
    download(url, raw)
    normalize_vertical(raw, review, effective_duration(alias, duration))
    return {
        "alias": alias,
        "model": spec["model"],
        "family": spec["family"],
        "version": spec["version"],
        "verified_on": VERIFIED_ON,
        "seconds": round(elapsed, 2),
        "estimated_cost_usd": (
            round(spec["price_per_second_usd"] * effective_duration(alias, duration), 4)
            if spec["price_per_second_usd"] is not None else None
        ),
        "arguments": args,
        "capabilities": list(spec["capabilities"]),
        "source_url": url,
        "original": os.path.basename(raw),
        "review": os.path.basename(review),
        "bytes": os.path.getsize(raw),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--duration", type=int, default=6)
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--out-dir", default="video_bakeoff")
    ap.add_argument(
        "--max-budget-usd",
        type=float,
        required=True,
        help="hard known-cost ceiling checked before any provider call",
    )
    ap.add_argument(
        "--allow-unknown-cost",
        action="store_true",
        help="explicitly permit models whose public price is not encoded",
    )
    ap.add_argument(
        "--plan-only",
        action="store_true",
        help="validate model IDs/request shapes/budget and write plan JSON; zero paid calls",
    )
    args = ap.parse_args()

    models = parse_models(args.models)
    approved_plan = plan(
        models,
        args.prompt,
        args.duration,
        args.max_budget_usd,
        args.allow_unknown_cost,
    )
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "plan.json"), "w") as f:
        json.dump(approved_plan, f, indent=2)
    with open(os.path.join(args.out_dir, "prompt.txt"), "w") as f:
        f.write(args.prompt + "\n")
    with open(os.path.join(args.out_dir, "review_template.json"), "w") as f:
        json.dump([review_stub(alias) for alias in models], f, indent=2)

    if args.plan_only:
        print(json.dumps(approved_plan, indent=2))
        print("PLAN ONLY: zero provider calls made.")
        return

    if not os.environ.get("FAL_KEY") and os.environ.get("FAL_API_KEY"):
        os.environ["FAL_KEY"] = os.environ["FAL_API_KEY"]
    if not os.environ.get("FAL_KEY"):
        raise SystemExit("FAL_KEY or FAL_API_KEY is required for a paid run")

    report = {
        **approved_plan,
        "results": [],
        "errors": [],
    }

    for alias in models:
        print(f"\n=== {alias}: {MODEL_SPECS[alias]['model']} ===")
        try:
            meta = run_one(alias, args.prompt, args.duration, args.out_dir)
            report["results"].append(meta)
            print(json.dumps(meta, indent=2))
        except Exception as exc:
            err = {
                "alias": alias,
                "model": MODEL_SPECS[alias]["model"],
                "error": f"{type(exc).__name__}: {exc}",
            }
            report["errors"].append(err)
            print("ERROR:", json.dumps(err))

    with open(os.path.join(args.out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)

    if not report["results"]:
        raise SystemExit("all requested models failed")
    print(
        f"\nCompleted {len(report['results'])}/{len(models)} models. "
        "Review *_review_9x16.mp4 and fill review_template.json."
    )


if __name__ == "__main__":
    main()
