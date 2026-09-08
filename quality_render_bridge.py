#!/usr/bin/env python3
"""Quality-first certification bridge into the existing render engine.

This is intentionally an ADDITIVE seam rather than a rewrite of ``main.py``.
It lets the current quality stack affect a real certification MP4 while keeping
all of the renderer's proven TTS, caption, pacing, footage-judge, audio-mix,
cover, and final-QA behavior intact.

Load-bearing behavior:
1. Require the sealed Writer V2.1 evidence bundle beside the manifest and prove
   every manifest source_claim_id belongs to that exact inventory.
2. Build the Visual Director plan for the exact accepted manifest.
3. Under an explicit FREE-network opt-in, resolve authentic scientific assets
   (NASA SVS / PubChem / RCSB via ``quality_runtime``).
4. Authentic NASA *video* winners are injected AHEAD of generic stock for their
   scene but still have to survive the existing relevance/darkness/technical
   selection in ``main.py``.
5. Exact PubChem molecular depictions are rendered directly through the existing
   scene compositor BEFORE generic stock, preserving narration, motion, grade,
   captions, audio mix, and final-video QA. Generated stills cannot enter here.
6. RCSB coordinate records and deterministic/generated lanes remain visible in
   provenance until a truthful renderer for those exact asset types is wired.
7. Provenance JSON is written beside the render even when final QA aborts.

Nothing here publishes, edits ``render.yml``, or changes production defaults.
Run explicitly as ``python quality_render_bridge.py <cert-dir>/manifest.json``.
Network is OFF unless QUALITY_RENDER_FREE_NETWORK=I_ACCEPT_FREE_NETWORK is set.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping

import main as legacy
import quality_exact_still as QES
import quality_runtime as QR
import quality_stack as Q
import visual_director as VD
import writer_story_bridge as WSB


FREE_NETWORK_ACK = "I_ACCEPT_FREE_NETWORK"
_MEDIA_RE = re.compile(r"(?:^|;\s*)media=([^;]+)")


@dataclass(frozen=True)
class SceneAssetDecision:
    scene_id: str
    scientific_subject: str
    attempted_tools: tuple[str, ...]
    delegated_tools: tuple[str, ...]
    generated_escalation_tools: tuple[str, ...]
    winner_asset_id: str = ""
    winner_visual_class: str = ""
    winner_source_name: str = ""
    winner_source_url: str = ""
    winner_provenance: str = ""
    legacy_video_injected: bool = False
    exact_still_routed: bool = False
    errors: tuple[str, ...] = ()
    provider_calls_made: int = 0


def _scene_key(raw: Mapping[str, Any], fallback: int) -> str:
    return str(raw.get("id") or raw.get("scene_id") or fallback)


def _require_certification_evidence(manifest_path: str | Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Fail before footage if the sealed Writer evidence handoff is absent/drifted."""
    mpath = Path(manifest_path)
    evidence_path = mpath.parent / "writer_evidence.json"
    session_path = mpath.parent / "quality_session_plan.json"
    if not evidence_path.is_file():
        raise RuntimeError(f"sealed Writer evidence missing beside manifest: {evidence_path}")
    if not session_path.is_file():
        raise RuntimeError(f"strict quality-session plan missing beside manifest: {session_path}")

    with evidence_path.open(encoding="utf-8") as f:
        evidence = json.load(f)
    inventory = evidence.get("claim_inventory")
    topic_id = str(evidence.get("topic_id") or "").strip()
    if not topic_id or not isinstance(inventory, Mapping):
        raise RuntimeError("writer_evidence.json missing topic_id/claim_inventory")
    packet = WSB.from_writer_inventory(topic_id, inventory)
    ok, problems = WSB.verify_manifest_refs(manifest, packet)
    if not ok:
        raise RuntimeError("certification manifest/evidence mismatch: " + "; ".join(problems))

    with session_path.open(encoding="utf-8") as f:
        session = json.load(f)
    if session.get("upstream_traceability_passed") is not True:
        raise RuntimeError("quality_session_plan does not carry upstream Writer V2.1 traceability pass")
    blockers = session.get("blockers") or []
    if blockers:
        raise RuntimeError("quality_session_plan contains blockers: " + "; ".join(str(x) for x in blockers))
    if str(session.get("topic_id") or "") != topic_id:
        raise RuntimeError("quality_session_plan topic_id differs from writer_evidence topic_id")

    manifest_refs = set(WSB.manifest_claim_ids(manifest))
    sealed_refs = set(str(x) for x in (evidence.get("manifest_referenced_claim_ids") or []))
    if manifest_refs != sealed_refs:
        raise RuntimeError("manifest referenced-claim set differs from sealed writer_evidence claim set")

    return {
        "topic_id": topic_id,
        "claim_count": len(packet.claims),
        "referenced_claim_count": len(manifest_refs),
        "grounding_mode": packet.grounding_mode,
    }


