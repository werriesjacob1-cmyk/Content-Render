#!/usr/bin/env python3
"""End-to-end planning session for Content Render's modular quality stack.

This is the handoff object between Writer V2.1 and the media/render stack. It
makes zero provider calls. A future pipeline entrypoint can persist this plan and
advance it as real assets/QA results arrive.

Writer V2.1 owns the actual factual-support decision. This module preserves and
validates its evidence references without reimplementing its hard/soft/semantic
traceability checker. A line with no claim IDs is therefore allowed only when the
caller supplies `upstream_traceability_passed=True`, meaning V2.1 already judged
that line connective/editorial rather than uncited factual content.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping, Sequence

import generated_media_controller as GMC
import quality_runtime as QR
import quality_stack as Q
import story_packet as SP
import visual_director as VD


@dataclass(frozen=True)
class EvidenceBinding:
    label: str
    source_claim_ids: tuple[str, ...]
    traceability_bound: bool
    traceability_error: str = ""


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
    hook_binding: EvidenceBinding
    scenes: tuple[SceneSessionPlan, ...]
    payoff_binding: EvidenceBinding
    upstream_traceability_passed: bool | None
    blockers: tuple[str, ...]
    provider_calls_made: int = 0
    publishing_enabled: bool = False
    human_review_required: bool = True

    @property
    def traceability_ready(self) -> bool:
        if self.upstream_traceability_passed is not True:
            return False
        if not self.hook_binding.traceability_bound or not self.payoff_binding.traceability_bound:
            return False
        return all(s.traceability_bound for s in self.scenes)

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


def _claim_refs(raw: Mapping[str, Any], field: str = "source_claim_ids") -> tuple[str, ...]:
    refs = raw.get(field)
    if not isinstance(refs, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(x).strip() for x in refs if str(x).strip()))


def _bind_claims(
    label: str,
    refs: Sequence[str],
    story: SP.StoryPacket,
    upstream_traceability_passed: bool | None,
) -> EvidenceBinding:
    refs = tuple(dict.fromkeys(str(x).strip() for x in refs if str(x).strip()))
    if refs:
        try:
            story.require_claim_ids(refs)
            return EvidenceBinding(label, refs, True, "")
        except ValueError as exc:
            return EvidenceBinding(label, refs, False, str(exc))
    if upstream_traceability_passed is True:
        # Writer V2.1's own checker permits an empty citation list only when
        # the line has no hard factual payload and its semantic critic does
        # not find an unsupported addition. Do not second-guess that here.
        return EvidenceBinding(label, (), True, "upstream V2.1 certified connective/editorial line")
    if upstream_traceability_passed is False:
        return EvidenceBinding(label, (), False, "upstream Writer V2.1 traceability did not pass")
    return EvidenceBinding(label, (), False, "no source_claim_ids and no upstream V2.1 traceability verdict supplied")


def build_session_plan(
    manifest: Mapping[str, Any],
    story: SP.StoryPacket,
    policy: Q.QualityPolicy | None = None,
    generated_config: GMC.GeneratedMediaConfig | None = None,
    *,
    upstream_traceability_passed: bool | None = None,
) -> QualitySessionPlan:
    """Create the complete zero-call session plan and surface evidence gaps.

    `upstream_traceability_passed` should be True only for a manifest returned
    as accepted by Writer V2.1's bounded loop: its candidate selector accepts
    only zero HARD mechanical+semantic violations, no validate() error, and a
    real quality score. We preserve that decision rather than recreating its
    word-level checker in this integration layer.
    """
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

    hook_binding = _bind_claims(
        "hook",
        _claim_refs(manifest, "hook_source_claim_ids"),
        story,
        upstream_traceability_passed,
    )
    if not hook_binding.traceability_bound:
        blockers.append(f"hook traceability: {hook_binding.traceability_error}")

    for spec in visual.scenes:
        raw = raw_map.get(spec.scene_id, {})
        refs = _claim_refs(raw)
        binding = _bind_claims(
            f"scene {spec.scene_id}", refs, story, upstream_traceability_passed
        )
        if not binding.traceability_bound:
            blockers.append(f"scene {spec.scene_id} traceability: {binding.traceability_error}")

        visual_execution = QR.plan_scene(spec, p)
        generated_strategy = None
        if generated_config is not None:
            generated_strategy = GMC.build_strategy(spec, generated_config, p)

        scene_plans.append(SceneSessionPlan(
            scene_id=spec.scene_id,
            source_claim_ids=refs,
            traceability_bound=binding.traceability_bound,
            traceability_error=binding.traceability_error,
            visual_execution=visual_execution,
            generated_strategy=generated_strategy,
        ))

    payoff_binding = _bind_claims(
        "payoff",
        _claim_refs(manifest, "payoff_source_claim_ids"),
        story,
        upstream_traceability_passed,
    )
    if not payoff_binding.traceability_bound:
        blockers.append(f"payoff traceability: {payoff_binding.traceability_error}")

    if upstream_traceability_passed is not True:
        blockers.append("Writer V2.1 accepted traceability verdict is required for strict new-stack preflight")
    if not story.claims:
        blockers.append("story packet contains no usable claims")

    return QualitySessionPlan(
        topic_id=story.topic_id,
        grounding_mode=story.grounding_mode,
        writer_claim_payload=SP.writer_payload(story),
        hook_binding=hook_binding,
        scenes=tuple(scene_plans),
        payoff_binding=payoff_binding,
        upstream_traceability_passed=upstream_traceability_passed,
        blockers=tuple(dict.fromkeys(blockers)),
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
    if not plan.traceability_ready:
        reasons.append("hook/scenes/payoff are not fully covered by accepted Writer V2.1 traceability")
    return (not reasons, tuple(dict.fromkeys(reasons)))
