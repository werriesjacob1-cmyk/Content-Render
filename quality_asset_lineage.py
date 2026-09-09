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
import quality_evidence as QE


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
    # Set only by ``repaired_lineage``. A bounded repair swaps a scene's asset,
    # so provenance written before the repair describes a file the shipped video
    # no longer contains. These two fields make the swap explicit rather than
    # leaving the reader to assume the original lineage still holds.
    repair_replaced: bool = False
    replaced_output_file: str = ""

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
    QE.write_json(p, payload, sort_keys=True)
    return payload


REPAIRED_SCHEMA = "content-render-repaired-asset-lineage-v1"


def phantom_assets(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Scene IDs whose lineage names an output file that is not on disk.

    Lineage is a provenance record for a shipped artifact. An entry pointing at
    a file that does not exist is worse than a missing entry: it reads as
    attribution while attributing nothing. Pure apart from the stat() calls.
    """
    missing: list[str] = []
    for row in payload.get("scenes") or []:
        if not isinstance(row, Mapping):
            continue
        out = str(row.get("output_file") or "")
        if out and not Path(out).is_file():
            missing.append(str(row.get("scene_id") or ""))
    return tuple(missing)


def repaired_lineage(
    base: Mapping[str, Any],
    replacements: Mapping[str, str | Path],
    *,
    repaired_video: str | Path,
    base_video: str | Path,
) -> dict[str, Any]:
    """Lineage for a REPAIRED artifact, derived from the pre-repair lineage.

    The bounded repair replaces the asset behind specific scenes. Without this,
    ``final_asset_lineage.json`` keeps naming the original scene files while the
    shipped video contains different ones -- provenance that is confidently
    wrong, which is the failure mode lineage exists to prevent.

    Fails closed on every way the two records could disagree: a scene the base
    lineage never had, a replacement identical to what it replaces, and an empty
    replacement set (a "repaired" lineage that repaired nothing is a false
    claim). Pure; it does not read or write the video files.
    """
    rows = base.get("scenes")
    if not isinstance(rows, Sequence) or not rows:
        raise ValueError("base lineage has no scenes")
    known = {str(r.get("scene_id") or "") for r in rows if isinstance(r, Mapping)}
    repl = {str(k): str(v) for k, v in dict(replacements).items()}
    if not repl:
        raise ValueError("a repaired lineage requires at least one replaced scene")
    unknown = sorted(set(repl) - known)
    if unknown:
        raise ValueError(
            f"replacement names scene(s) absent from the base lineage: {unknown}"
        )

    out_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("base lineage row is not an object")
        entry = dict(row)
        sid = str(entry.get("scene_id") or "")
        if sid in repl:
            original = str(entry.get("output_file") or "")
            new_file = repl[sid]
            if original and original == new_file:
                raise ValueError(
                    f"scene {sid}: replacement is the same file it replaces; "
                    "that is not a repair"
                )
            entry["replaced_output_file"] = original
            entry["output_file"] = new_file
            entry["repair_replaced"] = True
            note = str(entry.get("notes") or "")
            entry["notes"] = (note + "; " if note else "") + (
                f"asset replaced by bounded repair (was {original or 'unrecorded'})"
            )
        else:
            entry["repair_replaced"] = False
            entry.setdefault("replaced_output_file", "")
        out_rows.append(entry)

    payload = {
        "schema": REPAIRED_SCHEMA,
        "derived_from_schema": str(base.get("schema") or ""),
        "applies_to_video": str(repaired_video),
        "repair_of_video": str(base_video),
        "repaired_scene_ids": sorted(repl),
        "scene_count": len(out_rows),
        "attributable_scene_count": sum(1 for r in out_rows if r.get("attributable")),
        "all_rendered_scenes_attributable": all(
            r.get("attributable") for r in out_rows if float(r.get("duration_s") or 0) > 0
        ),
        "scenes": out_rows,
    }
    return payload


def write_repaired_lineage(
    base: Mapping[str, Any],
    replacements: Mapping[str, str | Path],
    path: str | Path,
    *,
    repaired_video: str | Path,
    base_video: str | Path,
) -> dict[str, Any]:
    payload = repaired_lineage(
        base, replacements, repaired_video=repaired_video, base_video=base_video
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    QE.write_json(p, payload, sort_keys=True)
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