def _nasa_media_url(candidate: VD.AssetCandidate | None) -> str:
    """Return the direct NASA media URL only for an authentic NASA video."""
    if candidate is None:
        return ""
    if candidate.visual_class != VD.VisualClass.AUTHENTIC_SCIENCE_VIDEO:
        return ""
    if candidate.is_generated or candidate.rights.source_name != "NASA Scientific Visualization Studio":
        return ""
    m = _MEDIA_RE.search(candidate.provenance_notes or "")
    url = (m.group(1).strip() if m else "")
    if not url.startswith("https://"):
        return ""
    return url


def to_legacy_video_candidate(
    candidate: VD.AssetCandidate | None,
    spec: VD.SceneSpec,
) -> dict[str, Any] | None:
    """Adapt one authenticated NASA video into ``main._gather_candidates`` shape.

    The legacy renderer remains the final moving-footage selection authority:
    this only ensures reality-first NASA media is CONSIDERED before stock. No
    score is hard-coded and no existing relevance gate is bypassed.
    """
    media_url = _nasa_media_url(candidate)
    if not media_url or candidate is None:
        return None
    desc_parts = [spec.scientific_subject, *spec.must_show, candidate.provenance_notes]
    desc = " ".join(str(x).strip() for x in desc_parts if str(x).strip())
    return {
        "id": candidate.asset_id,
        "url": media_url,
        "desc": desc[:1200],
        "source": "nasa_svs_quality_stack",
        "quality_provenance": {
            "visual_class": candidate.visual_class.value,
            "source_name": candidate.rights.source_name,
            "source_url": candidate.rights.source_url,
            "license_name": candidate.rights.license_name,
            "attribution_text": candidate.rights.attribution_text,
            "scientific_authenticity": candidate.scientific_authenticity,
            "relevance_score": candidate.relevance_score,
        },
    }


def _free_network_policy(enabled: bool) -> Q.QualityPolicy:
    return Q.QualityPolicy(
        plan_only=not enabled,
        allow_network=enabled,
        allow_paid=False,
        allow_generated_visuals=False,
        enable_voice_experiments=False,
        enable_sound_design=False,
        enable_repair=False,
        enable_final_qa_provider_calls=False,
    )


def resolve_manifest_assets(
    manifest: Mapping[str, Any],
    *,
    allow_free_network: bool,
) -> tuple[dict[str, dict[str, Any]], list[SceneAssetDecision]]:
    """Resolve every scene once; return strict per-scene renderer injections.

    Injection shapes are process-local and never serialized as trust evidence:
      {"kind": "video_candidate", "row": legacy_candidate}
      {"kind": "exact_still", "still": ExactStillInjection, "used": bool}

    Plan-only mode performs ZERO provider calls and returns no injection. Free
    network mode can only execute tools permitted by a no-paid/no-generated policy.
    """
    plan = VD.build_visual_plan(manifest)
    errors = plan.validate()
    if errors:
        raise ValueError("invalid Visual Director plan: " + "; ".join(errors))

    policy = _free_network_policy(allow_free_network)
    injections: dict[str, dict[str, Any]] = {}
    decisions: list[SceneAssetDecision] = []

    for spec in plan.scenes:
        if allow_free_network:
            resolution = QR.resolve_authentic_scene(
                spec,
                policy,
                work_dir=os.path.join(legacy.ROOT, ".quality_work"),
                used_ids=tuple(str(x) for x in getattr(legacy, "_used_video_ids", set())),
            )
            winner = resolution.winner
            video_row = to_legacy_video_candidate(winner, spec)
            exact_still = QES.from_candidate(winner, spec)
            if video_row is not None:
                injections[spec.scene_id] = {
                    "kind": "video_candidate",
                    "row": video_row,
                    "used": False,
                }
            elif exact_still is not None:
                injections[spec.scene_id] = {
                    "kind": "exact_still",
                    "still": exact_still,
                    "used": False,
                }
            decisions.append(SceneAssetDecision(
                scene_id=spec.scene_id,
                scientific_subject=spec.scientific_subject,
                attempted_tools=resolution.attempted_tools,
                delegated_tools=resolution.delegated_tools,
                generated_escalation_tools=resolution.generated_escalation_tools,
                winner_asset_id=(winner.asset_id if winner else ""),
                winner_visual_class=(winner.visual_class.value if winner else ""),
                winner_source_name=(winner.rights.source_name if winner else ""),
                winner_source_url=(winner.rights.source_url if winner else ""),
                winner_provenance=(winner.provenance_notes if winner else ""),
                legacy_video_injected=video_row is not None,
                exact_still_routed=exact_still is not None,
                errors=resolution.errors,
                provider_calls_made=resolution.provider_calls_made,
            ))
        else:
            local = QR.plan_scene(spec, policy)
            routes = local.get("routes") or []
            delegated = []
            for route in routes:
                for tool in route.get("tools") or []:
                    if tool.get("tool") == "existing_real_footage":
                        delegated.append("existing_real_footage")
            decisions.append(SceneAssetDecision(
                scene_id=spec.scene_id,
                scientific_subject=spec.scientific_subject,
                attempted_tools=(),
                delegated_tools=tuple(dict.fromkeys(delegated)),
                generated_escalation_tools=(),
                provider_calls_made=0,
            ))

    return injections, decisions


