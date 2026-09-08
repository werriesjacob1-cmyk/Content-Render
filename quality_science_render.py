#!/usr/bin/env python3
"""Private certification renderer with deterministic science-motion fallback.

This is a thin layer over the already-green ``quality_render_bridge``. It keeps
that bridge's evidence gate, NASA/PubChem resolution, legacy footage selection,
caption/audio/final-QA behavior, and provenance. The only added behavior is:

  authentic NASA/PubChem > evidence-bound deterministic science motion > stock

for a small set of V2.1 treatments whose frozen beat semantics license an ordered
process graphic. Generated media remains disabled here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

import main as legacy
import quality_render_bridge as B
import quality_science_motion as QSM
import writer_story_bridge as WSB


def _augment_provenance(
    motion_plans: Mapping[str, QSM.ScienceMotionPlan],
    motion_state: Mapping[str, dict[str, Any]],
) -> None:
    path = Path(legacy.OUT) / "quality_asset_provenance.json"
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    rows = []
    for sid, plan in motion_plans.items():
        state = motion_state.get(sid) or {}
        row = plan.provenance()
        row["rendered"] = state.get("rendered") is True
        if state.get("error"):
            row["render_error"] = state["error"]
        rows.append(row)
    payload["schema"] = "quality-render-bridge-v4-science-motion"
    payload["science_motion_planned"] = len(rows)
    payload["science_motion_rendered"] = sum(1 for r in rows if r.get("rendered"))
    payload["science_motion"] = rows
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main() -> None:
    mpath = sys.argv[1] if len(sys.argv) > 1 else "manifest.json"
    with open(mpath, encoding="utf-8") as f:
        manifest = json.load(f)

    # Same load-bearing preflight as the green bridge. Nothing visual happens
    # until the exact Writer evidence/session bundle is proved consistent.
    evidence_status = B._require_certification_evidence(mpath, manifest)
    print(f"[quality-science] Writer evidence VERIFIED: {evidence_status}")

    allowed_claim_ids = WSB.manifest_claim_ids(manifest)
    planned = QSM.plan_manifest(manifest, allowed_claim_ids)

    allow_free_network = os.getenv("QUALITY_RENDER_FREE_NETWORK", "") == B.FREE_NETWORK_ACK
    injections, decisions = B.resolve_manifest_assets(
        manifest,
        allow_free_network=allow_free_network,
    )

    # Authentic science is higher priority than deterministic explanatory
    # graphics. Only targets with NO NASA/PubChem injection receive motion.
    active_motion = {sid: plan for sid, plan in planned.items() if sid not in injections}
    suppressed = sorted(set(planned) - set(active_motion))
    if suppressed:
        print(f"[quality-science] authentic asset outranked deterministic motion for scene(s): {suppressed}")
    print(
        f"[quality-science] deterministic motion planned={len(planned)} active={len(active_motion)}; "
        f"authentic injections={len(injections)}"
    )

    bridge_restore = B.install_bridge(injections, manifest)
    bridged_build_scene = legacy.build_scene
    motion_state: dict[str, dict[str, Any]] = {sid: {"rendered": False} for sid in active_motion}

    def science_build_scene(scene, idx, seg_mp3, seg_dur):
        sid = B._scene_key(scene, idx)
        plan = active_motion.get(sid)
        if plan is not None:
            try:
                out = QSM.render_for_scene(plan, legacy, idx, seg_mp3, seg_dur)
                motion_state[sid]["rendered"] = True
                print(
                    f"  [science-motion] deterministic {plan.spec.kind.value} scene {sid} "
                    f"from claims {list(plan.source_claim_ids)}"
                )
                return out
            except Exception as exc:  # noqa: BLE001 -- preserve proven visual fallback
                motion_state[sid]["error"] = f"{type(exc).__name__}: {exc}"
                print(f"  [science-motion] render failed ({exc}) — falling back to authentic/legacy scene path")
        return bridged_build_scene(scene, idx, seg_mp3, seg_dur)

    legacy.build_scene = science_build_scene
    try:
        legacy.main()
    finally:
        # Restore in reverse order so no process-global monkeypatch survives even
        # when final assembled-video QA exits non-zero.
        legacy.build_scene = bridged_build_scene
        bridge_restore()
        B._write_provenance(decisions, allow_free_network, evidence_status, injections)
        _augment_provenance(active_motion, motion_state)


if __name__ == "__main__":
    main()
