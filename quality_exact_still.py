#!/usr/bin/env python3
"""Exact-science still adapter for the private quality render lane.

A scientifically exact structure image should not lose to generic stock merely
because the legacy renderer is video-first. This module adapts ONLY already-
resolved, provenance-bearing scientific stills and renders them through the same
motion/grade/audio scene compositor used by ``main.py``.

Current v1 eligibility is deliberately narrow: exact PubChem structure depictions.
RCSB coordinate records are NOT treated as images; they remain blocked until a
real coordinate-to-visual renderer exists. Generated stills are also excluded;
they belong to the separately promoted + independently vision-verified lane.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import os
import re
from typing import Any

import visual_director as VD


_LOCAL_IMAGE_RE = re.compile(r"(?:^|;\s*)local_image=([^;]+)")


@dataclass(frozen=True)
class ExactStillInjection:
    asset_id: str
    scene_id: str
    image_path: str
    source_name: str
    source_url: str
    license_name: str
    attribution_text: str
    scientific_authenticity: float
    relevance_score: float
    visual_class: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def from_candidate(
    candidate: VD.AssetCandidate | None,
    spec: VD.SceneSpec,
    *,
    require_file: bool = True,
) -> ExactStillInjection | None:
    """Return an exact still injection only for a local PubChem depiction."""
    if candidate is None or candidate.is_generated:
        return None
    if candidate.visual_class != VD.VisualClass.MOLECULAR_RENDER:
        return None
    if candidate.rights.source_name != "PubChem / National Library of Medicine":
        return None
    if candidate.scientific_authenticity < 0.95:
        return None
    m = _LOCAL_IMAGE_RE.search(candidate.provenance_notes or "")
    path = (m.group(1).strip() if m else "")
    if not path:
        return None
    if require_file and not (os.path.isfile(path) and os.path.getsize(path) > 100):
        return None
    return ExactStillInjection(
        asset_id=candidate.asset_id,
        scene_id=spec.scene_id,
        image_path=path,
        source_name=candidate.rights.source_name,
        source_url=candidate.rights.source_url,
        license_name=candidate.rights.license_name,
        attribution_text=candidate.rights.attribution_text,
        scientific_authenticity=float(candidate.scientific_authenticity),
        relevance_score=float(candidate.relevance_score),
        visual_class=candidate.visual_class.value,
    )


def render_with_legacy_compositor(legacy, scene, idx, seg_mp3, seg_dur, injection: ExactStillInjection):
    """Render one exact still using main.py's proven scene motion/audio stack.

    This intentionally mirrors the existing archival-still compositor, but runs
    BEFORE stock search because exact scientific evidence is the preferred visual
    for a molecular scene. Captions remain a later whole-video layer, so this
    function only creates the same scene MP4 shape ``build_scene`` would return.
    """
    if not os.path.isfile(injection.image_path):
        raise RuntimeError(f"exact still disappeared before render: {injection.image_path}")
    out = os.path.join(legacy.WORK, f"s{idx}.mp4")
    frames = max(1, round(float(seg_dur) * 30))
    zspeed = legacy.PROFILE["zoom_speed"]
    kind = scene.get("motion", "zoom_in")
    motion = legacy._motion_filter(
        scene,
        frames,
        zspeed,
        idx=idx,
        prev_kind=getattr(legacy, "_last_motion_kind", None),
    )
    legacy._last_motion_kind = kind
    grade = legacy.PROFILE["grade"]
    stat = legacy._stat_overlay(scene, seg_dur)
    legacy.run([
        "ffmpeg", "-y", "-loop", "1", "-i", injection.image_path, "-i", seg_mp3,
        "-t", f"{float(seg_dur):.3f}", "-r", "30",
        "-filter_complex", f"[0:v]{motion}{grade}{stat},setsar=1[v]",
        "-map", "[v]", "-map", "1:a", "-r", "30", "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", out,
    ])
    legacy.ARCHIVAL_SCENES += 1
    print(
        f"  [quality-still] exact {injection.source_name} scene "
        f"{idx}: {injection.asset_id} (auth={injection.scientific_authenticity:.2f})"
    )
    return out
