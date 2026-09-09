#!/usr/bin/env python3
"""S5/S6: the visual bible must STEER asset selection, not describe it afterwards.

A bible that is written to an evidence file and then ignored looks identical, in
every report, to one that governs routing -- both produce a visual_bible.json
with the right scene count. The only way to tell them apart is a counterfactual:
hold the narration byte-for-byte fixed, change a visual-bible field, and require
the planner's behaviour to change. If it does not, the bible is decoration.

Scope, stated honestly:
- PROVEN here for the production render path (quality_science_render), which
  applies the bible and feeds the directed copy to the Visual Director before any
  asset search.
- NOT proven by quality_downstream_factory_proof, which only WRITES the bible.
  That proof renders from synthetic scene files and performs no asset routing, so
  it has no selection for the bible to steer. Its visual_bible_scene_count is
  evidence that the bible was produced, not that it was obeyed.

Zero network, zero providers, no ffmpeg.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import quality_visual_bible as QVB
import visual_director as VD

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _manifest():
    return {
        "title": "The Mountain That Hides Its Own Height",
        "treatment": "revelation",
        "scenes": [
            {"id": "1", "voiceover": "Mauna Kea looks ordinary from the shore.",
             "search_query": "Mauna Kea Hawaii volcano", "_v2_role": "hook"},
            {"id": "2", "voiceover": "Most of it never breaks the surface.",
             "search_query": "underwater volcano slope", "_v2_role": "turn"},
            {"id": "3", "voiceover": "Measured from its base it out-tops Everest.",
             "search_query": "mountain height comparison diagram", "_v2_role": "escalation"},
            {"id": "4", "voiceover": "The tallest mountain on Earth is mostly ocean.",
             "search_query": "Mauna Kea summit above clouds", "_v2_role": "payoff"},
        ],
    }


def _narration(manifest):
    return [str(s.get("voiceover") or "") for s in manifest["scenes"]]


def _plan_from(manifest, bible):
    directed = QVB.apply_visual_bible(manifest, bible)
    return directed, VD.build_visual_plan(directed)


def _spec(plan, scene_id):
    return next(s for s in plan.scenes if s.scene_id == scene_id)


def test_the_bible_reaches_the_planner_at_all():
    m = _manifest()
    bible = QVB.build_visual_bible(m).to_dict()
    directed, plan = _plan_from(m, bible)
    spec = _spec(plan, "3")
    check(spec.must_show, "the planner's scene spec carries a must_show list")
    contract = next(r for r in bible["scenes"] if r["scene_id"] == "3")
    check(set(contract["must_show"]) <= set(spec.must_show),
          "the must_show the BIBLE specified is what the planner actually holds")
    check(spec.notes and "visual_intent=" in spec.notes,
          "the bible's intent reaches the planner as scene notes, not just the file")


def test_changing_must_show_changes_what_the_planner_requires():
    """The counterfactual. Narration is untouched; only the bible moves."""
    m = _manifest()
    base = QVB.build_visual_bible(m).to_dict()
    variant = copy.deepcopy(base)
    for row in variant["scenes"]:
        if row["scene_id"] == "3":
            row["must_show"] = ["submerged basalt flank", "seafloor base of the volcano"]

    d0, p0 = _plan_from(m, base)
    d1, p1 = _plan_from(m, variant)

    check(_narration(d0) == _narration(d1) == _narration(m),
          "narration is byte-identical across both arms -- only the bible differs")
    s0, s1 = _spec(p0, "3"), _spec(p1, "3")
    check(s0.must_show != s1.must_show,
          "a different bible must_show produces a different planner requirement")
    check("seafloor base of the volcano" in s1.must_show,
          "and it is the value the bible specified, not a re-derivation from narration")


def test_changing_must_show_changes_which_asset_WINS():
    """Requiring a different thing is only load-bearing if it picks differently."""
    m = _manifest()
    base = QVB.build_visual_bible(m).to_dict()
    variant = copy.deepcopy(base)
    for row in variant["scenes"]:
        if row["scene_id"] == "3":
            row["must_show"] = ["submerged basalt flank", "seafloor base"]

    rights = VD.RightsInfo(source_name="NOAA", source_url="https://example.invalid/a",
                           public_domain=True)

    def cand(asset_id, terms):
        return VD.AssetCandidate(
            asset_id=asset_id, visual_class=VD.VisualClass.AUTHENTIC_SCIENCE_VIDEO,
            subject_terms=tuple(terms), relevance_score=5.0,
            scientific_authenticity=5.0, technical_quality=5.0, rights=rights)

    pool = [
        cand("diagram", ["mountain", "height", "comparison", "diagram"]),
        cand("seafloor", ["submerged", "basalt", "flank", "seafloor", "base"]),
    ]

    winners = {}
    for tag, bible in (("base", base), ("variant", variant)):
        _, plan = _plan_from(m, bible)
        ranked = VD.rank_asset_candidates(_spec(plan, "3"), pool)
        alive = [r for r in ranked if not r.rejected_reason]
        check(alive, f"{tag}: at least one candidate survives rights screening")
        winners[tag] = alive[0].candidate.asset_id

    check(winners["base"] == "diagram",
          "under the derived bible the comparison diagram wins scene 3")
    check(winners["variant"] == "seafloor",
          "changing ONLY the bible's must_show changes the winning asset")


def test_the_intent_changes_the_route_not_just_the_text():
    """motion_required is set from intent and must reach routing behaviour."""
    m = _manifest()
    base = QVB.build_visual_bible(m).to_dict()
    still = copy.deepcopy(base)
    moving = copy.deepcopy(base)
    for row in still["scenes"]:
        if row["scene_id"] == "2":
            row["intent"] = QVB.VisualIntent.ORIENT.value
    for row in moving["scenes"]:
        if row["scene_id"] == "2":
            row["intent"] = QVB.VisualIntent.PROCESS.value

    d_still, _ = _plan_from(m, still)
    d_moving, _ = _plan_from(m, moving)
    check(_narration(d_still) == _narration(d_moving),
          "narration is fixed while the intent is varied")
    s_still = next(s for s in d_still["scenes"] if str(s["id"]) == "2")
    s_moving = next(s for s in d_moving["scenes"] if str(s["id"]) == "2")
    check(not s_still.get("motion_required") and s_moving.get("motion_required") is True,
          "a PROCESS intent demands motion where ORIENT does not -- the intent is "
          "a routing input, not a caption on the evidence file")


def test_the_same_bible_twice_is_identical():
    """Negative control: without this, any of the above could be nondeterminism."""
    m = _manifest()
    bible = QVB.build_visual_bible(m).to_dict()
    a, _ = _plan_from(m, bible)
    b, _ = _plan_from(m, copy.deepcopy(bible))
    check(json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True),
          "applying the same bible twice yields an identical directed manifest")


def test_applying_the_bible_never_edits_narration_or_claims():
    m = _manifest()
    m["scenes"][0]["source_claim_ids"] = ["claim-a"]
    before = copy.deepcopy(m)
    bible = QVB.build_visual_bible(m).to_dict()
    directed = QVB.apply_visual_bible(m, bible)
    check(m == before, "apply_visual_bible does not mutate the manifest it is given")
    check(_narration(directed) == _narration(before),
          "the directed copy carries the accepted narration unchanged")
    check(directed["scenes"][0].get("source_claim_ids") == ["claim-a"],
          "sealed source-claim identity survives visual direction untouched")


def test_the_render_path_applies_the_bible_BEFORE_asset_resolution():
    """Order is the whole property: applied after routing would prove nothing."""
    src = (ROOT / "quality_science_render.py").read_text(encoding="utf-8")
    apply_at = src.find("apply_visual_bible(")
    plan_at = src.find("plan_manifest(")
    resolve_at = src.find("resolve_manifest_assets(")
    check(apply_at > 0 and plan_at > 0 and resolve_at > 0,
          "the render path still applies the bible, plans motion and resolves assets")
    check(apply_at < plan_at and apply_at < resolve_at,
          "the bible is applied BEFORE motion planning and before asset resolution")
    directed_calls = re.findall(r"(plan_manifest|resolve_manifest_assets)\((\w+)", src)
    for fn, arg in directed_calls:
        check(arg == "directed_manifest",
              f"{fn} is fed the visual-directed manifest, not the raw one "
              "(feeding the raw manifest would silently un-steer routing)")


def test_the_factory_proof_does_not_overclaim_the_bible():
    """It writes the bible; it routes no assets. Say so rather than imply more."""
    src = (ROOT / "quality_downstream_factory_proof.py").read_text(encoding="utf-8")
    check("write_visual_bible(" in src,
          "the factory proof records the visual bible")
    check("apply_visual_bible(" not in src,
          "the factory proof does NOT claim to apply it -- it renders from fixed "
          "scene files and has no asset selection for a bible to steer")


if __name__ == "__main__":
    test_the_bible_reaches_the_planner_at_all()
    test_changing_must_show_changes_what_the_planner_requires()
    test_changing_must_show_changes_which_asset_WINS()
    test_the_intent_changes_the_route_not_just_the_text()
    test_the_same_bible_twice_is_identical()
    test_applying_the_bible_never_edits_narration_or_claims()
    test_the_render_path_applies_the_bible_BEFORE_asset_resolution()
    test_the_factory_proof_does_not_overclaim_the_bible()
    print("visual intent load-bearing tests: PASS")
