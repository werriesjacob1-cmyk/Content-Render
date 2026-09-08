#!/usr/bin/env python3
"""Quality-first certification bridge into the existing render engine.

This is intentionally an ADDITIVE seam rather than a rewrite of ``main.py``.
It lets the current quality stack affect a real certification MP4 while keeping
all of the renderer's proven TTS, caption, pacing, footage-judge, audio-mix,
cover, and final-QA behavior intact.

Current load-bearing behavior:
1. Build the Visual Director plan for the exact manifest.
2. Under an explicit FREE-network opt-in, resolve authentic scientific assets
   (currently NASA SVS / PubChem / RCSB via ``quality_runtime``).
3. Only authentic NASA *video* winners are adapted into the legacy moving-video
   candidate contract in this first bridge. They are injected AHEAD of generic
   stock for the matching scene but still have to survive the existing footage
   relevance/darkness/technical checks in ``main.py``.
4. PubChem/RCSB/deterministic/generated lanes remain visible in the provenance
   record instead of being faked into a video-shaped asset they are not.
5. A provenance JSON is written beside the render even when final QA aborts.

Nothing here publishes, edits ``render.yml``, or changes production defaults.
Run explicitly as ``python quality_render_bridge.py manifest.json``. Network is
OFF unless QUALITY_RENDER_FREE_NETWORK=I_ACCEPT_FREE_NETWORK is set.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import re
import sys
from typing import Any, Mapping

import main as legacy
import quality_runtime as QR
import quality_stack as Q
import visual_director as VD


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
    errors: tuple[str, ...] = ()
    provider_calls_made: int = 0


def _scene_key(raw: Mapping[str, Any], fallback: int) -> str:
    return str(raw.get("id") or raw.get("scene_id") or fallback)


def _nasa_media_url(candidate: VD.AssetCandidate | None) -> str:
    """Return the direct NASA media URL only for an authentic NASA video.

    ``AssetCandidate`` deliberately stores provider-neutral provenance. The
    NASA adapter records the exact direct media URL as ``media=...``; extracting
    only that explicit field prevents a page/citation URL from being mistaken
    for a playable clip.
    """
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

    The old renderer is still the final selection authority for this bridge:
    this merely ensures the reality-first candidate is CONSIDERED before stock.
    It does not hard-code a judge score or bypass the existing relevance gate.
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
    """Resolve every scene once before rendering; return injectable video rows.

    In plan-only mode this performs ZERO provider calls and returns no injected
    assets. With free network enabled, only tools allowed by the strict
    no-paid/no-generated policy can execute.
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
            row = to_legacy_video_candidate(winner, spec)
            if row is not None:
                injections[spec.scene_id] = row
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
                legacy_video_injected=row is not None,
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
    """Patch only the two narrow legacy seams needed for per-scene injection.

    Returns a callable restoring the original functions. This is intentionally
    reversible and process-local; importing this module never mutates ``main``.
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
        context["scene_id"] = raw_ids.get(id(scene), _scene_key(scene, idx))
        try:
            return original_build_scene(scene, idx, seg_mp3, seg_dur)
        finally:
            context["scene_id"] = ""

    def bridged_gather(query):
        rows = list(original_gather(query) or [])
        primary = injections.get(context["scene_id"])
        return _prepend_unique(primary, rows)

    legacy.build_scene = bridged_build_scene
    legacy._gather_candidates = bridged_gather

    def restore():
        legacy.build_scene = original_build_scene
        legacy._gather_candidates = original_gather

    return restore


def _write_provenance(decisions: list[SceneAssetDecision], allow_free_network: bool) -> None:
    os.makedirs(legacy.OUT, exist_ok=True)
    payload = {
        "schema": "quality-render-bridge-v1",
        "allow_free_network": allow_free_network,
        "paid_quality_calls_allowed": False,
        "generated_visuals_allowed": False,
        "publishing_enabled": False,
        "scene_decisions": [asdict(d) for d in decisions],
        "total_quality_provider_calls": sum(d.provider_calls_made for d in decisions),
        "nasa_video_injections": sum(1 for d in decisions if d.legacy_video_injected),
    }
    with open(os.path.join(legacy.OUT, "quality_asset_provenance.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main() -> None:
    mpath = sys.argv[1] if len(sys.argv) > 1 else "manifest.json"
    with open(mpath, encoding="utf-8") as f:
        manifest = json.load(f)
    allow_free_network = os.getenv("QUALITY_RENDER_FREE_NETWORK", "") == FREE_NETWORK_ACK
    if not allow_free_network:
        print("[quality-bridge] FREE network disabled; set QUALITY_RENDER_FREE_NETWORK="
              f"{FREE_NETWORK_ACK} for authentic scientific retrieval")
    injections, decisions = resolve_manifest_assets(
        manifest,
        allow_free_network=allow_free_network,
    )
    print(f"[quality-bridge] prepared {len(injections)} authentic NASA video injection(s) "
          f"across {len(decisions)} scene(s)")
    restore = install_bridge(injections, manifest)
    # main.main() reads argv itself. Keep the same manifest path and preserve its
    # existing fail-closed final QA behavior; even SystemExit writes provenance.
    try:
        legacy.main()
    finally:
        restore()
        _write_provenance(decisions, allow_free_network)


if __name__ == "__main__":
    main()
