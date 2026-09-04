#!/usr/bin/env python3
"""Zero-network integration regressions for quality_stack.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_stack as Q
import quality_runtime as QR
import visual_director as VD
import vision_gateway as VG
import asset_gateway as AG
import molecular_media as MM


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_registry_is_complete_and_safe():
    Q.assert_safe_defaults()
    status = Q.integration_status()
    required = {
        "you_grounded_research", "compound_mini_research", "visual_director",
        "nasa_svs", "pubchem", "rcsb_molecular", "existing_real_footage",
        "science_motion", "still_model_lab", "fal_video_lab", "qwen_asset_vision",
        "gemini_asset_vision", "voice_lab", "sound_brain", "video_repair",
        "final_video_qa", "writer_v2",
    }
    check(required <= set(status), "registry contains every current quality lane")
    missing = [m for m in Q.required_module_names() if not __import__(m)]
    check(not missing, "all non-writer integration modules import successfully")
    check(status["writer_v2"]["module_present"] in {True, False}, "writer V2 slot is optional until Claude lands it")
    check(not any("publish" in x or "publer" in x or "release" in x for x in status),
          "quality registry contains no publishing path")


def test_visual_priority_is_reality_first():
    molecular = Q.tools_for_visual_class(VD.VisualClass.MOLECULAR_RENDER)
    names = [x["tool"] for x in molecular]
    check(names[:3] == ["rcsb_molecular", "pubchem", "science_motion"],
          "molecular scenes try authentic structure/deterministic visuals before AI")

    generated = Q.tools_for_visual_class(VD.VisualClass.GENERATED_VIDEO)
    check(generated[0]["tool"] == "fal_video_lab", "generated-video route uses guarded model lab")
    check(any(x["tool"] == "qwen_asset_vision" for x in generated),
          "generated video requires independent Qwen vision lane")
    check(not generated[0]["permitted_now"], "generated video is disabled by zero-spend default policy")


def test_plan_only_end_to_end_contract():
    manifest = {
        "title": "Protein switch",
        "scenes": [
            {
                "id": 1,
                "voiceover": "This protein changes shape when a ligand binds.",
                "search_query": "protein ligand binding molecular structure",
                "motion_required": True,
            },
            {
                "id": 2,
                "voiceover": "That shape change exposes a new binding surface.",
                "search_query": "protein conformational change binding surface",
            },
        ],
    }
    plan = Q.build_quality_plan(manifest)
    check(plan["provider_calls_made"] == 0, "planning makes zero provider calls")
    check(plan["publishing_enabled"] is False, "integration plan cannot publish")
    check(plan["policy"]["plan_only"] is True, "plan-only is the default execution mode")
    check(len(plan["scenes"]) == 2, "visual director produced a scene contract for every beat")
    all_provider_rows = [p for s in plan["scenes"] for r in s["routes"] for p in r["provider_sequence"]]
    check(all(not row["permitted_now"] for row in all_provider_rows if row["requires_network"] or row["may_cost_money"]),
          "network/paid providers are blocked by default")


def test_vision_gateway_fails_closed_without_key():
    old = os.environ.pop("GROQ_API_KEY", None)
    try:
        check(VG.qwen_asset_verdict("real mantis shrimp", [b"fakejpeg"]) is None,
              "Qwen asset verifier does not run or approve without a key")
    finally:
        if old is not None:
            os.environ["GROQ_API_KEY"] = old
    bad = VG.VisionVerdict(9, True, False, False, False, False, "broken anatomy")
    check(not bad.production_eligible, "high score cannot override anatomy failure")
    good = VG.VisionVerdict(8, True, True, False, False, False, "clean literal match")
    check(good.production_eligible, "clean independently verified asset can become eligible")


def test_asset_gateway_unifies_providers():
    nasa = AG.nasa_svs_asset({
        "id": "svs:42",
        "url": "https://svs.gsfc.nasa.gov/vis/a000000/a000000/movie.mp4",
        "page_url": "https://svs.gsfc.nasa.gov/42/",
        "desc": "Satellite visualization of a hurricane eye",
    }, ["hurricane eye", "satellite"])
    check(nasa.visual_class == VD.VisualClass.AUTHENTIC_SCIENCE_VIDEO,
          "NASA candidate becomes authentic-science AssetCandidate")
    check(nasa.rights.is_usable(), "NASA asset carries explicit source/usage provenance")

    pubchem = AG.pubchem_asset("dopamine", "/tmp/dopamine.png")
    check(pubchem.visual_class == VD.VisualClass.MOLECULAR_RENDER,
          "PubChem depiction enters the same molecular asset class")
    check(pubchem.rights.is_usable() and not pubchem.rights.public_domain,
          "PubChem usage basis is explicit without over-claiming public-domain status")

    entry = MM.PDBEntry(
        pdb_id="1ABC",
        title="Example ligand-bound protein",
        experimental_methods=("X-RAY DIFFRACTION",),
        primary_citation_title="Example structure",
        primary_citation_authors=("A. Scientist",),
        primary_citation_year=2024,
        primary_citation_doi="10.0000/example",
        pdb_doi="10.2210/pdb1abc/pdb",
        latest_revision_date="2026-01-01",
        structure_url="https://www.rcsb.org/structure/1ABC",
        view3d_url="https://www.rcsb.org/3d-view/1ABC",
        coordinate_url="https://files.rcsb.org/download/1ABC.cif",
    )
    pdb = AG.rcsb_asset(entry, ["ligand-bound protein"])
    check(pdb.visual_class == VD.VisualClass.MOLECULAR_RENDER and pdb.rights.public_domain,
          "RCSB structure becomes CC0 molecular AssetCandidate")

    gen = AG.generated_asset(
        "fal:test", VD.VisualClass.GENERATED_VIDEO, ["mantis shrimp"],
        "https://fal.example/result/123", vision_verified=False,
    )
    check(gen.is_generated and not gen.vision_verified, "generated result starts unverified")
    rejected = AG.apply_vision_verdict(gen, VG.VisionVerdict(10, True, False, False, False, False, "wrong anatomy"))
    check(not rejected.vision_verified, "perfect numeric score cannot bypass anatomy gate")
    approved = AG.apply_vision_verdict(gen, VG.VisionVerdict(9, True, True, False, False, False, "clean"))
    check(approved.vision_verified, "full independent verdict can promote generated asset to ranking eligibility")

    spec = VD.SceneSpec(
        scene_id="x", narration="Satellite observations reveal the hurricane eye.",
        scientific_subject="hurricane eye", must_show=("hurricane eye",), domain="earth",
        authenticity_importance=10, forbidden_generic_substitutions=("generic storm stock",),
    )
    pretty_ai = AG.generated_asset(
        "ai:pretty", VD.VisualClass.GENERATED_VIDEO, ["hurricane eye"],
        "https://generated.example/a", relevance_score=1.0, technical_quality=1.0,
        scientific_authenticity=0.4, vision_verified=True,
    )
    winner = AG.choose_for_scene(spec, [pretty_ai, nasa])
    check(winner is not None and winner.asset_id == "svs:42",
          "one shared ranker chooses authentic science over prettier synthetic media")


def test_runtime_policy_and_authentic_resolution():
    spec = VD.SceneSpec(
        scene_id="storm", narration="A satellite view reveals the hurricane eye.",
        scientific_subject="hurricane eye satellite", must_show=("hurricane eye",),
        domain="earth", authenticity_importance=10,
        forbidden_generic_substitutions=("generic storm clouds",),
    )
    local_plan = QR.plan_scene(spec)
    check(local_plan["provider_calls_made"] == 0, "runtime planner itself is zero-call")
    check(not local_plan["generated_escalation_tools"], "default runtime exposes no paid AI escalation")

    old = QR.SM.svs_candidates
    calls = {"n": 0}
    def fake_svs(query, used_ids=(), limit=3):
        calls["n"] += 1
        return [{
            "id": "svs:storm",
            "url": "https://svs.gsfc.nasa.gov/movie.mp4",
            "page_url": "https://svs.gsfc.nasa.gov/storm/",
            "desc": "NASA satellite hurricane eye visualization",
        }]
    QR.SM.svs_candidates = fake_svs
    try:
        free_policy = Q.QualityPolicy(plan_only=False, allow_network=True)
        result = QR.resolve_authentic_scene(spec, free_policy)
    finally:
        QR.SM.svs_candidates = old
    check(calls["n"] == 1 and result.provider_calls_made == 1,
          "explicit free-network policy can execute authentic NASA retrieval")
    check(result.winner is not None and result.winner.asset_id == "svs:storm",
          "authentic resolver normalizes and selects NASA result")
    check(not result.generated_escalation_tools,
          "successful authentic resolution suppresses generated escalation")

    ai_policy = Q.QualityPolicy(
        plan_only=False, allow_network=True, allow_paid=True, allow_generated_visuals=True,
    )
    check(QR.generated_escalation_tools(ai_policy) == ("still_model_lab", "fal_video_lab"),
          "generated lanes become eligible only when paid generation and independent vision are permitted")
    no_network_ai = Q.QualityPolicy(
        plan_only=False, allow_network=False, allow_paid=True, allow_generated_visuals=True,
    )
    check(not QR.generated_escalation_tools(no_network_ai),
          "generation cannot become eligible without a working independent vision backend")


if __name__ == "__main__":
    test_registry_is_complete_and_safe()
    test_visual_priority_is_reality_first()
    test_plan_only_end_to_end_contract()
    test_vision_gateway_fails_closed_without_key()
    test_asset_gateway_unifies_providers()
    test_runtime_policy_and_authentic_resolution()
    print("quality_stack tests: PASS")
