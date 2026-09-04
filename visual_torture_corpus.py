"""Deterministic pre-production visual torture corpus for Writer V2.1.

This is deliberately zero-network and is NOT script promotion evidence.  It
captures the minimum visible/mechanistic requirements for the five canonical
Writer torture topics so Visual Director changes cannot quietly regress to
wallpaper such as generic labs, generic galaxies, or generic landscapes.

The corpus contains no provider choices and does not render anything.  It
exercises the existing :mod:`visual_director` contract only.
"""
from __future__ import annotations

from typing import Mapping

from visual_director import SceneSpec


CANONICAL_VISUAL_TORTURE_CORPUS: Mapping[str, tuple[SceneSpec, ...]] = {
    "stomach_lining": (
        SceneSpec(
            scene_id="stomach_surface",
            narration="Show the stomach lining as the actual subject, not a generic medical lab.",
            scientific_subject="stomach lining gastric tissue",
            must_show=("stomach lining", "gastric tissue surface"),
            domain="biology",
            authenticity_importance=10,
            forbidden_generic_substitutions=(
                "generic scientist in lab",
                "generic microscope b-roll",
                "generic anatomy mannequin",
            ),
            generated_visual_allowed=True,
            notes="Prefer authentic endoscopy/histology or source-backed anatomy before synthetic imagery.",
        ),
        SceneSpec(
            scene_id="stomach_mechanism",
            narration="Make the protective lining mechanism visually understandable rather than merely naming it.",
            scientific_subject="stomach lining protective mechanism",
            must_show=("stomach lining layers", "protective surface mechanism"),
            mechanism="cross-section of the stomach lining protective surface",
            domain="biology",
            authenticity_importance=9,
            motion_required=True,
            forbidden_generic_substitutions=(
                "generic scientist in lab",
                "unrelated microscope b-roll",
            ),
            generated_visual_allowed=True,
        ),
    ),
    "neutron_star_spoon": (
        SceneSpec(
            scene_id="neutron_star_object",
            narration="Show a neutron star as the actual astronomical object before making a scale comparison.",
            scientific_subject="neutron star",
            must_show=("neutron star",),
            domain="space",
            authenticity_importance=10,
            forbidden_generic_substitutions=(
                "generic galaxy wallpaper",
                "unrelated telescope footage",
            ),
            generated_visual_allowed=True,
        ),
        SceneSpec(
            scene_id="neutron_star_scale",
            narration="Explain the comparison with a labeled scale graphic instead of an invented physical mechanism.",
            scientific_subject="neutron star matter scale comparison",
            must_show=("labeled scale comparison", "neutron star matter"),
            mechanism="scale comparison",
            domain="space",
            authenticity_importance=9,
            motion_required=True,
            labels=("comparison",),
            forbidden_generic_substitutions=(
                "generic galaxy wallpaper",
                "unrelated exploding star footage",
            ),
            generated_visual_allowed=True,
            notes="Programmatic comparison is preferred for quantitative scale; do not fabricate unseen star interiors.",
        ),
    ),
    "mauna_kea": (
        SceneSpec(
            scene_id="mauna_kea_real",
            narration="Establish Mauna Kea itself with authentic geographic imagery.",
            scientific_subject="Mauna Kea Hawaii",
            must_show=("Mauna Kea",),
            domain="earth",
            authenticity_importance=10,
            forbidden_generic_substitutions=(
                "generic landscape",
                "unrelated volcano stock",
            ),
            generated_visual_allowed=False,
        ),
        SceneSpec(
            scene_id="mauna_kea_cross_section",
            narration="Show the mountain as a labeled above-water and below-water cross-section so the scale claim is visible.",
            scientific_subject="Mauna Kea ocean floor cross section",
            must_show=("Mauna Kea", "sea surface", "submerged mountain"),
            mechanism="vertical cross-section and scale comparison",
            domain="earth",
            authenticity_importance=9,
            motion_required=True,
            labels=("sea surface", "submerged section"),
            forbidden_generic_substitutions=(
                "generic landscape",
                "unlabeled mountain silhouette",
            ),
            generated_visual_allowed=True,
        ),
    ),
    "chess_possible_games": (
        SceneSpec(
            scene_id="chess_board_real",
            narration="Anchor the abstraction in a real chessboard and legal-looking position rather than generic thinking footage.",
            scientific_subject="chess board position",
            must_show=("chess board", "chess pieces"),
            domain="general",
            authenticity_importance=7,
            forbidden_generic_substitutions=("person thinking", "generic computer code"),
            generated_visual_allowed=False,
        ),
        SceneSpec(
            scene_id="chess_branching",
            narration="Turn the combinatorial idea into an expanding branching diagram the viewer can follow.",
            scientific_subject="chess move branching",
            must_show=("chess move tree", "branching choices"),
            mechanism="branching sequence of possible chess moves",
            domain="general",
            authenticity_importance=7,
            motion_required=True,
            labels=("moves", "branches"),
            forbidden_generic_substitutions=("generic numbers animation", "person thinking"),
            generated_visual_allowed=True,
        ),
    ),
    "mantis_shrimp": (
        SceneSpec(
            scene_id="mantis_shrimp_real",
            narration="Show the actual mantis shrimp and striking appendage before any stylized explanation.",
            scientific_subject="mantis shrimp striking appendage",
            must_show=("mantis shrimp", "striking appendage"),
            domain="biology",
            authenticity_importance=10,
            motion_required=True,
            forbidden_generic_substitutions=(
                "generic tropical fish",
                "generic underwater reef",
                "generic scientist in lab",
            ),
            generated_visual_allowed=False,
        ),
        SceneSpec(
            scene_id="mantis_shrimp_mechanism",
            narration="Make the strike mechanism legible with source-backed high-speed imagery or a constrained explanatory diagram.",
            scientific_subject="mantis shrimp strike mechanism",
            must_show=("striking appendage motion", "impact sequence"),
            mechanism="high-speed strike sequence",
            domain="biology",
            authenticity_importance=10,
            motion_required=True,
            forbidden_generic_substitutions=(
                "generic tropical fish",
                "generic underwater reef",
                "unrelated slow-motion splash",
            ),
            generated_visual_allowed=True,
        ),
    ),
}


def validate_corpus() -> list[str]:
    """Return deterministic corpus errors; an empty list means structurally valid."""
    errors: list[str] = []
    expected = {
        "stomach_lining",
        "neutron_star_spoon",
        "mauna_kea",
        "chess_possible_games",
        "mantis_shrimp",
    }
    missing = expected - set(CANONICAL_VISUAL_TORTURE_CORPUS)
    extra = set(CANONICAL_VISUAL_TORTURE_CORPUS) - expected
    if missing:
        errors.append("missing canonical topics: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("unexpected canonical topics: " + ", ".join(sorted(extra)))

    seen_scene_ids: set[str] = set()
    for topic, scenes in CANONICAL_VISUAL_TORTURE_CORPUS.items():
        if len(scenes) < 2:
            errors.append(f"{topic}: must exercise both subject anchoring and mechanism/scale")
        for scene in scenes:
            errors.extend(f"{topic}/{scene.scene_id}: {e}" for e in scene.validate())
            if scene.scene_id in seen_scene_ids:
                errors.append(f"duplicate scene_id across corpus: {scene.scene_id}")
            seen_scene_ids.add(scene.scene_id)
    return errors
