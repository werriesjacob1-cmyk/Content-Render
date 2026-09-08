#!/usr/bin/env python3
"""Zero-network regressions for quality_render_bridge.py."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_render_bridge as B
import quality_runtime as QR
import scientific_media as SM
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


def _sealed_manifest():
    return {
        "title": "Storm",
        "hook": "A hurricane eye can look eerily calm from orbit.",
        "hook_source_claim_ids": ["base_001"],
        "payoff": "That calm center is wrapped by the storm's strongest winds.",
        "payoff_source_claim_ids": ["base_002"],
        "_semantic_verified": True,
        "scenes": [
            {
                "id": 1,
                "voiceover": "A hurricane eye can look eerily calm from orbit.",
                "search_query": "hurricane eye satellite",
                "source_claim_ids": ["base_001"],
                "_v2_role": "hook",
            },
            {
                "id": 2,
                "voiceover": "That calm center is wrapped by the storm's strongest winds.",
                "search_query": "hurricane eyewall satellite",
                "source_claim_ids": ["base_002"],
                "_v2_role": "payoff",
            },
        ],
    }


def _writer_evidence(manifest=None):
    manifest = manifest or _sealed_manifest()
    return {
        "topic_id": "hurricane_eye",
        "claim_inventory": {
            "grounded": False,
            "claims": [
                {
                    "claim_id": "base_001",
                    "claim_text": "The eye of a strong hurricane can contain relatively calm conditions.",
                    "source_kind": "base_fact",
                    "source_ref": "topic_bank.fact",
                    "confidence": "verified_base_fact",
                    "allowed_numbers": [],
                    "allowed_entities": [],
                },
                {
                    "claim_id": "base_002",
                    "claim_text": "The eyewall around the eye contains the hurricane's strongest winds.",
                    "source_kind": "base_fact",
                    "source_ref": "topic_bank.wow",
                    "confidence": "verified_base_fact",
                    "allowed_numbers": [],
                    "allowed_entities": [],
                },
            ],
        },
        "manifest_referenced_claim_ids": ["base_001", "base_002"],
    }


def _write_sealed_bundle(root: Path, manifest=None):
    manifest = manifest or _sealed_manifest()
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "writer_evidence.json").write_text(json.dumps(_writer_evidence(manifest)), encoding="utf-8")
    (root / "quality_session_plan.json").write_text(json.dumps({
        "topic_id": "hurricane_eye",
        "upstream_traceability_passed": True,
        "blockers": [],
    }), encoding="utf-8")
    return root / "manifest.json", manifest


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


def test_precise_planet_queries_reach_nasa_and_are_not_duplicated():
    # Precise Writer visual intents should not need a generic word like
    # "planet" merely to qualify for NASA SVS. These are exactly the kinds of
    # Venus scenes the flagship writer produces.
    check(SM.svs_relevant("venus retrograde rotation"),
          "precise Venus rotation query is eligible for NASA SVS")
    check(SM.svs_relevant("venus sunrise horizon"),
          "precise Venus horizon query is eligible for NASA SVS")

    spec = VD.SceneSpec(
        scene_id="v1",
        narration="Venus spins in retrograde.",
        scientific_subject="venus retrograde rotation",
        must_show=("venus retrograde rotation",),
        mechanism="venus retrograde rotation",
        domain="space",
        authenticity_importance=10,
        forbidden_generic_substitutions=("generic galaxy wallpaper",),
    )
    query = QR._query(spec)
    check(query == "venus retrograde rotation",
          "scientific query de-duplicates identical Visual Director subject fields")


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


def test_sealed_writer_evidence_is_required_before_render():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mpath, manifest = _write_sealed_bundle(root)
        status = B._require_certification_evidence(mpath, manifest)
        check(status["topic_id"] == "hurricane_eye", "sealed Writer evidence passes intact")
        check(status["referenced_claim_count"] == 2, "exact referenced claim set is counted")

        (root / "writer_evidence.json").unlink()
        try:
            B._require_certification_evidence(mpath, manifest)
        except RuntimeError as exc:
            check("evidence missing" in str(exc), "missing writer evidence stops before render")
        else:
            raise AssertionError("missing writer evidence must fail closed")


def test_mutated_claim_or_sealed_reference_drift_fails_closed():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mpath, manifest = _write_sealed_bundle(root)

        mutated = json.loads(json.dumps(manifest))
        mutated["scenes"][0]["source_claim_ids"] = ["invented_999"]
        try:
            B._require_certification_evidence(mpath, mutated)
        except RuntimeError as exc:
            check("unknown Writer claim ID invented_999" in str(exc),
                  "unknown scene claim cannot reach visual retrieval")
        else:
            raise AssertionError("unknown claim ID must fail closed")

        evidence = _writer_evidence(manifest)
        evidence["manifest_referenced_claim_ids"] = ["base_001"]
        (root / "writer_evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
        try:
            B._require_certification_evidence(mpath, manifest)
        except RuntimeError as exc:
            check("referenced-claim set differs" in str(exc),
                  "sealed reference-set drift cannot reach render")
        else:
            raise AssertionError("sealed reference drift must fail closed")


def test_quality_session_blocker_or_topic_drift_fails_closed():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mpath, manifest = _write_sealed_bundle(root)
        (root / "quality_session_plan.json").write_text(json.dumps({
            "topic_id": "hurricane_eye",
            "upstream_traceability_passed": True,
            "blockers": ["scene 1 traceability failed"],
        }), encoding="utf-8")
        try:
            B._require_certification_evidence(mpath, manifest)
        except RuntimeError as exc:
            check("contains blockers" in str(exc), "quality-session blocker stops before render")
        else:
            raise AssertionError("quality-session blockers must fail closed")

        (root / "quality_session_plan.json").write_text(json.dumps({
            "topic_id": "different_topic",
            "upstream_traceability_passed": True,
            "blockers": [],
        }), encoding="utf-8")
        try:
            B._require_certification_evidence(mpath, manifest)
        except RuntimeError as exc:
            check("topic_id differs" in str(exc), "cross-topic packet swap stops before render")
        else:
            raise AssertionError("cross-topic packet swap must fail closed")


if __name__ == "__main__":
    test_nasa_adapter_is_strict_and_provenance_preserving()
    test_free_network_policy_cannot_spend_or_generate()
    test_plan_only_manifest_resolution_makes_zero_calls()
    test_precise_planet_queries_reach_nasa_and_are_not_duplicated()
    test_injection_precedes_stock_without_bypassing_pool()
    test_sealed_writer_evidence_is_required_before_render()
    test_mutated_claim_or_sealed_reference_drift_fails_closed()
    test_quality_session_blocker_or_topic_drift_fails_closed()
    print("quality_render_bridge tests: PASS")
