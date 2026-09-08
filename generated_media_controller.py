#!/usr/bin/env python3
"""Production promotion boundary for generated science visuals.

Model labs enumerate candidates. This controller prevents that from becoming an
implicit production default. An exact alias must be explicitly promoted before it
can appear in a generated-media strategy, and QualityPolicy must separately allow
paid/generated work.

This module only BUILDS plans. It never calls a provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import quality_stack as Q
import visual_director as VD
import still_model_bakeoff as SMB
import image_to_video_bakeoff as I2V
import video_model_bakeoff as VMB


@dataclass(frozen=True)
class PromotedModel:
    lane: str  # still | image_to_video | direct_video
    alias: str
    approved: bool = False
    evidence: str = ""


@dataclass(frozen=True)
class GeneratedMediaConfig:
    still: PromotedModel | None = None
    image_to_video: PromotedModel | None = None
    direct_video: PromotedModel | None = None
    max_still_usd: Decimal = Decimal("0.15")
    max_i2v_usd: Decimal = Decimal("0.60")
    max_direct_video_usd: Decimal = Decimal("0.75")


LANE_REGISTRIES = {
    "still": SMB.MODEL_SPECS,
    "image_to_video": I2V.MODEL_SPECS,
    "direct_video": VMB.MODEL_SPECS,
}


def validate_promotion(model: PromotedModel | None, expected_lane: str) -> list[str]:
    if model is None:
        return []
    errors: list[str] = []
    if model.lane != expected_lane:
        errors.append(f"expected lane {expected_lane}, got {model.lane}")
    registry = LANE_REGISTRIES[expected_lane]
    if model.alias not in registry:
        errors.append(f"unknown {expected_lane} model alias {model.alias!r}")
    if not model.approved:
        errors.append(f"{expected_lane} model {model.alias!r} has not been explicitly promoted")
    if model.approved and not model.evidence.strip():
        errors.append(f"promoted {expected_lane} model {model.alias!r} requires promotion evidence")
    return errors


def validate_config(config: GeneratedMediaConfig) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_promotion(config.still, "still"))
    errors.extend(validate_promotion(config.image_to_video, "image_to_video"))
    errors.extend(validate_promotion(config.direct_video, "direct_video"))
    for name, value in (
        ("max_still_usd", config.max_still_usd),
        ("max_i2v_usd", config.max_i2v_usd),
        ("max_direct_video_usd", config.max_direct_video_usd),
    ):
        if not value.is_finite() or value < 0:
            errors.append(f"{name} must be finite and non-negative")
    return errors


def _science_prompt(spec: VD.SceneSpec) -> str:
    visible = "; ".join(spec.must_show)
    mechanism = f" Mechanism to preserve: {spec.mechanism}." if spec.mechanism else ""
    return (
        f"Literal scientific subject: {spec.scientific_subject}. Must visibly show: {visible}."
        f"{mechanism} Preserve scientifically plausible anatomy/object geometry and identity. "
        "Vertical documentary composition. No text, labels, watermark, fantasy anatomy, or unrelated objects."
    )[:2400]


def _motion_prompt(spec: VD.SceneSpec) -> str:
    mechanism = spec.mechanism or "subtle physically plausible movement of the literal subject"
    return (
        f"Animate only the verified reference image. {mechanism}. Preserve the exact subject identity, "
        "geometry, anatomy, colors, and composition from the first frame. Subtle documentary camera motion. "
        "Do not add labels, text, new objects, fantasy details, or change species/structure."
    )[:2400]


def build_strategy(
    spec: VD.SceneSpec,
    config: GeneratedMediaConfig,
    policy: Q.QualityPolicy,
    *,
    verified_still_url: str = "",
    duration_s: int = 6,
) -> dict[str, Any]:
    """Return the only generated-media lanes allowed for this scene. Zero calls."""
    errors = validate_config(config)
    if errors:
        return {"eligible": False, "blocked_reasons": errors, "steps": [], "provider_calls_made": 0}
    if not policy.permits(Q.TOOL_MAP["qwen_asset_vision"]) and not policy.permits(Q.TOOL_MAP["gemini_asset_vision"]):
        return {
            "eligible": False,
            "blocked_reasons": ["independent vision QA is not permitted/available"],
            "steps": [],
            "provider_calls_made": 0,
        }
    if not policy.allow_generated_visuals or not policy.allow_paid or not policy.allow_network or policy.plan_only:
        return {
            "eligible": False,
            "blocked_reasons": ["QualityPolicy has not explicitly enabled paid generated visuals"],
            "steps": [],
            "provider_calls_made": 0,
        }
    if not spec.generated_visual_allowed:
        return {"eligible": False, "blocked_reasons": ["scene forbids generated visuals"], "steps": [], "provider_calls_made": 0}

    steps: list[dict[str, Any]] = []
    still_prompt = _science_prompt(spec)
    if config.still is not None:
        plan = SMB.build_plan([config.still.alias], still_prompt, float(config.max_still_usd))
        steps.append({
            "lane": "still",
            "tool": "still_model_lab",
            "alias": config.still.alias,
            "plan": plan,
            "next_gate": "independent vision QA; do not animate if it fails",
        })

    if verified_still_url and config.image_to_video is not None:
        plan = I2V.build_plan(
            [config.image_to_video.alias], verified_still_url, _motion_prompt(spec), duration_s, config.max_i2v_usd
        )
        steps.append({
            "lane": "image_to_video",
            "tool": "image_to_video_lab",
            "alias": config.image_to_video.alias,
            "plan": plan,
            "next_gate": "independent video vision QA; animation invalidates still-only approval",
        })

    # Direct T2V is deliberately later than still-first. It is only in the plan
    # when an exact direct-video model has separately earned promotion.
    if config.direct_video is not None:
        models = [config.direct_video.alias]
        plan = VMB.plan(models, still_prompt, duration_s, float(config.max_direct_video_usd), False)
        steps.append({
            "lane": "direct_video_fallback",
            "tool": "fal_video_lab",
            "alias": config.direct_video.alias,
            "plan": plan,
            "next_gate": "independent video vision QA",
        })

    if not steps:
        return {
            "eligible": False,
            "blocked_reasons": ["no exact generated-media model has been promoted for this strategy state"],
            "steps": [],
            "provider_calls_made": 0,
        }
    return {
        "eligible": True,
        "blocked_reasons": [],
        "steps": steps,
        "provider_calls_made": 0,
        "production_eligible": False,
        "reason": "plans only; every generated result still requires independent vision QA",
    }
