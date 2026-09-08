#!/usr/bin/env python3
"""Zero-network regressions for quality_render_bridge.py."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_render_bridge as B
import visual_director as VD


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _spec():
    return VD.SceneSpec(
        scene_id="1",
        narration="A satellite view reveals the hurricane eye.",
        scientific_subject="hurricane eye",
        must_show=("hurricane eye",),
        domain="earth",
        authenticity_importance=10,
        forbidden_generic_substitutions=("generic storm clouds",),
    )


def _nasa_candidate():
    return VD.AssetCandidate(
        asset_id="svs:123",
        visual_class=VD.VisualClass.AUTHENTIC_SCIENCE_VIDEO,
        subject_terms=("hurricane eye",),
        relevance_score=0.9,
        scientific_authenticity=1.0,
        technical_quality=0.9,
        rights=VD.RightsInfo(
            source_name="NASA Scientific Visualization Studio",
            source_url="https://svs.gsfc.nasa.gov/123/",
            license_name="NASA media usage guidelines",
            license_url="https://www.nasa.gov/nasa-brand-center/images-and-media/",
            attribution_text="NASA Scientific Visualization Studio",
        ),
        provenance_notes=(
            "authentic NASA SVS source; "
            "media=https://svs.gsfc.nasa.gov/vis/a000000/a000123/movie.mp4; satellite hurricane"
        ),
    )


def test_nasa_adapter_is_strict_and_provenance_preserving():
    spec = _spec()
    row = B.to_legacy_video_candidate(_nasa_candidate(), spec)
    check(row is not None, "authentic NASA moving media can enter legacy candidate pool")
    check(row["url"].endswith("movie.mp4"), "direct media URL, not source page, is injected")
    check(row["id"] == "svs:123", "stable NASA asset ID survives adapter")
    check(row["quality_provenance"]["source_name"] == "NASA Scientific Visualization Studio",
          "NASA provenance survives adapter")
    check(row["quality_provenance"]["scientific_authenticity"] == 1.0,
          "scientific-authenticity score survives adapter")

    generated = VD.AssetCandidate(
        asset_id="gen:1",
        visual_class=VD.VisualClass.GENERATED_VIDEO,
        subject_terms=("hurricane eye",),
        relevance_score=1.0,
        scientific_authenticity=0.4,
        technical_quality=1.0,
        rights=VD.RightsInfo(source_name="generated media", source_url="https://example.invalid/a", license_name="generated"),
        provenance_notes="media=https://example.invalid/a.mp4",
        is_generated=True,
        vision_verified=True,
    )
    check(B.to_legacy_video_candidate(generated, spec) is None,
          "generated media cannot masquerade as authentic NASA injection")


def test_free_network_policy_cannot_spend_or_generate():
    p = B._free_network_policy(True)
    check(not p.plan_only and p.allow_network, "explicit certification policy permits free network")
    check(not p.allow_paid and not p.allow_generated_visuals,
          "free-network bridge cannot enable paid/generated lanes")
    check(not p.enable_voice_experiments and not p.enable_sound_design and not p.enable_repair,
          "free-network bridge cannot silently enable experimental audio/repair")

    p0 = B._free_network_policy(False)
    check(p0.plan_only and not p0.allow_network, "default bridge policy remains zero-call plan-only")


def test_plan_only_manifest_resolution_makes_zero_calls():
    manifest = {
        "title": "Storm",
        "scenes": [{
            "id": 1,
            "voiceover": "A satellite view reveals the hurricane eye.",
            "search_query": "hurricane eye satellite",
        }],
    }
    injections, decisions = B.resolve_manifest_assets(manifest, allow_free_network=False)
    check(injections == {}, "plan-only mode injects no unverified asset")
    check(len(decisions) == 1 and decisions[0].provider_calls_made == 0,
          "plan-only resolution records zero provider calls")


def test_injection_precedes_stock_without_bypassing_pool():
    nasa = {"id": "svs:123", "url": "https://example/nasa.mp4", "desc": "NASA hurricane"}
    stock = [
        {"id": "pex:1", "url": "https://example/1.mp4", "desc": "storm"},
        {"id": "svs:123", "url": "https://example/duplicate.mp4", "desc": "duplicate"},
    ]
    rows = B._prepend_unique(nasa, stock)
    check(rows[0]["id"] == "svs:123", "quality-first authentic candidate is considered first")
    check([r["id"] for r in rows].count("svs:123") == 1, "injected asset is de-duplicated")
    check(any(r["id"] == "pex:1" for r in rows), "legacy stock remains available as fallback")


if __name__ == "__main__":
    test_nasa_adapter_is_strict_and_provenance_preserving()
    test_free_network_policy_cannot_spend_or_generate()
    test_plan_only_manifest_resolution_makes_zero_calls()
    test_injection_precedes_stock_without_bypassing_pool()
    print("quality_render_bridge tests: PASS")
