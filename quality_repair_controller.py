#!/usr/bin/env python3
"""Bounded QA -> scene repair -> reassembly -> local re-QA controller.

The controller deliberately separates *authorization to edit* from the repair
provider. ``quality_postrender_review`` may diagnose a target; this module
validates that target, preserves unaffected scene files byte-for-byte, accepts
only explicitly supplied replacement scene files, reassembles the video, and
reruns local audio/structural QA. It never calls FAL/Higgsfield/another provider
on its own.

This makes the repair loop executable without silently authorizing paid edits.
A future provider adapter can create a replacement scene, then hand that file to
this exact preservation/reassembly gate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Callable, Mapping, Sequence

import quality_audio_qa as AQA

MAX_REPAIR_TARGETS = 2
MAX_AFFECTED_SCENES_PER_TARGET = 3


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class RepairTask:
    target_index: int
    category: str
    severity: str
    affected_scene_ids: tuple[str, ...]
    start_s: float
    end_s: float
    recommended_action: str
    preserve: tuple[str, ...]

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.severity not in {"major", "critical"}:
            errors.append("only major/critical targets are executable")
        if not self.affected_scene_ids:
            errors.append("repair target must map to concrete scene IDs")
        if len(self.affected_scene_ids) > MAX_AFFECTED_SCENES_PER_TARGET:
            errors.append("repair target spans too many scenes")
        if self.end_s <= self.start_s:
            errors.append("repair window must have positive duration")
        joined = " ".join(self.preserve).lower()
        if "writer" not in joined or "claim" not in joined:
            errors.append("repair target lacks Writer/claim preservation contract")
        return errors


def tasks_from_plan(plan: Mapping[str, Any]) -> list[RepairTask]:
    raw_targets = plan.get("targets") or []
    if len(raw_targets) > MAX_REPAIR_TARGETS:
        raise ValueError(f"repair plan has {len(raw_targets)} targets > hard cap {MAX_REPAIR_TARGETS}")
    tasks: list[RepairTask] = []
    for idx, row in enumerate(raw_targets, 1):
        if not isinstance(row, Mapping):
            raise ValueError("repair target must be an object")
        task = RepairTask(
            target_index=idx,
            category=str(row.get("category") or "other"),
            severity=str(row.get("severity") or "").lower(),
            affected_scene_ids=tuple(str(x) for x in (row.get("affected_scene_ids") or []) if str(x)),
            start_s=float(row.get("start_s") or 0.0),
            end_s=float(row.get("end_s") or 0.0),
            recommended_action=str(row.get("recommended_action") or "").strip(),
            preserve=tuple(str(x) for x in (row.get("preserve") or []) if str(x).strip()),
        )
        errors = task.validate()
        if errors:
            raise ValueError(f"target {idx}: " + "; ".join(errors))
        tasks.append(task)
    return tasks


def affected_scene_ids(tasks: Sequence[RepairTask]) -> set[str]:
    return {sid for task in tasks for sid in task.affected_scene_ids}


def execute_replacements(
    *,
    plan: Mapping[str, Any],
    scene_files: Mapping[str, str | Path],
    replacements: Mapping[str, str | Path],
    output_scene_dir: str | Path,
    output_video: str | Path,
    assemble: Callable[[Sequence[str], str], None],
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply pre-authorized replacement files while proving good scenes unchanged."""
    tasks = tasks_from_plan(plan)
    target_ids = affected_scene_ids(tasks)
    if not target_ids:
        raise ValueError("repair plan contains no executable scene targets")
    if set(replacements) != target_ids:
        raise ValueError(
            f"replacement IDs {sorted(replacements)} must exactly equal targeted IDs {sorted(target_ids)}"
        )
    if not target_ids.issubset(set(scene_files)):
        raise ValueError("repair plan references scene absent from rendered scene map")

    out_dir = Path(output_scene_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {sid: sha256(path) for sid, path in scene_files.items()}
    ordered_ids = list(scene_files)
    new_paths: dict[str, str] = {}
    for sid in ordered_ids:
        src = Path(replacements[sid] if sid in target_ids else scene_files[sid])
        if not src.is_file():
            raise ValueError(f"scene source missing for {sid}: {src}")
        dest = out_dir / f"scene_{sid}{src.suffix or '.mp4'}"
        shutil.copy2(src, dest)
        new_paths[sid] = str(dest)

    after = {sid: sha256(path) for sid, path in new_paths.items()}
    preservation = {
        sid: {"before": before[sid], "after": after[sid], "unchanged": before[sid] == after[sid]}
        for sid in ordered_ids if sid not in target_ids
    }
    if not all(x["unchanged"] for x in preservation.values()):
        raise RuntimeError("repair mutated a non-target scene")
    changed = {sid: before[sid] != after[sid] for sid in target_ids}
    if not all(changed.values()):
        raise RuntimeError("one or more targeted replacement scenes are byte-identical to source")

    assemble([new_paths[sid] for sid in ordered_ids], str(output_video))
    out_video = Path(output_video)
    if not out_video.is_file() or out_video.stat().st_size < 1000:
        raise RuntimeError("reassembly did not produce a usable video")

    evidence: dict[str, Any] = {
        "schema": "content-render-bounded-repair-execution-v1",
        "tasks": [asdict(t) for t in tasks],
        "targeted_scene_ids": sorted(target_ids),
        "unaffected_scene_preservation": preservation,
        "targeted_scene_changed": changed,
        "output_video": str(out_video),
        "output_sha256": sha256(out_video),
        "provider_calls_made": 0,
        "provider_repair_authorized": False,
        "re_qa": {},
    }
    if manifest_path is not None:
        report = AQA.review(str(out_video), str(manifest_path))
        evidence["re_qa"]["audio"] = report
        evidence["re_qa"]["audio_mechanical_pass"] = report.get("mechanical_pass") is True
    return evidence


def write_evidence(evidence: Mapping[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(evidence), indent=2, sort_keys=True), encoding="utf-8")
