#!/usr/bin/env python3
"""Mechanical readiness gate before a finished Content Render video reaches human review.

This does not publish. Passing this module means only "eligible to show Jacob for
final human review". Human approval remains mandatory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import visual_director as VD
import sound_brain as SB
import final_video_qa as FQ


@dataclass(frozen=True)
class SceneReviewRecord:
    scene_id: str
    asset: VD.AssetCandidate | None
    source_claim_ids: tuple[str, ...] = ()
    high_factual_load: bool = False


@dataclass(frozen=True)
class VoiceSelection:
    provider: str
    model: str
    voice: str
    production_approved: bool
    evidence: str = ""


@dataclass(frozen=True)
class ReadinessInput:
    script_traceability_passed: bool
    scenes: tuple[SceneReviewRecord, ...]
    voice: VoiceSelection
    sound_plan: SB.SoundPlan | None = None
    sound_max_credits: int | None = None
    final_qa: FQ.FinalQAVerdict | None = None
    repaired_since_final_qa: bool = False


@dataclass(frozen=True)
class ReadinessVerdict:
    eligible_for_human_review: bool
    reasons: tuple[str, ...]
    human_review_required: bool = True
    publish_allowed: bool = False


def evaluate(inp: ReadinessInput) -> ReadinessVerdict:
    reasons: list[str] = []

    if not inp.script_traceability_passed:
        reasons.append("script claim traceability has not passed")
    if not inp.scenes:
        reasons.append("no scene review records supplied")

    seen: set[str] = set()
    for row in inp.scenes:
        sid = str(row.scene_id or "").strip()
        if not sid:
            reasons.append("scene review record missing scene_id")
            continue
        if sid in seen:
            reasons.append(f"duplicate scene review record: {sid}")
        seen.add(sid)
        asset = row.asset
        if asset is None:
            reasons.append(f"scene {sid}: no selected visual asset")
            continue
        if not asset.rights.is_usable():
            reasons.append(f"scene {sid}: selected asset lacks explicit usable rights/provenance")
        if asset.is_generated and not asset.vision_verified:
            reasons.append(f"scene {sid}: generated asset has not passed independent vision QA")
        if row.high_factual_load and not row.source_claim_ids:
            reasons.append(f"scene {sid}: high-factual-load visual lacks source claim IDs")

    if not inp.voice.production_approved:
        reasons.append(
            f"voice {inp.voice.provider}/{inp.voice.model}/{inp.voice.voice} is experimental, not production-approved"
        )

    if inp.sound_plan is not None:
        sound_errors = inp.sound_plan.validate()
        reasons.extend(f"sound: {x}" for x in sound_errors)
        if inp.sound_max_credits is None:
            reasons.append("sound plan supplied without a hard credit ceiling")
        elif not sound_errors:
            try:
                SB.enforce_credit_budget(inp.sound_plan, inp.sound_max_credits)
            except Exception as exc:
                reasons.append(f"sound: {type(exc).__name__}: {exc}")

    if inp.repaired_since_final_qa:
        reasons.append("video changed after final QA; final QA must be rerun")
    elif inp.final_qa is None:
        reasons.append("holistic final-video QA has not run")
    else:
        passed, qa_reasons = FQ.mechanical_gate(inp.final_qa)
        if not passed:
            reasons.extend(f"final QA: {x}" for x in qa_reasons)

    # This contract can never authorize publishing; it only advances a finished
    # artifact into human review.
    return ReadinessVerdict(
        eligible_for_human_review=not reasons,
        reasons=tuple(reasons),
        human_review_required=True,
        publish_allowed=False,
    )


def edge_baseline_selection(voice: str = "en-GB-RyanNeural") -> VoiceSelection:
    """Current production baseline remains approved unless Jacob changes it."""
    return VoiceSelection(
        provider="edge",
        model="edge-tts",
        voice=voice,
        production_approved=True,
        evidence="current production baseline; Voice Lab challengers require explicit promotion",
    )


def experimental_voice(provider: str, model: str, voice: str, evidence: str = "") -> VoiceSelection:
    return VoiceSelection(provider, model, voice, False, evidence)
