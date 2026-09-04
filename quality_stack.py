#!/usr/bin/env python3
"""Content Render Quality Stack integration orchestrator.

This module is the glue between the isolated quality experiments. It is designed
for staged integration: plan first, execute only when a caller explicitly enables
network/paid lanes, and never publish from here.

The stack keeps responsibilities separate:
research -> writer -> visual contract -> authentic media / deterministic visuals
-> verified generated media only when needed -> voice/sound -> repair -> final QA.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
import importlib.util
from typing import Any, Mapping, Sequence

import visual_director as VD


class Stage(str, Enum):
    RESEARCH = "research"
    WRITING = "writing"
    VISUAL_PLANNING = "visual_planning"
    AUTHENTIC_MEDIA = "authentic_media"
    GENERATED_MEDIA = "generated_media"
    VISION_QA = "vision_qa"
    MOTION = "motion"
    VOICE = "voice"
    SOUND = "sound"
    REPAIR = "repair"
    FINAL_QA = "final_qa"


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    stage: Stage
    module: str
    requires_network: bool = False
    may_cost_money: bool = False
    generated_media: bool = False
    experimental: bool = False
    note: str = ""

    def module_present(self) -> bool:
        if self.module == "existing_main":
            return True
        return importlib.util.find_spec(self.module) is not None


@dataclass(frozen=True)
class QualityPolicy:
    """Runtime permission boundary. Safe defaults make a zero-spend plan only."""
    plan_only: bool = True
    allow_network: bool = False
    allow_paid: bool = False
    allow_generated_visuals: bool = False
    enable_voice_experiments: bool = False
    enable_sound_design: bool = False
    enable_repair: bool = False
    enable_final_qa_provider_calls: bool = False

    def permits(self, tool: ToolDescriptor) -> bool:
        if not tool.module_present():
            return False
        if self.plan_only:
            return not tool.requires_network and not tool.may_cost_money
        if tool.requires_network and not self.allow_network:
            return False
        if tool.may_cost_money and not self.allow_paid:
            return False
        if tool.generated_media and not self.allow_generated_visuals:
            return False
        if tool.stage == Stage.VOICE and tool.experimental and not self.enable_voice_experiments:
            return False
        if tool.stage == Stage.SOUND and not self.enable_sound_design:
            return False
        if tool.stage == Stage.REPAIR and not self.enable_repair:
            return False
        if tool.stage == Stage.FINAL_QA and tool.requires_network and not self.enable_final_qa_provider_calls:
            return False
        return True


TOOLS: tuple[ToolDescriptor, ...] = (
    ToolDescriptor("you_grounded_research", Stage.RESEARCH, "research_grounding", True, True, note="source-backed You Answer adapter; exact cited excerpts required"),
    ToolDescriptor("compound_mini_research", Stage.RESEARCH, "research_grounding", True, True, experimental=True, note="research/fact-check only until exact claim-source binding is mechanical"),
    ToolDescriptor("writer_v2", Stage.WRITING, "writer_v2", True, True, experimental=True, note="optional slot; Claude V2.1 lands here when approved"),
    ToolDescriptor("visual_director", Stage.VISUAL_PLANNING, "visual_director", note="pure local scene contract and evidence-first routing"),
    ToolDescriptor("nasa_svs", Stage.AUTHENTIC_MEDIA, "scientific_media", True, False, note="NASA Scientific Visualization Studio"),
    ToolDescriptor("pubchem", Stage.AUTHENTIC_MEDIA, "scientific_media", True, False, note="exact small-molecule structures"),
    ToolDescriptor("rcsb_molecular", Stage.AUTHENTIC_MEDIA, "molecular_media", True, False, note="experimental PDB structures with CC0 core data provenance"),
    ToolDescriptor("existing_real_footage", Stage.AUTHENTIC_MEDIA, "existing_main", True, False, note="Pexels/Wikimedia/iNaturalist/Openverse/Internet Archive adapters already in main"),
    ToolDescriptor("science_motion", Stage.MOTION, "science_motion", note="deterministic scale/timeline/process/layer graphics bound to claim IDs"),
    ToolDescriptor("still_model_lab", Stage.GENERATED_MEDIA, "still_model_bakeoff", True, True, True, True, "verified-still-first candidate generation; never auto-promotes"),
    ToolDescriptor("fal_video_lab", Stage.GENERATED_MEDIA, "video_model_bakeoff", True, True, True, True, "current FAL video candidates with hard budget guard"),
    ToolDescriptor("qwen_asset_vision", Stage.VISION_QA, "vision_gateway", True, True, experimental=True, note="Qwen 3.8 independent still/video verification"),
    ToolDescriptor("gemini_asset_vision", Stage.VISION_QA, "existing_main", True, True, experimental=True, note="existing Gemini first-choice asset vision until modular migration"),
    ToolDescriptor("voice_lab", Stage.VOICE, "voice_bakeoff", True, True, experimental=True, note="blind normalized Edge/Orpheus/Cartesia/Eleven comparison"),
    ToolDescriptor("sound_brain", Stage.SOUND, "sound_brain", True, True, experimental=True, note="restrained scene-aware SFX with hard credit ceiling"),
    ToolDescriptor("video_repair", Stage.REPAIR, "video_repair_lab", True, True, True, True, "constrained repair before regeneration; preservation contract required"),
    ToolDescriptor("final_video_qa", Stage.FINAL_QA, "final_video_qa", True, True, experimental=True, note="assembled-video Gemini/Qwen review after local sampling"),
)

TOOL_MAP = {t.name: t for t in TOOLS}

# Visual Director classes -> concrete provider/tool order. Authentic or deterministic
# routes always precede generated media. Generic stock is an actual last resort.
VISUAL_TOOL_ORDER: Mapping[VD.VisualClass, tuple[str, ...]] = {
    VD.VisualClass.AUTHENTIC_SCIENCE_VIDEO: ("nasa_svs", "existing_real_footage"),
    VD.VisualClass.AUTHENTIC_ARCHIVE: ("existing_real_footage",),
    VD.VisualClass.SCIENTIFIC_VISUALIZATION: ("nasa_svs", "science_motion", "existing_real_footage"),
    VD.VisualClass.MOLECULAR_RENDER: ("rcsb_molecular", "pubchem", "science_motion"),
    VD.VisualClass.PROGRAMMATIC_DIAGRAM: ("science_motion",),
    VD.VisualClass.NORMAL_REAL_FOOTAGE: ("existing_real_footage",),
    VD.VisualClass.VERIFIED_GENERATED_STILL: ("still_model_lab", "qwen_asset_vision", "gemini_asset_vision"),
    VD.VisualClass.IMAGE_TO_VIDEO: ("still_model_lab", "qwen_asset_vision", "fal_video_lab", "qwen_asset_vision"),
    VD.VisualClass.GENERATED_VIDEO: ("fal_video_lab", "qwen_asset_vision", "gemini_asset_vision"),
    VD.VisualClass.GENERIC_STOCK: ("existing_real_footage",),
}

PIPELINE_ORDER: tuple[str, ...] = (
    "you_grounded_research",
    "compound_mini_research",
    "writer_v2",
    "visual_director",
    "nasa_svs",
    "pubchem",
    "rcsb_molecular",
    "existing_real_footage",
    "science_motion",
    "still_model_lab",
    "fal_video_lab",
    "qwen_asset_vision",
    "gemini_asset_vision",
    "voice_lab",
    "sound_brain",
    "video_repair",
    "final_video_qa",
)


def integration_status() -> dict[str, dict[str, Any]]:
    return {
        t.name: {
            "stage": t.stage.value,
            "module": t.module,
            "module_present": t.module_present(),
            "requires_network": t.requires_network,
            "may_cost_money": t.may_cost_money,
            "generated_media": t.generated_media,
            "experimental": t.experimental,
            "note": t.note,
        }
        for t in TOOLS
    }


def assert_safe_defaults(policy: QualityPolicy | None = None) -> None:
    p = policy or QualityPolicy()
    if not p.plan_only:
        raise AssertionError("default quality policy must remain plan_only")
    if p.allow_network or p.allow_paid or p.allow_generated_visuals:
        raise AssertionError("default quality policy cannot enable network/paid/generated lanes")
    # This module deliberately has no publishing descriptor at all.
    if any("publish" in t.name or "publer" in t.name or "release" in t.name for t in TOOLS):
        raise AssertionError("publishing must never be part of the quality-stack tool registry")


def tools_for_visual_class(visual_class: VD.VisualClass, policy: QualityPolicy | None = None) -> tuple[dict[str, Any], ...]:
    p = policy or QualityPolicy()
    rows = []
    for name in VISUAL_TOOL_ORDER.get(visual_class, ()):
        t = TOOL_MAP[name]
        rows.append({
            "tool": name,
            "permitted_now": p.permits(t),
            "module_present": t.module_present(),
            "requires_network": t.requires_network,
            "may_cost_money": t.may_cost_money,
            "generated_media": t.generated_media,
        })
    return tuple(rows)


def _scene_routes_to_dict(plan: VD.VisualPlan, policy: QualityPolicy) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in plan.scenes:
        routes = []
        for route in plan.routes.get(spec.scene_id, ()):  # route order set by Visual Director
            routes.append({
                "visual_class": route.visual_class.value,
                "reason": route.reason,
                "provider_sequence": tools_for_visual_class(route.visual_class, policy),
            })
        out.append({
            "scene_id": spec.scene_id,
            "scientific_subject": spec.scientific_subject,
            "must_show": list(spec.must_show),
            "mechanism": spec.mechanism,
            "domain": spec.domain,
            "authenticity_importance": spec.authenticity_importance,
            "routes": routes,
        })
    return out


def build_quality_plan(manifest: Mapping[str, Any], policy: QualityPolicy | None = None) -> dict[str, Any]:
    """Build the end-to-end tool plan without making any provider call."""
    p = policy or QualityPolicy()
    assert_safe_defaults(QualityPolicy())
    visual_plan = VD.build_visual_plan(manifest)
    errors = visual_plan.validate()
    if errors:
        raise ValueError("invalid visual plan: " + "; ".join(errors))
    status = integration_status()
    return {
        "policy": asdict(p),
        "writer_v2_present": status["writer_v2"]["module_present"],
        "all_tools": status,
        "scenes": _scene_routes_to_dict(visual_plan, p),
        "post_visual_stages": [
            {"tool": name, "permitted_now": p.permits(TOOL_MAP[name])}
            for name in ("voice_lab", "sound_brain", "video_repair", "final_video_qa")
        ],
        "publishing_enabled": False,
        "provider_calls_made": 0,
    }


def required_module_names() -> tuple[str, ...]:
    """Modules that should exist on the integration branch before wiring main.py."""
    return tuple(dict.fromkeys(
        t.module for t in TOOLS if t.module not in {"existing_main", "writer_v2"}
    ))
