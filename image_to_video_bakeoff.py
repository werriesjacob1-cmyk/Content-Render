#!/usr/bin/env python3
"""Budget-guarded image-to-video lab for verified science stills.

This fills the controlled-visual path:
    generated/real still -> independent vision QA -> image-to-video -> vision QA

It is not a production selector. Models must be compared and explicitly promoted
before any one becomes a production default. Every result starts unverified.

Endpoint/pricing checks performed 2026-09-03 against current fal model pages:
- Kling 3 Standard I2V: fal-ai/kling-video/v3/standard/image-to-video, $0.084/s audio off
- Grok Imagine I2V: xai/grok-imagine-video/image-to-video, $0.07/s at 720p + $0.002 image input
- Seedance 2.5 I2V: bytedance/seedance-2.5/image-to-video, ~$0.473/s at 720p
"""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_UP
import json
import os
import time
import urllib.request

try:
    import fal_client
except Exception:
    fal_client = None

VERIFIED_ON = "2026-09-03"


def _kling_args(image_url: str, prompt: str, duration: int) -> dict:
    return {
        "start_image_url": image_url,
        "prompt": prompt,
        "duration": str(max(3, min(15, int(duration)))),
        "generate_audio": False,
        "shot_type": "customize",
        "negative_prompt": "blur, distort, low quality, text, labels, watermark, deformed anatomy, subject mutation",
    }


def _grok_args(image_url: str, prompt: str, duration: int) -> dict:
    return {
        "image_url": image_url,
        "prompt": prompt,
        "duration": max(1, min(15, int(duration))),
        "resolution": "720p",
    }


def _seedance_args(image_url: str, prompt: str, duration: int) -> dict:
    return {
        "image_url": image_url,
        "prompt": prompt,
        "duration": str(max(2, min(30, int(duration)))),
        "resolution": "720p",
        "aspect_ratio": "9:16",
    }


MODEL_SPECS = {
    "kling3_standard": {
        "model": "fal-ai/kling-video/v3/standard/image-to-video",
        "family": "Kling",
        "version": "3 Standard",
        "price_per_second_usd": Decimal("0.084"),
        "fixed_cost_usd": Decimal("0"),
        "arguments": _kling_args,
        "note": "cheap controllable lane; native audio explicitly disabled",
    },
    "grok_imagine": {
        "model": "xai/grok-imagine-video/image-to-video",
        "family": "Grok Imagine",
        "version": "current",
        "price_per_second_usd": Decimal("0.07"),
        "fixed_cost_usd": Decimal("0.002"),
        "arguments": _grok_args,
        "note": "cheap 720p lane; output audio is ignored by Content Render",
    },
    "seedance25": {
        "model": "bytedance/seedance-2.5/image-to-video",
        "family": "Seedance",
        "version": "2.5",
        "price_per_second_usd": Decimal("0.473"),
        "fixed_cost_usd": Decimal("0"),
        "arguments": _seedance_args,
        "note": "expensive quality challenger; not a default spend path",
    },
}

DEFAULT_MODELS = "kling3_standard,grok_imagine"


def parse_models(raw: str) -> list[str]:
    out: list[str] = []
    for piece in str(raw or "").split(","):
        alias = piece.strip()
        if not alias:
            continue
        if alias not in MODEL_SPECS:
            raise ValueError(f"unknown I2V alias {alias!r}; choose from {sorted(MODEL_SPECS)}")
        if alias not in out:
            out.append(alias)
    if not out:
        raise ValueError("no image-to-video models selected")
    return out


def estimate_cost(models: list[str], duration: int) -> Decimal:
    d = Decimal(str(max(1, int(duration))))
    total = sum(
        MODEL_SPECS[a]["price_per_second_usd"] * d + MODEL_SPECS[a]["fixed_cost_usd"]
        for a in models
    )
    return total.quantize(Decimal("0.0001"), rounding=ROUND_UP)


def enforce_budget(models: list[str], duration: int, max_budget_usd: str | float | Decimal) -> Decimal:
    ceiling = Decimal(str(max_budget_usd))
    if not ceiling.is_finite() or ceiling < 0:
        raise ValueError("max budget must be finite and non-negative")
    estimate = estimate_cost(models, duration)
    if estimate > ceiling:
        raise ValueError(f"estimated I2V cost ${estimate} exceeds hard budget ${ceiling}")
    return estimate


