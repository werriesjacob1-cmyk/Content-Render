#!/usr/bin/env python3
"""Actual rendered-asset lineage for private Content Render certification.

Candidate provenance is not enough: this file records what each rendered scene
actually used after the legacy selector/fallbacks made their choices. The
capture helpers are stdlib-only and receive runtime facts from the renderer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class AssetLineageEntry:
    scene_id: str
    scene_index: int
    visual_intent: str
    subject_id: str
    subject: str
    renderer_kind: str
    output_file: str
    duration_s: float
    selected_asset_ids: tuple[str, ...] = ()
    selected_source_urls: tuple[str, ...] = ()
    source_family: str = ""
    source_claim_ids: tuple[str, ...] = ()
    continuity_with: tuple[str, ...] = ()
    injection_asset_id: str = ""
    injection_selected: bool = False
    science_motion_kind: str = ""
    attributable: bool = True
    notes: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.scene_id:
            errors.append("scene_id required")
        if self.scene_index < 1:
            errors.append("scene_index must be >=1")
        if not self.visual_intent or not self.subject_id:
            errors.append("visual contract identity missing")
        if self.duration_s < 0:
            errors.append("duration_s must be >=0")
        if self.output_file and self.duration_s > 0 and not self.renderer_kind:
            errors.append("rendered scene lacks renderer_kind")
        return errors


def write_lineage(entries: Sequence[AssetLineageEntry], path: str | Path) -> dict[str, Any]:
    errors: list[str] = []
    for e in entries:
        errors.extend(f"{e.scene_id}: {x}" for x in e.validate())
    if errors:
        raise ValueError("; ".join(errors))
    payload = {
        "schema": "content-render-final-asset-lineage-v1",
        "scene_count": len(entries),
        "attributable_scene_count": sum(1 for e in entries if e.attributable),
        "all_rendered_scenes_attributable": all(e.attributable for e in entries if e.duration_s > 0),
        "scenes": [asdict(e) for e in entries],
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def classify_legacy_artifacts(work_dir: str | Path, scene_index: int) -> tuple[str, tuple[str, ...]]:
    """Classify fallback path from concrete files created for this scene."""
    work = Path(work_dir)
    names = tuple(sorted(p.name for p in work.glob(f"s{scene_index}_*") if p.is_file()))
    if any(name.endswith("_ai.png") for name in names):
        return "generated_still", names
    if any(name.endswith("_img.jpg") or name.endswith("_img.png") for name in names):
        return "archival_still", names
    if any("_hero.mp4" in name or "_fal.mp4" in name for name in names):
        return "generated_video", names
    if any("_raw.mp4" in name for name in names):
        return "legacy_real_video", names
    if names:
        return "legacy_compositor", names
    return "unattributed", names


def bible_scene(bible: Mapping[str, Any], scene_id: str) -> Mapping[str, Any]:
    for row in bible.get("scenes") or []:
        if isinstance(row, Mapping) and str(row.get("scene_id") or "") == str(scene_id):
            return row
    return {}
