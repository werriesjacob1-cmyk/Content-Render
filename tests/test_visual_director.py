#!/usr/bin/env python3
"""Zero-network tests for visual_director.py."""\nimport os\nimport sys\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n
from visual_director import (
    AssetCandidate,
    RightsInfo,
    SceneSpec,
    VisualClass,
    build_scene_spec,
    build_visual_plan,
    choose_best_asset,
    rank_asset_candidates,
    route_scene,
)


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_routes():
    mol = SceneSpec(
        scene_id="1",
        narration="This protein changes shape when the ligand binds.",
        scientific_subject="protein ligand binding",
        must_show=("protein ligand binding",),
        mechanism="conformational change",
        domain="molecular",
        authenticity_importance=10,
        motion_required=True,
        forbidden_generic_substitutions=("generic blue molecule",),
    )
    routes = route_scene(mol)
    classes = [r.visual_class for r in routes]
    check(classes[0] == VisualClass.MOLECULAR_RENDER, "molecular render outranks synthetic imagery")
    check(classes.index(VisualClass.PROGRAMMATIC_DIAGRAM) < classes.index(VisualClass.GENERATED_VIDEO),
          "programmatic mechanism outranks free-form AI video")
    check(classes[-1] == VisualClass.GENERIC_STOCK, "generic stock is last resort")

    space = SceneSpec(
        scene_id="2",
        narration="A neutron star bends spacetime around it.",
        scientific_subject="neutron star",
        must_show=("neutron star",),
        mechanism="gravity and scale",
        domain="space",
        authenticity_importance=9,
        motion_required=True,
        forbidden_generic_substitutions=("generic galaxy wallpaper",),
    )
    sclasses = [r.visual_class for r in route_scene(space)]
    check(sclasses[0] == VisualClass.AUTHENTIC_SCIENCE_VIDEO,
          "space scene prefers authentic scientific media")
    check(sclasses.index(VisualClass.SCIENTIFIC_VISUALIZATION) < sclasses.index(VisualClass.GENERATED_VIDEO),
          "scientific visualization beats generated video")


def test_manifest_plan_and_inference():
    manifest = {
        "scenes": [
            {
                "id": 1,
                "voiceover": "Inside the hurricane, warm ocean water feeds the storm.",
                "search_query": "hurricane satellite storm eye",
                "on_screen_text": "THE ENGINE",
            },
            {
                "id": 2,
                "voiceover": "Now compare the storm's width with the state below it.",
                "search_query": "hurricane scale comparison",
                "motion_required": True,
            },
        ]
    }
    plan = build_visual_plan(manifest)
    check(not plan.validate(), "generated visual plan is valid")
    check(plan.scenes[0].domain == "earth", "earth domain inferred")
    check(plan.scenes[0].authenticity_importance >= 8, "scientific scene gets high authenticity")
    check(bool(plan.scenes[0].forbidden_generic_substitutions),
          "high-authenticity scene explicitly forbids generic substitutes")
    r2 = [x.visual_class for x in plan.routes["2"]]
    check(VisualClass.PROGRAMMATIC_DIAGRAM in r2, "scale comparison gets deterministic diagram route")


def test_validation_fails_closed():
    bad = SceneSpec(
        scene_id="x",
        narration="Something happens.",
        scientific_subject="thing",
        must_show=(),
        authenticity_importance=9,
        forbidden_generic_substitutions=(),
    )
    errors = bad.validate()
    check(any("must_show" in e for e in errors), "scene without visible requirement rejected")
    check(any("forbid" in e for e in errors), "high-authenticity scene without explicit generic ban rejected")


def _rights(name="NASA SVS"):
    return RightsInfo(
        source_name=name,
        source_url="https://example.test/source",
        license_name="public-domain",
        public_domain=True,
    )


def test_asset_ranking_and_fail_closed():
    spec = SceneSpec(
        scene_id="3",
        narration="Satellite observations reveal the hurricane eye.",
        scientific_subject="hurricane eye",
        must_show=("hurricane eye",),
        domain="earth",
        authenticity_importance=10,
        forbidden_generic_substitutions=("generic landscape", "unrelated weather stock"),
    )
    authentic = AssetCandidate(
        asset_id="nasa:1",
        visual_class=VisualClass.AUTHENTIC_SCIENCE_VIDEO,
        subject_terms=("hurricane eye satellite",),
        relevance_score=.90,
        scientific_authenticity=1.0,
        technical_quality=.80,
        rights=_rights(),
    )
    pretty_ai = AssetCandidate(
        asset_id="ai:1",
        visual_class=VisualClass.GENERATED_VIDEO,
        subject_terms=("hurricane eye cinematic",),
        relevance_score=1.0,
        scientific_authenticity=.4,
        technical_quality=1.0,
        rights=RightsInfo(source_name="generated", source_url="internal://generated", license_name="generated"),
        is_generated=True,
        vision_verified=True,
    )
    unverified_ai = AssetCandidate(
        asset_id="ai:2",
        visual_class=VisualClass.GENERATED_VIDEO,
        subject_terms=("hurricane eye",),
        relevance_score=1.0,
        scientific_authenticity=.8,
        technical_quality=1.0,
        rights=RightsInfo(source_name="generated", source_url="internal://generated", license_name="generated"),
        is_generated=True,
        vision_verified=False,
    )
    no_rights = AssetCandidate(
        asset_id="archive:bad",
        visual_class=VisualClass.AUTHENTIC_ARCHIVE,
        subject_terms=("hurricane eye",),
        relevance_score=1.0,
        scientific_authenticity=1.0,
        technical_quality=1.0,
        rights=RightsInfo(source_name="mystery", source_url="https://example.test/no-license"),
    )
    ranked = rank_asset_candidates(spec, [pretty_ai, authentic, unverified_ai, no_rights])
    check(ranked[0].candidate.asset_id == "nasa:1", "authentic scientific asset beats prettier synthetic clip")
    reasons = {r.candidate.asset_id: r.rejected_reason for r in ranked}
    check("vision QA" in reasons["ai:2"], "unverified generated media rejected")
    check("rights" in reasons["archive:bad"], "asset with incomplete rights rejected")
    check(choose_best_asset(spec, [unverified_ai, no_rights]) is None,
          "no acceptable asset fails closed rather than picking junk")


def test_build_scene_spec_does_not_invent():
    raw = {
        "id": 7,
        "voiceover": "The object crosses the membrane.",
        "search_query": "cell membrane transport",
    }
    spec = build_scene_spec(raw)
    check(spec.must_show == ("cell membrane transport",),
          "existing manifest visual intent becomes must_show")
    check("Empire State Building" not in spec.scientific_subject,
          "director does not invent decorative comparison targets")


if __name__ == "__main__":
    test_routes()
    test_manifest_plan_and_inference()
    test_validation_fails_closed()
    test_asset_ranking_and_fail_closed()
    test_build_scene_spec_does_not_invent()
    print("visual_director tests: PASS")