def build_plan(models: list[str], image_url: str, prompt: str, duration: int, max_budget_usd) -> dict:
    image_url = str(image_url or "").strip()
    prompt = str(prompt or "").strip()
    if not image_url.startswith(("https://", "http://")):
        raise ValueError("I2V requires a hosted image URL")
    if not prompt:
        raise ValueError("motion prompt is required")
    if len(prompt) > 2500:
        raise ValueError("motion prompt exceeds conservative shared limit")
    estimate = enforce_budget(models, duration, max_budget_usd)
    return {
        "verified_on": VERIFIED_ON,
        "image_url": image_url,
        "prompt": prompt,
        "duration": int(duration),
        "estimated_cost_usd": str(estimate),
        "max_budget_usd": str(Decimal(str(max_budget_usd))),
        "models": [
            {
                "alias": alias,
                "model": MODEL_SPECS[alias]["model"],
                "family": MODEL_SPECS[alias]["family"],
                "version": MODEL_SPECS[alias]["version"],
                "arguments": MODEL_SPECS[alias]["arguments"](image_url, prompt, duration),
                "note": MODEL_SPECS[alias]["note"],
            }
            for alias in models
        ],
        "input_still_must_be_vision_verified": True,
        "output_video_vision_verified": False,
        "production_eligible": False,
    }


def extract_video_url(result) -> str | None:
    if not isinstance(result, dict):
        return None
    video = result.get("video")
    if isinstance(video, dict) and video.get("url"):
        return str(video["url"])
    data = result.get("data")
    if isinstance(data, dict):
        return extract_video_url(data)
    return None


def _download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "content-render/i2v-lab"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def run_one(alias: str, image_url: str, prompt: str, duration: int, out_dir: str) -> dict:
    if fal_client is None:
        raise RuntimeError("fal-client is not installed")
    spec = MODEL_SPECS[alias]
    args = spec["arguments"](image_url, prompt, duration)
    started = time.time()
    result = fal_client.subscribe(spec["model"], arguments=args, with_logs=True)
    elapsed = time.time() - started
    url = extract_video_url(result)
    if not url:
        raise RuntimeError(f"{alias} returned no video URL")
    dest = os.path.join(out_dir, f"{alias}_i2v.mp4")
    _download(url, dest)
    if not os.path.exists(dest) or os.path.getsize(dest) < 1000:
        raise RuntimeError(f"{alias} I2V download was empty")
    return {
        "alias": alias,
        "model": spec["model"],
        "seconds": round(elapsed, 2),
        "source_url": url,
        "file": os.path.basename(dest),
        "bytes": os.path.getsize(dest),
        "vision_verified": False,
        "production_eligible": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image-url", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--duration", type=int, default=6)
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--max-budget-usd", required=True)
    ap.add_argument("--out-dir", default="image_to_video_bakeoff")
    ap.add_argument("--plan-only", action="store_true")
    args = ap.parse_args()

    models = parse_models(args.models)
    plan = build_plan(models, args.image_url, args.prompt, args.duration, args.max_budget_usd)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "plan.json"), "w") as f:
        json.dump(plan, f, indent=2)
    if args.plan_only:
        print(json.dumps(plan, indent=2))
        print("PLAN ONLY: zero provider calls made.")
        return

    if not os.environ.get("FAL_KEY") and os.environ.get("FAL_API_KEY"):
        os.environ["FAL_KEY"] = os.environ["FAL_API_KEY"]
    if not os.environ.get("FAL_KEY"):
        raise SystemExit("FAL_KEY or FAL_API_KEY is required for a paid run")

    report = {**plan, "results": [], "errors": []}
    for alias in models:
        try:
            report["results"].append(run_one(alias, args.image_url, args.prompt, args.duration, args.out_dir))
        except Exception as exc:
            report["errors"].append({"alias": alias, "error": f"{type(exc).__name__}: {exc}"})
    with open(os.path.join(args.out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    if not report["results"]:
        raise SystemExit("all selected image-to-video models failed")
    print("Generated I2V candidates. NONE is production-eligible until output vision QA passes.")


if __name__ == "__main__":
    main()
