#!/usr/bin/env python3
"""Private still-first science visual model lab.

Why this exists:
    Direct text-to-video is difficult to control for scientific subjects.
    A stronger path is often:
        generate still -> vision QA -> animate verified reference

This harness compares current still models on the SAME science prompt.  It never
promotes a generated image into production: every review record starts with
vision_verified=false.

Safety:
- --plan-only makes zero provider calls and is the workflow default.
- --max-budget-usd is checked before any call.
- safety checkers remain enabled where exposed.
- model-side prompt expansion is disabled where possible so scientific intent is
  not silently rewritten during a fair bakeoff.
- no automatic "winner"; human + vision review remain required.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.request
from urllib.parse import urlparse

try:
    import fal_client
except Exception:
    fal_client = None


VERIFIED_ON = "2026-09-03"


def _seedream_args(prompt: str) -> dict:
    return {
        "prompt": prompt,
        "image_size": "portrait_16_9",
        "num_images": 1,
        "max_images": 1,
        "enable_safety_checker": True,
    }


def _gpt_image_args(prompt: str) -> dict:
    return {
        "prompt": prompt,
        "image_size": "portrait_16_9",
        "quality": "medium",
        "num_images": 1,
        "output_format": "png",
    }


def _nano_args(prompt: str) -> dict:
    return {
        "prompt": prompt,
        "num_images": 1,
        "aspect_ratio": "9:16",
        "output_format": "png",
        "safety_tolerance": "4",
        "resolution": "2K",
        "limit_generations": True,
        "enable_web_search": False,
    }


def _qwen_args(prompt: str) -> dict:
    return {
        "prompt": prompt,
        "negative_prompt": (
            "watermark, logo, unreadable text, gibberish labels, deformed anatomy, "
            "wrong species, fantasy anatomy, low quality"
        ),
        "image_size": {"width": 1152, "height": 2048},
        "enable_prompt_expansion": False,
        "enable_safety_checker": True,
        "num_images": 1,
        "output_format": "png",
    }


def _ideogram_args(prompt: str) -> dict:
    return {
        "prompt": prompt,
        "expansion_model": "None",
        "image_size": "portrait_16_9",
        "rendering_speed": "QUALITY",
        "acceleration": "none",
        "num_images": 1,
        "enable_safety_checker": True,
        "output_format": "png",
    }


# Conservative per-request guard estimates for the fixed requests above.
# These estimates exist to PREVENT accidental spend; report.json records them as
# estimates, not accounting truth.
MODEL_SPECS = {
    "seedream5_pro": {
        "model": "bytedance/seedream/v5/pro/text-to-image",
        "family": "Seedream",
        "version": "5.0 Pro",
        "arguments": _seedream_args,
        "estimated_cost_usd": 0.0675,
        "note": "flagship tier; portrait preset; source page <=1536^2 price guard",
    },
    "gpt_image2": {
        "model": "openai/gpt-image-2",
        "family": "GPT Image",
        "version": "2",
        "arguments": _gpt_image_args,
        # Conservative allowance relative to published medium-quality canonical
        # sizes; exact provider billing is token/size dependent.
        "estimated_cost_usd": 0.06,
        "note": "medium quality to keep science-reference experiments inexpensive",
    },
    "nano_banana2": {
        "model": "fal-ai/nano-banana-2",
        "family": "Nano Banana",
        "version": "2",
        "arguments": _nano_args,
        # $0.08 at 1K, 1.5x at 2K.
        "estimated_cost_usd": 0.12,
        "note": "2K vertical; web search disabled; generation limit=1",
    },
    "qwen_image3": {
        "model": "alibaba/qwen-image-3/text-to-image",
        "family": "Qwen Image",
        "version": "3",
        "arguments": _qwen_args,
        "estimated_cost_usd": 0.075,
        "note": "2K-class custom vertical; prompt expansion disabled",
    },
    "ideogram4": {
        "model": "ideogram/v4",
        "family": "Ideogram",
        "version": "4",
        "arguments": _ideogram_args,
        # Conservative guard for portrait output at QUALITY. Public rate is
        # $0.025/MP; this leaves headroom around the preset's actual pixel count.
        "estimated_cost_usd": 0.03,
        "note": "QUALITY lane; expansion disabled for exact same-prompt comparison",
    },
}

DEFAULT_MODELS = "seedream5_pro,gpt_image2,nano_banana2,qwen_image3,ideogram4"


def parse_models(raw: str) -> list[str]:
    out: list[str] = []
    for piece in (raw or "").split(","):
        alias = piece.strip()
        if not alias:
            continue
        if alias not in MODEL_SPECS:
            raise ValueError(
                f"unknown model alias {alias!r}; choose from {sorted(MODEL_SPECS)}"
            )
        if alias not in out:
            out.append(alias)
    if not out:
        raise ValueError("no models selected")
    return out


def estimate_cost(models: list[str]) -> float:
    total = sum(float(MODEL_SPECS[a]["estimated_cost_usd"]) for a in models)
    return math.ceil(total * 10000) / 10000


def enforce_budget(models: list[str], max_budget_usd: float) -> float:
    if not math.isfinite(float(max_budget_usd)) or float(max_budget_usd) < 0:
        raise ValueError("max budget must be finite and non-negative")
    estimate = estimate_cost(models)
    if estimate > float(max_budget_usd) + 1e-12:
        raise ValueError(
            f"estimated still-lab cost ${estimate:.4f} exceeds hard budget "
            f"${float(max_budget_usd):.4f}"
        )
    return estimate


def build_plan(models: list[str], prompt: str, max_budget_usd: float) -> dict:
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    if len(prompt) > 5000:
        raise ValueError("prompt exceeds the strictest selected model limit")
    estimate = enforce_budget(models, max_budget_usd)
    return {
        "verified_on": VERIFIED_ON,
        "prompt": prompt,
        "estimated_cost_usd": estimate,
        "max_budget_usd": float(max_budget_usd),
        "models": [
            {
                "alias": alias,
                "model": MODEL_SPECS[alias]["model"],
                "family": MODEL_SPECS[alias]["family"],
                "version": MODEL_SPECS[alias]["version"],
                "estimated_cost_usd": MODEL_SPECS[alias]["estimated_cost_usd"],
                "arguments": MODEL_SPECS[alias]["arguments"](prompt),
                "note": MODEL_SPECS[alias]["note"],
            }
            for alias in models
        ],
        "production_eligible": False,
        "reason": "generated stills require independent vision QA before use",
    }


def extract_image_url(result) -> str | None:
    if not isinstance(result, dict):
        return None
    images = result.get("images")
    if isinstance(images, list) and images and isinstance(images[0], dict):
        url = images[0].get("url")
        return str(url) if url else None
    data = result.get("data")
    if isinstance(data, dict):
        return extract_image_url(data)
    return None


def _extension(url: str) -> str:
    suffix = os.path.splitext(urlparse(url).path)[1].lower()
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp"} else ".img"


def download(url: str, dest: str) -> None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "content-render/still-first-lab"}
    )
    with urllib.request.urlopen(req, timeout=90) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def review_stub(alias: str) -> dict:
    return {
        "alias": alias,
        "semantic_match_0_10": None,
        "scientific_plausibility_0_10": None,
        "subject_integrity_0_10": None,
        "composition_for_vertical_video_0_10": None,
        "fine_detail_0_10": None,
        "text_or_label_artifacts": [],
        "anatomy_or_object_errors": [],
        "animatable_as_reference": None,
        "vision_verified": False,
        "vision_qa": None,
        "would_use_in_final": None,
        "human_notes": "",
    }


def run_one(alias: str, prompt: str, out_dir: str) -> dict:
    if fal_client is None:
        raise RuntimeError("fal-client is not installed")
    spec = MODEL_SPECS[alias]
    args = spec["arguments"](prompt)
    started = time.time()
    result = fal_client.subscribe(spec["model"], arguments=args, with_logs=True)
    elapsed = time.time() - started
    url = extract_image_url(result)
    if not url:
        raise RuntimeError(
            f"{alias} returned no image URL; keys="
            f"{list(result) if isinstance(result, dict) else type(result)}"
        )
    dest = os.path.join(out_dir, alias + _extension(url))
    download(url, dest)
    if not os.path.exists(dest) or os.path.getsize(dest) < 1000:
        raise RuntimeError(f"{alias} image download was empty")
    return {
        "alias": alias,
        "model": spec["model"],
        "family": spec["family"],
        "version": spec["version"],
        "seconds": round(elapsed, 2),
        "estimated_cost_usd": spec["estimated_cost_usd"],
        "arguments": args,
        "source_url": url,
        "file": os.path.basename(dest),
        "bytes": os.path.getsize(dest),
        "vision_verified": False,
        "production_eligible": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--out-dir", default="still_bakeoff")
    ap.add_argument("--max-budget-usd", type=float, required=True)
    ap.add_argument(
        "--plan-only",
        action="store_true",
        help="zero-spend validation of endpoints/request shapes/budget",
    )
    args = ap.parse_args()

    models = parse_models(args.models)
    plan = build_plan(models, args.prompt, args.max_budget_usd)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    with open(os.path.join(args.out_dir, "prompt.txt"), "w", encoding="utf-8") as f:
        f.write(args.prompt.strip() + "\n")
    with open(
        os.path.join(args.out_dir, "review_template.json"), "w", encoding="utf-8"
    ) as f:
        json.dump([review_stub(a) for a in models], f, indent=2)

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
        print(f"\n=== {alias}: {MODEL_SPECS[alias]['model']} ===")
        try:
            row = run_one(alias, args.prompt, args.out_dir)
            report["results"].append(row)
            print(json.dumps(row, indent=2))
        except Exception as exc:
            err = {
                "alias": alias,
                "model": MODEL_SPECS[alias]["model"],
                "error": f"{type(exc).__name__}: {exc}",
            }
            report["errors"].append(err)
            print("ERROR:", json.dumps(err))

    with open(os.path.join(args.out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    if not report["results"]:
        raise SystemExit("all selected still models failed")
    print(
        f"\nGenerated {len(report['results'])}/{len(models)} candidates. "
        "NONE is production-eligible until independent vision QA passes."
    )


if __name__ == "__main__":
    main()
