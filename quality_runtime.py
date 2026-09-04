#!/usr/bin/env python3
"""Runtime seam for the modular Content Render quality stack.

This is deliberately narrower than main.py. It resolves one SceneSpec through
quality-first provider lanes and returns normalized AssetCandidate objects.

Default QualityPolicy is plan-only, so importing/calling the planner does not
perform network or paid work. Authentic network retrieval occurs only when the
caller explicitly supplies a non-plan policy with allow_network=True. Generated
media is never produced here yet; this module only reports whether escalation is
permitted after authentic/deterministic routes fail.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Sequence

import quality_stack as Q
import visual_director as VD
import scientific_media as SM
import molecular_media as MM
import asset_gateway as AG


@dataclass(frozen=True)
class SceneResolution:
    scene_id: str
    attempted_tools: tuple[str, ...]
    candidates: tuple[VD.AssetCandidate, ...]
    winner: VD.AssetCandidate | None
    delegated_tools: tuple[str, ...]
    generated_escalation_tools: tuple[str, ...]
    errors: tuple[str, ...]
    provider_calls_made: int

    @property
    def resolved(self) -> bool:
        return self.winner is not None


def _query(spec: VD.SceneSpec) -> str:
    parts = list(spec.must_show) + [spec.scientific_subject, spec.mechanism]
    text = " ".join(str(x).strip() for x in parts if str(x).strip())
    return re.sub(r"\s+", " ", text).strip()[:240]


def _route_classes(spec: VD.SceneSpec) -> tuple[VD.VisualClass, ...]:
    return tuple(r.visual_class for r in VD.route_scene(spec))


def _tool_allowed(name: str, policy: Q.QualityPolicy) -> bool:
    tool = Q.TOOL_MAP[name]
    return policy.permits(tool)


def generated_escalation_tools(policy: Q.QualityPolicy) -> tuple[str, ...]:
    """Only expose generation when generation AND independent vision QA can run."""
    vision = [name for name in ("qwen_asset_vision", "gemini_asset_vision") if _tool_allowed(name, policy)]
    if not vision:
        return ()
    out: list[str] = []
    for name in ("still_model_lab", "fal_video_lab"):
        if _tool_allowed(name, policy):
            out.append(name)
    return tuple(out)


def _subject_terms(spec: VD.SceneSpec) -> tuple[str, ...]:
    return tuple(dict.fromkeys([spec.scientific_subject, *spec.must_show]))


def resolve_authentic_scene(
    spec: VD.SceneSpec,
    policy: Q.QualityPolicy | None = None,
    *,
    work_dir: str = ".quality_work",
    used_ids: Sequence[str] = (),
) -> SceneResolution:
    """Try authentic scientific routes for one scene, then rank once.

    `existing_real_footage` is intentionally returned as delegated rather than
    importing main.py and coupling this new stack back into the legacy monolith.
    The future main.py seam can satisfy that lane with its existing Pexels /
    Wikimedia / iNaturalist / Openverse / Archive adapters.
    """
    p = policy or Q.QualityPolicy()
    errors = spec.validate()
    if errors:
        raise ValueError("invalid SceneSpec: " + "; ".join(errors))

    classes = _route_classes(spec)
    query = _query(spec)
    terms = _subject_terms(spec)
    attempted: list[str] = []
    delegated: list[str] = []
    candidates: list[VD.AssetCandidate] = []
    failures: list[str] = []
    calls = 0

    if VD.VisualClass.AUTHENTIC_SCIENCE_VIDEO in classes or VD.VisualClass.SCIENTIFIC_VISUALIZATION in classes:
        if _tool_allowed("nasa_svs", p) and SM.svs_relevant(query):
            attempted.append("nasa_svs")
            try:
                rows = SM.svs_candidates(query, used_ids=used_ids, limit=3)
                calls += 1
                for row in rows:
                    try:
                        candidates.append(AG.nasa_svs_asset(row, terms))
                    except Exception as exc:
                        failures.append(f"nasa normalize: {type(exc).__name__}: {exc}")
            except Exception as exc:
                failures.append(f"nasa_svs: {type(exc).__name__}: {exc}")

    if VD.VisualClass.MOLECULAR_RENDER in classes:
        if _tool_allowed("rcsb_molecular", p):
            attempted.append("rcsb_molecular")
            try:
                hits = MM.search_rcsb(spec.scientific_subject, max_results=3)
                calls += 1
                for hit in hits[:2]:
                    try:
                        entry = MM.fetch_entry(hit.pdb_id)
                        calls += 1
                        # Search score is provider-relative, so don't pretend it
                        # is a calibrated probability; clamp a modest relevance.
                        rel = 0.82 if hit is hits[0] else 0.72
                        candidates.append(AG.rcsb_asset(entry, terms, relevance_score=rel))
                    except Exception as exc:
                        failures.append(f"rcsb {hit.pdb_id}: {type(exc).__name__}: {exc}")
            except Exception as exc:
                failures.append(f"rcsb search: {type(exc).__name__}: {exc}")

        if _tool_allowed("pubchem", p) and SM.pubchem_relevant(query):
            attempted.append("pubchem")
            try:
                os.makedirs(work_dir, exist_ok=True)
                dest = os.path.join(work_dir, f"scene_{spec.scene_id}_pubchem.png")
                resolved = SM.pubchem_image(query, dest)
                calls += 1
                if resolved:
                    candidates.append(AG.pubchem_asset(resolved, dest))
            except Exception as exc:
                failures.append(f"pubchem: {type(exc).__name__}: {exc}")

    # Deterministic science motion requires explicit factual payload + claim IDs,
    # which this scene contract does not fabricate. Report it as delegated to the
    # story/claim layer rather than inventing a chart from narration prose.
    if VD.VisualClass.PROGRAMMATIC_DIAGRAM in classes and _tool_allowed("science_motion", p):
        delegated.append("science_motion")

    if any(c in classes for c in (
        VD.VisualClass.AUTHENTIC_ARCHIVE,
        VD.VisualClass.NORMAL_REAL_FOOTAGE,
        VD.VisualClass.GENERIC_STOCK,
    )):
        # Existing real-footage retrieval is the integration seam back to main.py.
        delegated.append("existing_real_footage")

    winner = AG.choose_for_scene(spec, candidates) if candidates else None
    escalation = () if winner is not None else generated_escalation_tools(p)

    return SceneResolution(
        scene_id=spec.scene_id,
        attempted_tools=tuple(attempted),
        candidates=tuple(candidates),
        winner=winner,
        delegated_tools=tuple(dict.fromkeys(delegated)),
        generated_escalation_tools=escalation,
        errors=tuple(failures),
        provider_calls_made=calls,
    )


def plan_scene(spec: VD.SceneSpec, policy: Q.QualityPolicy | None = None) -> dict:
    """Pure local execution plan: which routes/tools would be eligible, no calls."""
    p = policy or Q.QualityPolicy()
    return {
        "scene_id": spec.scene_id,
        "query": _query(spec),
        "routes": [
            {
                "visual_class": route.visual_class.value,
                "reason": route.reason,
                "tools": list(Q.tools_for_visual_class(route.visual_class, p)),
            }
            for route in VD.route_scene(spec)
        ],
        "generated_escalation_tools": list(generated_escalation_tools(p)),
        "provider_calls_made": 0,
    }
