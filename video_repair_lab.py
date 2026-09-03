#!/usr/bin/env python3
"""Private, budget-guarded video repair lab.

Purpose: repair a mostly-good science clip instead of discarding its useful
motion/continuity and regenerating from scratch.

This module does NOT auto-edit production media.  It creates explicit repair
plans and can run manually selected FAL repair endpoints.  Every repaired result
is marked vision_verified=false / production_eligible=false until an independent
visual QA pass accepts it.

Verified 2026-09-03:
- LTX 2.3 retake-video: segment-level retake, $0.10/sec
- Luma Ray 3.2 video-to-video: adherence controls, 5s/10s, cost depends on res
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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


class RepairKind(str, Enum):
    WRONG_SUBJECT = "wrong_subject"
    BAKED_TEXT = "baked_text"
    BACKGROUND = "background"
    ANATOMY_OR_OBJECT = "anatomy_or_object"
    STYLE_HARMONIZATION = "style_harmonization"
    CONTINUITY = "continuity"
    OTHER = "other"


@dataclass(frozen=True)
class RepairSpec:
    source_video_url: str
    kind: RepairKind
    instruction: str
    preserve: tuple[str, ...]
    must_not_change: tuple[str, ...] = ()
    start_time_s: float = 0.0
    duration_s: float = 5.0

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.source_video_url.startswith(("https://", "http://")):
            errors.append("source_video_url must be HTTP(S)")
        if not self.instruction.strip():
            errors.append("repair instruction required")
        if not self.preserve or any(not x.strip() for x in self.preserve):
            errors.append("at least one preserve requirement is mandatory")
        if not math.isfinite(float(self.start_time_s)) or self.start_time_s < 0:
            errors.append("start_time_s must be finite and >= 0")
        if not math.isfinite(float(self.duration_s)) or not (1 <= self.duration_s <= 10):
            errors.append("duration_s must be 1..10")
        return errors


def build_repair_prompt(spec: RepairSpec) -> str:
    errors = spec.validate()
    if errors:
        raise ValueError("; ".join(errors))
    preserve = "; ".join(spec.preserve)
    forbidden = "; ".join(spec.must_not_change) or "everything not named in the requested repair"
    return (
        "VIDEO REPAIR ONLY. Preserve the source clip's useful composition and motion. "
        f"Problem type: {spec.kind.value}. Requested repair: {spec.instruction.strip()} "
        f"MUST PRESERVE: {preserve}. MUST NOT CHANGE: {forbidden}. "
        "Do not add text, labels, logos, new objects, new species, decorative scientific "
        "details, or extra events unless the repair instruction explicitly requires them. "
        "If the requested correction cannot be made while preserving these constraints, "
        "prefer minimal change rather than creative reinterpretation."
    )


def _ltx_args(spec: RepairSpec) -> dict:
    return {
        "video_url": spec.source_video_url,
        "prompt": build_repair_prompt(spec),
        "start_time": round(float(spec.start_time_s), 3),
        "duration": round(float(spec.duration_s), 3),
        # Content Render mixes its own narration later. Never let visual repair
        # silently replace source audio.
        "retake_mode": "replace_video",
    }


def _luma_args(spec: RepairSpec) -> dict:
    # Ray 3.2 accepts only 5s/10s. Choose the smallest supported duration that
    # fully covers the requested repair window.
    duration = "5s" if spec.duration_s <= 5 else "10s"
    return {
        "prompt": build_repair_prompt(spec),
        "video_url": spec.source_video_url,
        "resolution": "540p",
        "duration": duration,
        # Maximum preservation bias for a repair lab.
        "edit_strength": "adhere_1",
        "hdr": False,
        "exr_export": False,
    }


MODEL_SPECS = {
    "ltx23_retake": {
        "model": "fal-ai/ltx-2.3/retake-video",
        "family": "LTX",
        "version": "2.3 Retake",
        "arguments": _ltx_args,
        "cost": lambda spec: 0.10 * float(spec.duration_s),
        "note": "segment-level visual-only retake; source audio preserved externally",
    },
    "luma_ray32": {
        "model": "luma/agent/ray/v3.2/video-to-video",
        "family": "Luma Ray",
        "version": "3.2",
        "arguments": _luma_args,
        # Verified 540p: $0.72 / 5s, $1.44 / 10s.
        "cost": lambda spec: 0.72 if spec.duration_s <= 5 else 1.44,
        "note": "whole 5s/10s source-aware edit with strongest adherence setting",
    },
}

DEFAULT_MODELS = "ltx23_retake,luma_ray32"


def parse_models(raw: str) -> list[str]:
    out: list[str] = []
    for piece in (raw or "").split(","):
        alias = piece.strip()
        if not alias:
            continue
        if alias not in MODEL_SPECS:
            raise ValueError(
                f"unknown repair model {alias!r}; choose from {sorted(MODEL_SPECS)}"
            )
        if alias not in out:
            out.append(alias)
    if not out:
        raise ValueError("no repair models selected")
    return out


def estimate_cost(models: list[str], spec: RepairSpec) -> float:
    errors = spec.validate()
    if errors:
        raise ValueError("; ".join(errors))
    total = sum(float(MODEL_SPECS[a]["cost"](spec)) for a in models)
    return math.ceil(total * 100) / 100


def enforce_budget(models: list[str], spec: RepairSpec, max_budget_usd: float) -> float:
    budget = float(max_budget_usd)
    if not math.isfinite(budget) or budget < 0:
        raise ValueError("max budget must be finite and non-negative")
    estimate = estimate_cost(models, spec)
    if estimate > budget + 1e-12:
        raise ValueError(
            f"estimated repair cost ${estimate:.2f} exceeds hard budget ${budget:.2f}"
        )
    return estimate


def build_plan(models: list[str], spec: RepairSpec, max_budget_usd: float) -> dict:
    estimate = enforce_budget(models, spec, max_budget_usd)
    return {
        "verified_on": VERIFIED_ON,
        "repair": {
            "kind": spec.kind.value,
            "source_video_url": spec.source_video_url,
            "instruction": spec.instruction,
            "preserve": list(spec.preserve),
            "must_not_change": list(spec.must_not_change),
            "start_time_s": spec.start_time_s,
            "duration_s": spec.duration_s,
        },
        "repair_prompt": build_repair_prompt(spec),
        "estimated_cost_usd": estimate,
        "max_budget_usd": float(max_budget_usd),
        "models": [
            {
                "alias": alias,
                "model": MODEL_SPECS[alias]["model"],
                "family": MODEL_SPECS[alias]["family"],
                "version": MODEL_SPECS[alias]["version"],
                "estimated_cost_usd": round(
                    float(MODEL_SPECS[alias]["cost"](spec)), 4
                ),
                "arguments": MODEL_SPECS[alias]["arguments"](spec),
                "note": MODEL_SPECS[alias]["note"],
            }
            for alias in models
        ],
        "vision_verified": False,
        "production_eligible": False,
        "reason": "every repair must pass independent visual QA and human review",
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


def _ext(url: str) -> str:
    suffix = os.path.splitext(urlparse(url).path)[1].lower()
    return suffix if suffix in {".mp4", ".mov", ".webm", ".m4v"} else ".mp4"


def download(url: str, dest: str) -> None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "content-render/video-repair-lab"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def review_stub(alias: str) -> dict:
    return {
        "alias": alias,
        "requested_problem_fixed": None,
        "preservation_0_10": None,
        "scientific_integrity_0_10": None,
        "new_artifacts": [],
        "new_text_or_labels": [],
        "continuity_damage": [],
        "vision_verified": False,
        "vision_qa": None,
        "better_than_source": None,
        "would_use_in_final": None,
        "human_notes": "",
    }


def run_one(alias: str, spec: RepairSpec, out_dir: str) -> dict:
    if fal_client is None:
        raise RuntimeError("fal-client is not installed")
    row = MODEL_SPECS[alias]
    args = row["arguments"](spec)
    started = time.time()
    result = fal_client.subscribe(row["model"], arguments=args, with_logs=True)
    elapsed = time.time() - started
    url = extract_video_url(result)
    if not url:
        raise RuntimeError("repair endpoint returned no video URL")
    dest = os.path.join(out_dir, alias + _ext(url))
    download(url, dest)
    if not os.path.exists(dest) or os.path.getsize(dest) < 1000:
        raise RuntimeError("repair download was empty")
    return {
        "alias": alias,
        "model": row["model"],
        "family": row["family"],
        "version": row["version"],
        "seconds": round(elapsed, 2),
        "estimated_cost_usd": round(float(row["cost"](spec)), 4),
        "arguments": args,
        "source_url": url,
        "file": os.path.basename(dest),
        "bytes": os.path.getsize(dest),
        "vision_verified": False,
        "production_eligible": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-video-url", required=True)
    ap.add_argument("--kind", choices=[x.value for x in RepairKind], required=True)
    ap.add_argument("--instruction", required=True)
    ap.add_argument("--preserve", action="append", required=True)
    ap.add_argument("--must-not-change", action="append", default=[])
    ap.add_argument("--start-time", type=float, default=0.0)
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--max-budget-usd", type=float, required=True)
    ap.add_argument("--out-dir", default="video_repair")
    ap.add_argument("--plan-only", action="store_true")
    args = ap.parse_args()

    spec = RepairSpec(
        source_video_url=args.source_video_url,
        kind=RepairKind(args.kind),
        instruction=args.instruction,
        preserve=tuple(args.preserve),
        must_not_change=tuple(args.must_not_change),
        start_time_s=args.start_time,
        duration_s=args.duration,
    )
    models = parse_models(args.models)
    plan = build_plan(models, spec, args.max_budget_usd)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    with open(
        os.path.join(args.out_dir, "review_template.json"), "w", encoding="utf-8"
    ) as f:
        json.dump([review_stub(a) for a in models], f, indent=2)

    if args.plan_only:
        print(json.dumps(plan, indent=2))
        print("PLAN ONLY: zero repair calls made.")
        return

    if not os.environ.get("FAL_KEY") and os.environ.get("FAL_API_KEY"):
        os.environ["FAL_KEY"] = os.environ["FAL_API_KEY"]
    if not os.environ.get("FAL_KEY"):
        raise SystemExit("FAL_KEY or FAL_API_KEY is required for a paid repair run")

    report = {**plan, "results": [], "errors": []}
    for alias in models:
        try:
            result = run_one(alias, spec, args.out_dir)
            report["results"].append(result)
            print(json.dumps(result, indent=2))
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
        raise SystemExit("all selected repair models failed")
    print("Repairs generated. NONE is production-eligible until re-QA and human review.")


if __name__ == "__main__":
    main()