def _prepend_unique(primary: dict[str, Any] | None, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if primary is None:
        return rows
    pid = primary.get("id")
    out = [primary]
    out.extend(r for r in rows if r.get("id") != pid)
    return out


def install_bridge(injections: Mapping[str, dict[str, Any]], manifest: Mapping[str, Any]):
    """Patch only the narrow per-scene seams needed for quality-first injection.

    Exact stills are rendered before legacy stock search. NASA video remains a
    candidate at the head of the existing moving-footage pool. Any exact-still
    compositor failure falls back to the untouched legacy scene builder so the
    certification render does not die over an optional adapter failure.

    Returns a callable restoring the original functions. Importing this module
    never mutates ``main.py``.
    """
    original_build_scene = legacy.build_scene
    original_gather = legacy._gather_candidates
    raw_ids = {
        id(raw): _scene_key(raw, i)
        for i, raw in enumerate(manifest.get("scenes") or [], 1)
        if isinstance(raw, dict)
    }
    context = {"scene_id": ""}

    def bridged_build_scene(scene, idx, seg_mp3, seg_dur):
        sid = raw_ids.get(id(scene), _scene_key(scene, idx))
        injection = injections.get(sid)
        if injection and injection.get("kind") == "exact_still":
            try:
                out = QES.render_with_legacy_compositor(
                    legacy, scene, idx, seg_mp3, seg_dur, injection["still"]
                )
                injection["used"] = True
                return out
            except Exception as exc:  # noqa: BLE001 -- preserve proven legacy fallback
                injection["error"] = f"{type(exc).__name__}: {exc}"
                print(f"  [quality-still] exact still compositor failed ({exc}) — falling back to legacy scene")

        context["scene_id"] = sid
        try:
            return original_build_scene(scene, idx, seg_mp3, seg_dur)
        finally:
            context["scene_id"] = ""

    def bridged_gather(query):
        rows = list(original_gather(query) or [])
        injection = injections.get(context["scene_id"])
        primary = (
            injection.get("row")
            if injection and injection.get("kind") == "video_candidate"
            else None
        )
        if primary is not None:
            injection["used"] = True  # considered by the legacy selector; final winner remains its decision
        return _prepend_unique(primary, rows)

    legacy.build_scene = bridged_build_scene
    legacy._gather_candidates = bridged_gather

    def restore():
        legacy.build_scene = original_build_scene
        legacy._gather_candidates = original_gather

    return restore


def _write_provenance(
    decisions: list[SceneAssetDecision],
    allow_free_network: bool,
    evidence_status: Mapping[str, Any],
    injections: Mapping[str, dict[str, Any]],
) -> None:
    os.makedirs(legacy.OUT, exist_ok=True)
    exact_used = sum(
        1 for x in injections.values()
        if x.get("kind") == "exact_still" and x.get("used") is True
    )
    video_considered = sum(
        1 for x in injections.values()
        if x.get("kind") == "video_candidate" and x.get("used") is True
    )
    payload = {
        "schema": "quality-render-bridge-v3",
        "evidence_verified_before_render": True,
        "evidence_status": dict(evidence_status),
        "allow_free_network": allow_free_network,
        "paid_quality_calls_allowed": False,
        "generated_visuals_allowed": False,
        "publishing_enabled": False,
        "scene_decisions": [asdict(d) for d in decisions],
        "total_quality_provider_calls": sum(d.provider_calls_made for d in decisions),
        "nasa_video_candidates_considered": video_considered,
        "pubchem_exact_stills_rendered": exact_used,
        "injection_errors": {
            sid: x.get("error") for sid, x in injections.items() if x.get("error")
        },
    }
    with open(os.path.join(legacy.OUT, "quality_asset_provenance.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main() -> None:
    mpath = sys.argv[1] if len(sys.argv) > 1 else "manifest.json"
    with open(mpath, encoding="utf-8") as f:
        manifest = json.load(f)
    evidence_status = _require_certification_evidence(mpath, manifest)
    print(f"[quality-bridge] Writer evidence VERIFIED: {evidence_status}")
    allow_free_network = os.getenv("QUALITY_RENDER_FREE_NETWORK", "") == FREE_NETWORK_ACK
    if not allow_free_network:
        print("[quality-bridge] FREE network disabled; set QUALITY_RENDER_FREE_NETWORK="
              f"{FREE_NETWORK_ACK} for authentic scientific retrieval")
    injections, decisions = resolve_manifest_assets(
        manifest,
        allow_free_network=allow_free_network,
    )
    n_video = sum(1 for x in injections.values() if x.get("kind") == "video_candidate")
    n_still = sum(1 for x in injections.values() if x.get("kind") == "exact_still")
    print(
        f"[quality-bridge] prepared {n_video} authentic NASA video candidate(s) + "
        f"{n_still} exact PubChem still(s) across {len(decisions)} scene(s)"
    )
    restore = install_bridge(injections, manifest)
    try:
        legacy.main()
    finally:
        restore()
        _write_provenance(decisions, allow_free_network, evidence_status, injections)


if __name__ == "__main__":
    main()
