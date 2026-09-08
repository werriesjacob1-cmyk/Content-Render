#!/usr/bin/env python3
"""Evidence-bound deterministic science-motion lane for private certification.

This module turns a *small, explicit subset* of Writer V2.1 treatments into
purpose-built graphics without another model call. It never infers a process or
quantity from arbitrary narration. Every visual step/value is copied from
already-accepted spoken lines carrying sealed Writer claim IDs.

Eligible v1 treatments:
- ONE_OBJECT_JOURNEY: path begins -> transformation -> obstacle -> destination
- HIDDEN_MECHANISM: beneath surface -> mechanism -> consequence
- INSIDE_THE_SYSTEM: internal component -> connection -> critical interaction
- SCALE_REVEAL: only dimensionless ``N times`` ratios that are safe to compare

The resulting graphic is deterministic FFmpeg output, makes zero network/AI
calls, and is used only when a higher-priority authentic NASA/PubChem asset did
not already resolve the target scene.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Mapping, Sequence

import science_motion as SM


# Zero-based manifest scene indices. Writer V2.1 assembly is canonical:
# 0=hook, 1..6=treatment beats, 7=payoff.
# target_index is deliberately the LAST displayed process step so the graphic
# cannot visually reveal a later beat before narration has reached it.
_TREATMENT_FLOW = {
    "ONE_OBJECT_JOURNEY": {
        "step_indexes": (2, 3, 4, 5),  # beat2 begin, beat3 transform, beat4 obstacle, beat5 destination
        "target_index": 5,
        "title": "THE JOURNEY",
    },
    "HIDDEN_MECHANISM": {
        "step_indexes": (3, 4, 5),     # beat3 beneath surface, beat4 mechanism, beat5 consequence
        "target_index": 5,
        "title": "WHAT'S HAPPENING",
    },
    "INSIDE_THE_SYSTEM": {
        "step_indexes": (3, 4, 5),     # beat3 component, beat4 connection, beat5 critical interaction
        "target_index": 5,
        "title": "INSIDE THE SYSTEM",
    },
}

_RATIO_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s+(times)\b", re.I)


@dataclass(frozen=True)
class ScienceMotionPlan:
    target_scene_id: str
    treatment: str
    source_scene_ids: tuple[str, ...]
    source_claim_ids: tuple[str, ...]
    spec: SM.ScienceMotionSpec

    def provenance(self) -> dict[str, Any]:
        p = SM.provenance_manifest(self.spec)
        p.update({
            "target_scene_id": self.target_scene_id,
            "treatment": self.treatment,
            "source_scene_ids": list(self.source_scene_ids),
            "labels_are_substrings_of_accepted_v21_narration": True,
            "provider_calls": 0,
        })
        return p


def _scene_id(scene: Mapping[str, Any], fallback: int) -> str:
    return str(scene.get("id") or scene.get("scene_id") or fallback)


def _short_accepted_label(text: str, max_chars: int = 38) -> str:
    """Make a compact display label using only words from the accepted line.

    No synonym generation, summarization, or model call is allowed here. We take
    a whole-word prefix so the graphic cannot add a factual proposition that the
    Writer did not already say and semantically certify.
    """
    clean = re.sub(r"[\r\n\t]+", " ", str(text or "")).strip()
    clean = re.sub(r"\s+", " ", clean)
    words = clean.split()
    out: list[str] = []
    length = 0
    for raw in words:
        word = raw.strip("\"'“”‘’.,;:!?()[]{}")
        if not word:
            continue
        add = len(word) + (1 if out else 0)
        if out and length + add > max_chars:
            break
        if not out and len(word) > max_chars:
            word = word[:max_chars]
            add = len(word)
        out.append(word)
        length += add
        if len(out) >= 7:
            break
    return " ".join(out).upper()


def _plan_dimensionless_scale(
    manifest: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, ScienceMotionPlan]:
    """Plan a SCALE_COMPARE only for accepted dimensionless ``N times`` ratios.

    This deliberately refuses ordinary measurements with unlike units: comparing
    10 metres to 3 seconds as bar lengths would be visually false. Dimensionless
    ratios are safe to place on one axis. The eclipse flagship is the motivating
    case: accepted lines contain ``400 times wider`` and ``400 times farther``;
    two equal bars make the cancellation legible without inventing new science.
    """
    scenes = [s for s in (manifest.get("scenes") or []) if isinstance(s, Mapping)]
    if not scenes or not allowed:
        return {}

    selected: list[tuple[str, str, float, str, tuple[str, ...]]] = []
    seen_labels: set[str] = set()
    for idx, scene in enumerate(scenes, 1):
        voice = str(scene.get("voiceover") or "").strip()
        match = _RATIO_RE.search(voice)
        if not match:
            continue
        refs = tuple(dict.fromkeys(
            str(x).strip() for x in (scene.get("source_claim_ids") or []) if str(x).strip()
        ))
        if not refs:
            continue
        unknown = [x for x in refs if x not in allowed]
        if unknown:
            raise ValueError(
                f"science-motion scene {_scene_id(scene, idx)} references unsealed claim IDs: {unknown}"
            )
        label = _short_accepted_label(voice)
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)
        value = float(match.group(1))
        display = match.group(0).upper()
        selected.append((_scene_id(scene, idx), label, value, display, refs))
        if len(selected) >= 4:
            break

    if len(selected) < 2:
        return {}

    # Land on the second ratio reveal: by this point both compared values have
    # already been spoken, so the deterministic graphic cannot spoil a later beat.
    selected = selected[:4]
    target_id = selected[1][0]
    source_scene_ids = tuple(row[0] for row in selected)
    all_refs = tuple(dict.fromkeys(ref for row in selected for ref in row[4]))
    items = tuple(
        SM.ScaleItem(
            label=row[1],
            value=row[2],
            display_value=row[3],
            source_claim_id=row[4][0],
        )
        for row in selected
    )
    spec = SM.ScienceMotionSpec(
        kind=SM.MotionKind.SCALE_COMPARE,
        title="SCALE COMPARISON",
        duration=4.0,
        source_claim_ids=all_refs,
        scale_items=items,
        subtitle="EVIDENCE-BOUND RATIOS",
    )
    errors = spec.validate()
    if errors:
        raise ValueError("invalid deterministic scale-motion plan: " + "; ".join(errors))
    return {
        target_id: ScienceMotionPlan(
            target_scene_id=target_id,
            treatment="SCALE_REVEAL",
            source_scene_ids=source_scene_ids,
            source_claim_ids=all_refs,
            spec=spec,
        )
    }


def plan_manifest(
    manifest: Mapping[str, Any],
    allowed_claim_ids: Sequence[str],
) -> dict[str, ScienceMotionPlan]:
    """Return at most one deterministic science graphic for this manifest.

    The allowed IDs must come from the already-verified sealed Writer evidence
    handoff. Unsupported/unsafe treatment shapes simply produce no deterministic
    motion; the renderer then continues to authentic/legacy visual fallbacks.
    """
    treatment = str(manifest.get("treatment") or "").strip()
    allowed = {str(x).strip() for x in allowed_claim_ids if str(x).strip()}
    if treatment == "SCALE_REVEAL":
        return _plan_dimensionless_scale(manifest, allowed)

    rule = _TREATMENT_FLOW.get(treatment)
    if not rule:
        return {}

    scenes = list(manifest.get("scenes") or [])
    indexes = tuple(rule["step_indexes"])
    target_index = int(rule["target_index"])
    if not scenes or max((*indexes, target_index)) >= len(scenes):
        return {}
    if not allowed:
        return {}

    flow_steps: list[SM.FlowStep] = []
    source_scene_ids: list[str] = []
    all_refs: list[str] = []
    for index in indexes:
        raw = scenes[index]
        if not isinstance(raw, Mapping):
            return {}
        refs = tuple(dict.fromkeys(
            str(x).strip() for x in (raw.get("source_claim_ids") or []) if str(x).strip()
        ))
        if not refs:
            return {}
        unknown = [x for x in refs if x not in allowed]
        if unknown:
            raise ValueError(
                f"science-motion scene {_scene_id(raw, index + 1)} references unsealed claim IDs: {unknown}"
            )
        label = _short_accepted_label(str(raw.get("voiceover") or ""))
        if not label:
            return {}
        flow_steps.append(SM.FlowStep(label=label, source_claim_ids=refs))
        source_scene_ids.append(_scene_id(raw, index + 1))
        all_refs.extend(refs)

    target = scenes[target_index]
    if not isinstance(target, Mapping):
        return {}
    target_id = _scene_id(target, target_index + 1)
    refs = tuple(dict.fromkeys(all_refs))
    spec = SM.ScienceMotionSpec(
        kind=SM.MotionKind.PROCESS_FLOW,
        title=str(rule["title"]),
        duration=4.0,  # replaced with the real spoken-segment duration at render time
        source_claim_ids=refs,
        flow_steps=tuple(flow_steps),
        subtitle="EVIDENCE-BOUND EXPLANATION",
    )
    errors = spec.validate()
    if errors:
        raise ValueError("invalid deterministic science-motion plan: " + "; ".join(errors))

    return {
        target_id: ScienceMotionPlan(
            target_scene_id=target_id,
            treatment=treatment,
            source_scene_ids=tuple(source_scene_ids),
            source_claim_ids=refs,
            spec=spec,
        )
    }


def render_for_scene(
    plan: ScienceMotionPlan,
    legacy_module: Any,
    idx: int,
    seg_mp3: str,
    seg_dur: float,
) -> str:
    """Render one deterministic scene with the exact narration audio attached."""
    duration = float(seg_dur)
    if not (1.0 <= duration <= 20.0):
        raise ValueError(f"science-motion spoken segment duration outside 1..20s: {duration}")
    spec = replace(plan.spec, duration=duration)
    out = legacy_module.os.path.join(legacy_module.WORK, f"s{idx}.mp4")
    return SM.render_science_motion(
        spec,
        out,
        audio_path=seg_mp3,
        font_path=getattr(legacy_module, "FONT", None),
    )
