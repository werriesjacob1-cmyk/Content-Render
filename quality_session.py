#!/usr/bin/env python3
"""End-to-end planning session for Content Render's modular quality stack.

This is the handoff object between Writer V2.1 and the media/render stack. It
makes zero provider calls. A future pipeline entrypoint can persist this plan and
advance it as real assets/QA results arrive.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping

import generated_media_controller as GMC
import quality_runtime as QR
import quality_stack as Q
import story_packet as SP
import visual_director as VD


@dataclass(frozen=True)
class SceneSessionPlan:
    scene_id: str
    source_claim_ids: tuple[str, ...]
    traceability_bound: bool
    traceability_error: str
    visual_execution: Mapping[str, Any]
    generated_strategy: Mapping[str, Any] | None


@dataclass(frozen=True)
class QualitySessionPlan:
    topic_id: str
    grounding_mode: str
    writer_claim_payload: Mapping[str, Any]
    scenes: tuple[SceneSessionPlan, ...]
    blockers: tuple[str, ...]
    provider_calls_made: int = 0
    publishing_enabled: bool = False
    human_review_required: bool = True

    @property
    def traceability_ready(self) -> bool:
        return not any("traceability" in b.lower() or "claim" in b.lower() for b in self.blockers)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _manifest_scene_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for i, raw in enumerate(manifest.get("scenes") or [], 1):
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("id") or raw.get("scene_id") or i)
        out[sid] = raw
    return out


def _claim_refs(raw_scene: Mapping[str, Any]) -> tuple[str, ...]:
    refs = raw_scene.get("source_claim_ids")
    if not isinstance(refs, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(x).strip() for x in refs if str(x).strip()))


def build_session_plan(
    manifest: Mapping[str, Any],
    story: SP.StoryPacket,
    policy: Q.QualityPolicy | None = None,
    generated_config: GMC.GeneratedMediaConfig | None = None,
) -> QualitySessionPlan:
    """Create the complete zero-call session plan and surface traceability gaps."""
    p = policy or Q.QualityPolicy()
    story_errors = story.validate()
    if story_errors:
        raise ValueError("invalid StoryPacket: " + "; ".join(story_errors))

    visual = VD.build_visual_plan(manifest)
    visual_errors = visual.validate()
    if visual_errors:
        raise ValueError("invalid VisualPlan: " + "; ".join(visual_errors))

    raw_map = _manifest_scene_map(manifest)
    blockers: list[str] = []
    scene_plans: list[SceneSessionPlan] = []

    for spec in visual.scenes:
        raw = raw_map.get(spec.scene_id, {})
        refs = _claim_refs(raw)
        bound = False
        trace_error = ""
        if refs:
            try:
                story.require_claim_ids(refs)
                bound = True
            except ValueError as exc:
                trace_error = str(exc)
                blockers.append(f"scene {spec.scene_id} traceability: {trace_error}")
        else:
            trace_error = "no source_claim_ids supplied by writer"
            blockers.append(f"scene {spec.scene_id} traceability: {trace_error}")

        visual_execution = QR.plan_scene(spec, p)
        generated_strategy = None
        if generated_config is not None:
            generated_strategy = GMC.build_strategy(spec, generated_config, p)

        scene_plans.append(SceneSessionPlan(
            scene_id=spec.scene_id,
            source_claim_ids=refs,
            traceability_bound=bound,
            traceability_error=trace_error,
            visual_execution=visual_execution,
            generated_strategy=generated_strategy,
        ))

    if not story.claims:
        blockers.append("story packet contains no usable claims")

    return QualitySessionPlan(
        topic_id=story.topic_id,
        grounding_mode=story.grounding_mode,
        writer_claim_payload=SP.writer_payload(story),
        scenes=tuple(scene_plans),
        blockers=tuple(blockers),
        provider_calls_made=0,
        publishing_enabled=False,
        human_review_required=True,
    )


def render_preflight(plan: QualitySessionPlan) -> tuple[bool, tuple[str, ...]]:
    """Pre-render gate: no unbound factual story may enter the new quality path."""
    reasons = list(plan.blockers)
    if plan.provider_calls_made != 0:
        reasons.append("session planner unexpectedly recorded provider calls")
    if plan.publishing_enabled:
        reasons.append("quality session must never enable publishing")
    if not plan.scenes:
        reasons.append("session has no scenes")
    if any(not s.traceability_bound for s in plan.scenes):
        reasons.append("one or more scenes are not bound to source claim IDs")
    return (not reasons, tuple(dict.fromkeys(reasons)))
