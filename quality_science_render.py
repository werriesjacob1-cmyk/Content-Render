#!/usr/bin/env python3
"""Private certification renderer with deterministic science-motion fallback.

Authentic NASA/PubChem > evidence-bound deterministic science motion > stock.
The renderer now also writes a pre-search visual bible and actual per-scene asset
lineage so downstream learning knows what really rendered, not only what was
considered.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

import main as legacy
import quality_asset_lineage as QAL
import quality_render_bridge as B
import quality_science_motion as QSM
import quality_visual_bible as QVB
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
    payload["schema"] = "quality-render-bridge-v5-science-motion-lineage"
    payload["science_motion_planned"] = len(rows)
    payload["science_motion_rendered"] = sum(1 for r in rows if r.get("rendered"))
    payload["science_motion"] = rows
    payload["visual_bible_file"] = "visual_bible.json"
    payload["final_asset_lineage_file"] = "final_asset_lineage.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _write_scene_timeline(manifest: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    cursor = 0.0
    scenes = [s for s in (manifest.get("scenes") or []) if isinstance(s, Mapping)]
    for idx, scene in enumerate(scenes, 1):
        path = Path(legacy.WORK) / f"s{idx}.mp4"
        duration = float(legacy.ffprobe_dur(str(path))) if path.is_file() else 0.0
        start = cursor
        end = cursor + max(0.0, duration)
        rows.append({
            "scene_id": B._scene_key(scene, idx),
            "scene_index": idx,
            "role": str(scene.get("_v2_role") or "scene"),
            "start_s": round(start, 3),
            "end_s": round(end, 3),
            "duration_s": round(max(0.0, duration), 3),
            "search_query": str(scene.get("search_query") or ""),
            "source_claim_ids": list(scene.get("source_claim_ids") or []),
            "rendered_scene_file_present": path.is_file() and duration > 0,
        })
        cursor = end
    payload = {
        "schema": "quality-scene-timeline-v1",
        "scene_count": len(rows),
        "measured_body_duration_s": round(cursor, 3),
        "scenes": rows,
    }
    Path(legacy.OUT).mkdir(parents=True, exist_ok=True)
    (Path(legacy.OUT) / "scene_timeline.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return payload


def main() -> None:
    mpath = sys.argv[1] if len(sys.argv) > 1 else "manifest.json"
    with open(mpath, encoding="utf-8") as f:
        manifest = json.load(f)

    evidence_status = B._require_certification_evidence(mpath, manifest)
    print(f"[quality-science] Writer evidence VERIFIED: {evidence_status}")

    Path(legacy.OUT).mkdir(parents=True, exist_ok=True)
    visual_bible = QVB.write_visual_bible(manifest, Path(legacy.OUT) / "visual_bible.json")
    print(f"[quality-science] visual bible sealed for {len(visual_bible.get('scenes') or [])} scenes")

    allowed_claim_ids = WSB.manifest_claim_ids(manifest)
    planned = QSM.plan_manifest(manifest, allowed_claim_ids)

    allow_free_network = os.getenv("QUALITY_RENDER_FREE_NETWORK", "") == B.FREE_NETWORK_ACK
    injections, decisions = B.resolve_manifest_assets(
        manifest,
        allow_free_network=allow_free_network,
    )
    decision_by_scene = {d.scene_id: d for d in decisions}

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
    lineage_state: dict[str, dict[str, Any]] = {}

    def _record_lineage(scene, idx, out_path, *, renderer_kind: str, before_ids: list[str],
                        injection=None, science_plan=None, notes: str = ""):
        sid = B._scene_key(scene, idx)
        after_ids = list(getattr(legacy, "_used_history", []))
        new_ids = tuple(str(x) for x in after_ids[len(before_ids):])
        contract = QAL.bible_scene(visual_bible, sid)
        decision = decision_by_scene.get(sid)
        injection_id = str(getattr(decision, "winner_asset_id", "") or "")
        injection_url = str(getattr(decision, "winner_source_url", "") or "")
        inj_selected = bool(injection_id and injection_id in new_ids)
        duration = float(legacy.ffprobe_dur(str(out_path))) if out_path and Path(out_path).is_file() else 0.0
        actual_kind = renderer_kind
        artifacts: tuple[str, ...] = ()
        if actual_kind == "legacy":
            before_stat = int(lineage_state.get(sid, {}).get("before_stat", 0))
            before_arch = int(lineage_state.get(sid, {}).get("before_arch", 0))
            if int(getattr(legacy, "STAT_CARD_SCENES", 0)) > before_stat:
                actual_kind = "stat_card"
            elif int(getattr(legacy, "ARCHIVAL_SCENES", 0)) > before_arch:
                actual_kind = "archival_still"
            elif inj_selected:
                actual_kind = "authentic_science_video"
            elif new_ids:
                actual_kind = "legacy_real_video"
            else:
                actual_kind, artifacts = QAL.classify_legacy_artifacts(legacy.WORK, idx)
        selected_urls = (injection_url,) if inj_selected and injection_url else ()
        lineage_state[sid] = {
            "entry": QAL.AssetLineageEntry(
                scene_id=sid,
                scene_index=idx,
                visual_intent=str(contract.get("intent") or "demonstrate"),
                subject_id=str(contract.get("subject_id") or "unknown"),
                subject=str(contract.get("subject") or scene.get("search_query") or "scene subject"),
                renderer_kind=actual_kind,
                output_file=str(out_path or ""),
                duration_s=round(duration, 3),
                selected_asset_ids=new_ids or ((injection_id,) if actual_kind in {"exact_scientific_still", "deterministic_science_motion"} and injection_id else ()),
                selected_source_urls=selected_urls,
                source_family=str(contract.get("preferred_source_family") or ""),
                source_claim_ids=tuple(str(x) for x in (scene.get("source_claim_ids") or [])),
                continuity_with=tuple(str(x) for x in (contract.get("continuity_with") or [])),
                injection_asset_id=injection_id,
                injection_selected=inj_selected or actual_kind == "exact_scientific_still",
                science_motion_kind=(science_plan.spec.kind.value if science_plan is not None else ""),
                attributable=actual_kind != "unattributed",
                notes=(notes + (f" artifacts={list(artifacts)}" if artifacts else "")).strip(),
            )
        }

    def science_build_scene(scene, idx, seg_mp3, seg_dur):
        sid = B._scene_key(scene, idx)
        before_ids = list(getattr(legacy, "_used_history", []))
        lineage_state[sid] = {
            "before_stat": int(getattr(legacy, "STAT_CARD_SCENES", 0)),
            "before_arch": int(getattr(legacy, "ARCHIVAL_SCENES", 0)),
        }
        plan = active_motion.get(sid)
        if plan is not None:
            try:
                out = QSM.render_for_scene(plan, legacy, idx, seg_mp3, seg_dur)
                motion_state[sid]["rendered"] = True
                _record_lineage(scene, idx, out, renderer_kind="deterministic_science_motion",
                                before_ids=before_ids, science_plan=plan)
                print(
                    f"  [science-motion] deterministic {plan.spec.kind.value} scene {sid} "
                    f"from claims {list(plan.source_claim_ids)}"
                )
                return out
            except Exception as exc:  # noqa: BLE001
                motion_state[sid]["error"] = f"{type(exc).__name__}: {exc}"
                print(f"  [science-motion] render failed ({exc}) — falling back to authentic/legacy scene path")
        out = bridged_build_scene(scene, idx, seg_mp3, seg_dur)
        injection = injections.get(sid)
        kind = "exact_scientific_still" if injection and injection.get("kind") == "exact_still" and injection.get("used") else "legacy"
        _record_lineage(scene, idx, out, renderer_kind=kind, before_ids=before_ids,
                        injection=injection, notes="quality bridge/legacy final selector")
        return out

    legacy.build_scene = science_build_scene
    try:
        legacy.main()
    finally:
        try:
            timeline = _write_scene_timeline(manifest)
            print(
                f"[quality-science] measured {timeline['scene_count']} scene boundaries "
                f"across {timeline['measured_body_duration_s']:.3f}s"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[quality-science] scene timeline capture failed: {exc}")
        try:
            ordered_entries = []
            for idx, scene in enumerate([s for s in (manifest.get("scenes") or []) if isinstance(s, Mapping)], 1):
                sid = B._scene_key(scene, idx)
                state = lineage_state.get(sid) or {}
                if state.get("entry") is not None:
                    ordered_entries.append(state["entry"])
            lineage = QAL.write_lineage(ordered_entries, Path(legacy.OUT) / "final_asset_lineage.json")
            print(
                f"[quality-science] asset lineage attributable={lineage['attributable_scene_count']}/"
                f"{lineage['scene_count']}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[quality-science] final asset lineage capture failed: {exc}")
        legacy.build_scene = bridged_build_scene
        bridge_restore()
        B._write_provenance(decisions, allow_free_network, evidence_status, injections)
        _augment_provenance(active_motion, motion_state)


if __name__ == "__main__":
    main()
