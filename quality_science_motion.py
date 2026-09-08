#!/usr/bin/env python3
"""Evidence-bound deterministic science-motion lane for private certification.

This module turns a *small, explicit subset* of Writer V2.1 treatments into
purpose-built graphics without another model call. It never infers a process or
quantity from arbitrary narration. Every visual step/value is copied from
already-accepted spoken lines carrying sealed Writer claim IDs.

Eligible production treatments:
- ONE_OBJECT_JOURNEY: path begins -> transformation -> obstacle -> destination
- HIDDEN_MECHANISM: beneath surface -> mechanism -> consequence
- INSIDE_THE_SYSTEM: internal component -> connection -> critical interaction

SCALE_REVEAL is deliberately NOT in that list. See
``SCALE_REVEAL_PRODUCTION_ROUTING_ENABLED`` below: sealed provenance proves each
ratio is real, but nothing currently proves two ratios measure comparable
quantities, so the production planner refuses to chart them.

The resulting graphic is deterministic FFmpeg output, makes zero network/AI
calls, and is used only when a higher-priority authentic NASA/PubChem asset did
not already resolve the target scene.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Mapping, Sequence

import science_motion as SM


_TREATMENT_FLOW = {
    "ONE_OBJECT_JOURNEY": {
        "step_indexes": (2, 3, 4, 5),
        "target_index": 5,
        "title": "THE JOURNEY",
    },
    "HIDDEN_MECHANISM": {
        "step_indexes": (3, 4, 5),
        "target_index": 5,
        "title": "WHAT'S HAPPENING",
    },
    "INSIDE_THE_SYSTEM": {
        "step_indexes": (3, 4, 5),
        "target_index": 5,
        "title": "INSIDE THE SYSTEM",
    },
}

_RATIO_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s+(times)\b", re.I)

# Fail-closed switch for the SCALE_REVEAL lane. Matching sealed "N times"
# ratios proves each number was actually said and cited -- it does NOT prove the
# two ratios measure comparable quantities. "4 times faster" and "100 times
# denser" are both dimensionless, both sealed, and putting them on one axis
# would assert a comparison the evidence never makes. Until claims carry an
# explicit machine-readable comparability contract (a shared quantity/dimension
# the planner can check rather than infer), no deterministic comparison graphic
# is emitted. The planner below is retained, unreferenced by production, so that
# contract can be built against working machinery instead of from scratch.
SCALE_REVEAL_PRODUCTION_ROUTING_ENABLED = False


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
    """Make a compact display label using only words from the accepted line."""
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


def _ratio_tail_label(text: str, match: re.Match[str], max_chars: int = 32) -> str:
    """Use the accepted words immediately after ``N times`` as the bar label.

    For the eclipse seed this yields ``WIDER THAN ITSELF`` and ``FARTHER AWAY``
    rather than repeating the whole sentence above a 400-times display value.
    The label remains literal accepted narration; no synonym or summary is added.
    """
    tail = str(text or "")[match.end():].strip(" \t\r\n,.;:!?—–-")
    if not tail:
        return _short_accepted_label(text, max_chars=max_chars)
    return _short_accepted_label(tail, max_chars=max_chars)


def _inert_plan_dimensionless_scale(
    manifest: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, ScienceMotionPlan]:
    """NOT PRODUCTION. Retained machinery for a future comparability contract.

    Nothing in production calls this. It plans a SCALE_COMPARE from accepted
    dimensionless ``N times`` ratios, which is safe only when the ratios happen
    to describe comparable quantities -- something this function cannot verify
    and never claimed to. It refuses unlike-unit measurements and unsealed
    claims, but two sealed ratios of unrelated quantities would still be
    charted together, which is exactly why ``plan_manifest`` no longer routes
    here. See ``SCALE_REVEAL_PRODUCTION_ROUTING_ENABLED``.
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
        label = _ratio_tail_label(voice, match)
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)
        selected.append((
            _scene_id(scene, idx),
            label,
            float(match.group(1)),
            match.group(0).upper(),
            refs,
        ))
        if len(selected) >= 4:
            break

    if len(selected) < 2:
        return {}

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
    """Return at most one deterministic science graphic for this manifest."""
    treatment = str(manifest.get("treatment") or "").strip()
    allowed = {str(x).strip() for x in allowed_claim_ids if str(x).strip()}
    if treatment == "SCALE_REVEAL":
        # Fail closed: no deterministic comparison graphic without explicit
        # proof of semantic comparability. The scene keeps its normal
        # authentic-science/stock routing instead.
        return {}

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
        duration=4.0,
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
