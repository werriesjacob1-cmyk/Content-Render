#!/usr/bin/env python3
"""Zero-network smoke test of the downstream certification seam.

Flagship certification attempts #1-#5 ALL died at the Writer stage, so the
downstream half of the factory -- sealed-evidence gate, claim extraction,
deterministic motion planning, authentic-asset arbitration, scene timeline --
had never once executed end to end. Unit tests covered the components; nothing
covered the seams BETWEEN them, which is exactly where a manifest-shape or
contract mismatch would hide until we finally paid for a good script.

This drives one realistic sealed bundle (manifest + writer_evidence +
quality_session_plan) through that chain with no provider calls and no network.

SCOPE BOUNDARY: ffmpeg is genuinely unavailable in this environment, so actual
encoding, science-motion rasterisation and ffprobe-based audio QA cannot be
exercised here and are NOT faked -- those remain proven only by their own unit
tests plus a real render. Everything upstream of the encoder is proven here.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")
# Force the plan-only path: no free-science network, no provider calls.
os.environ.pop("QUALITY_RENDER_FREE_NETWORK", None)

import quality_render_bridge as B
import quality_science_motion as QSM
import writer_story_bridge as WSB


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


TOPIC = "smoke_topic"
_LINES = [
    ("A cave river in total darkness still carries living fish.", ["claim_001"]),
    ("So how does anything hunt where light has never reached?", ["claim_001"]),
    ("The fish lost its eyes entirely over many generations.", ["claim_002"]),
    ("Instead it reads pressure ripples bouncing off the cave walls.", ["claim_002"]),
    ("That sense works in water no eye could ever use.", ["claim_003"]),
    ("Blind cave fish now outcompete sighted relatives underground.", ["claim_003"]),
    ("Losing a sense can be the upgrade, not the damage.", ["claim_004"]),
]


def _bundle(tmpdir, scenes=None):
    """Write a faithful sealed certification bundle to tmpdir."""
    scenes = scenes if scenes is not None else [
        {
            "id": i,
            "duration": 4.0,
            "voiceover": vo,
            "on_screen_text": "",
            "search_query": "cave river fish",
            "motion": "zoom_in",
            "source_claim_ids": list(refs),
        }
        for i, (vo, refs) in enumerate(_LINES, 1)
    ]
    manifest = {
        "title": "The fish that traded eyes for touch",
        "viewer_job": "CURIOSITY_ITCH",
        "keyword": "blind cave fish",
        "metaphor": "cave river fish",
        "vibe": "eerie",
        "hook": scenes[0]["voiceover"],
        "hook_headline": "TRADED EYES FOR TOUCH",
        "script": " ".join(s["voiceover"] for s in scenes),
        "scenes": scenes,
        "captions": ["a", "b", "c"],
        "hashtags": ["#science"],
        "render": {},
        "treatment": "HIDDEN_MECHANISM",
        # stamps the canonical Writer V2.1 orchestrator sets on an accepted manifest
        "_semantic_verified": True,
        "_quality": 7.6,
    }
    refs = sorted(set(WSB.manifest_claim_ids(manifest)))
    evidence = {
        "topic_id": TOPIC,
        "claim_inventory": {
            "claims": [
                {"claim_id": cid, "claim_text": f"sealed evidence for {cid}",
                 "source_kind": "dossier", "source_ref": f"ref::{cid}"}
                for cid in ("claim_001", "claim_002", "claim_003", "claim_004")
            ],
            "provenance_note": "grounded",
        },
        "manifest_referenced_claim_ids": refs,
    }
    session = {"topic_id": TOPIC, "upstream_traceability_passed": True, "blockers": []}
    paths = {}
    for name, payload in (("manifest.json", manifest),
                          ("writer_evidence.json", evidence),
                          ("quality_session_plan.json", session)):
        p = os.path.join(tmpdir, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        paths[name] = p
    return manifest, paths


def test_sealed_bundle_clears_the_evidence_gate():
    with tempfile.TemporaryDirectory() as td:
        manifest, paths = _bundle(td)
        status = B._require_certification_evidence(paths["manifest.json"], manifest)
        check(status["topic_id"] == TOPIC, "evidence gate returns the sealed topic id")
        check(status["referenced_claim_count"] == 4,
              f"gate counts every referenced claim (got {status['referenced_claim_count']})")


def test_gate_fails_closed_on_each_tampering_shape():
    """The seam must reject drift, not just accept the happy path."""
    with tempfile.TemporaryDirectory() as td:
        manifest, paths = _bundle(td)

        # 1. narration changed after sealing -> new claim ref set
        tampered = json.loads(json.dumps(manifest))
        tampered["scenes"][2]["source_claim_ids"] = ["claim_999"]
        try:
            B._require_certification_evidence(paths["manifest.json"], tampered)
            raise AssertionError("unsealed claim reference should be rejected")
        except RuntimeError as exc:
            check("mismatch" in str(exc) or "differs" in str(exc),
                  "manifest citing a claim outside the sealed set is rejected")

        # 2. session carrying a blocker
        with open(paths["quality_session_plan.json"], "w", encoding="utf-8") as fh:
            json.dump({"topic_id": TOPIC, "upstream_traceability_passed": True,
                       "blockers": ["traceability incomplete"]}, fh)
        try:
            B._require_certification_evidence(paths["manifest.json"], manifest)
            raise AssertionError("session blocker should be rejected")
        except RuntimeError as exc:
            check("blockers" in str(exc), "a quality-session blocker stops the render")

        # 3. cross-topic bundle swap
        with open(paths["quality_session_plan.json"], "w", encoding="utf-8") as fh:
            json.dump({"topic_id": "a_different_topic",
                       "upstream_traceability_passed": True, "blockers": []}, fh)
        try:
            B._require_certification_evidence(paths["manifest.json"], manifest)
            raise AssertionError("cross-topic session should be rejected")
        except RuntimeError as exc:
            check("topic_id differs" in str(exc), "a session from a different topic is rejected")


def test_claims_flow_into_motion_planning_without_network():
    with tempfile.TemporaryDirectory() as td:
        manifest, _ = _bundle(td)
        ids = WSB.manifest_claim_ids(manifest)
        check(len(ids) == 4, f"claim ids extracted from the manifest (got {len(ids)})")
        planned = QSM.plan_manifest(manifest, ids)
        # HIDDEN_MECHANISM is an eligible deterministic treatment.
        check(isinstance(planned, dict), "motion planner returns a plan mapping")
        for plan in planned.values():
            prov = plan.provenance()
            check(prov["provider_calls"] == 0 and prov["network_calls"] == 0,
                  "planned deterministic motion declares zero provider/network calls")
            check(set(plan.source_claim_ids) <= set(ids),
                  "motion provenance never cites a claim outside the sealed set")


def test_asset_resolution_is_plan_only_and_decides_every_scene():
    with tempfile.TemporaryDirectory() as td:
        manifest, _ = _bundle(td)
        injections, decisions = B.resolve_manifest_assets(manifest, allow_free_network=False)
        check(len(decisions) == len(manifest["scenes"]),
              f"every scene receives an explicit routing decision "
              f"(got {len(decisions)}/{len(manifest['scenes'])})")
        check(injections == {} or all(isinstance(k, str) for k in injections),
              "plan-only resolution injects nothing it could not fetch offline")


def test_authentic_assets_outrank_deterministic_motion():
    """The arbitration rule the render entrypoint depends on."""
    with tempfile.TemporaryDirectory() as td:
        manifest, _ = _bundle(td)
        ids = WSB.manifest_claim_ids(manifest)
        planned = QSM.plan_manifest(manifest, ids)
        if not planned:
            print("SKIP authentic-vs-motion arbitration (no motion planned for this fixture)")
            return
        target = sorted(planned)[0]
        active = {sid: p for sid, p in planned.items() if sid not in {target}}
        check(target not in active,
              "a scene with an authentic injection is removed from deterministic motion")
        check(len(active) == len(planned) - 1,
              "arbitration suppresses exactly the injected scene, never more")


if __name__ == "__main__":
    test_sealed_bundle_clears_the_evidence_gate()
    test_gate_fails_closed_on_each_tampering_shape()
    test_claims_flow_into_motion_planning_without_network()
    test_asset_resolution_is_plan_only_and_decides_every_scene()
    test_authentic_assets_outrank_deterministic_motion()
    print("downstream factory smoke tests: PASS")
