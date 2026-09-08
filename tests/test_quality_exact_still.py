#!/usr/bin/env python3
"""Zero-network regressions for quality_exact_still.py."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_exact_still as E
import visual_director as VD


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _spec():
    return VD.SceneSpec(
        scene_id="2",
        narration="This is the exact molecular structure of dopamine.",
        scientific_subject="dopamine molecule",
        must_show=("dopamine", "molecular structure"),
        domain="chemistry",
        authenticity_importance=10,
        forbidden_generic_substitutions=("generic lab glassware",),
    )


def _pubchem(path):
    return VD.AssetCandidate(
        asset_id="pubchem:dopamine",
        visual_class=VD.VisualClass.MOLECULAR_RENDER,
        subject_terms=("dopamine", "chemical structure"),
        relevance_score=0.95,
        scientific_authenticity=1.0,
        technical_quality=0.95,
        rights=VD.RightsInfo(
            source_name="PubChem / National Library of Medicine",
            source_url="https://pubchem.ncbi.nlm.nih.gov/compound/dopamine",
            license_name="NLM/U.S. Government unrestricted use and reproduction notice",
            attribution_text="PubChem structure depiction: dopamine",
        ),
        provenance_notes=f"exact PubChem PUG-REST structure depiction; local_image={path}",
    )


def test_only_exact_pubchem_local_still_is_promoted():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "dopamine.png"
        path.write_bytes(b"x" * 200)
        inj = E.from_candidate(_pubchem(str(path)), _spec())
        check(inj is not None and inj.asset_id == "pubchem:dopamine",
              "exact local PubChem structure is eligible")
        check(inj.scientific_authenticity == 1.0 and inj.source_name.startswith("PubChem"),
              "scientific authenticity and provenance survive promotion")

        missing = E.from_candidate(_pubchem(str(path) + ".missing"), _spec())
        check(missing is None, "missing local image cannot be promoted")

        generated = VD.AssetCandidate(
            asset_id="generated:dopamine",
            visual_class=VD.VisualClass.MOLECULAR_RENDER,
            subject_terms=("dopamine",), relevance_score=1.0,
            scientific_authenticity=1.0, technical_quality=1.0,
            rights=VD.RightsInfo(source_name="PubChem / National Library of Medicine", source_url="x", license_name="x"),
            provenance_notes=f"local_image={path}", is_generated=True, vision_verified=True,
        )
        check(E.from_candidate(generated, _spec()) is None,
              "generated image cannot masquerade as exact PubChem still")

        rcsb = VD.AssetCandidate(
            asset_id="rcsb:1ABC", visual_class=VD.VisualClass.MOLECULAR_RENDER,
            subject_terms=("protein",), relevance_score=1.0,
            scientific_authenticity=1.0, technical_quality=1.0,
            rights=VD.RightsInfo(source_name="RCSB PDB 1ABC", source_url="x", license_name="CC0"),
            provenance_notes=f"local_image={path}",
        )
        check(E.from_candidate(rcsb, _spec()) is None,
              "RCSB coordinates are not falsely treated as an already-rendered still")


def test_legacy_compositor_path_preserves_existing_scene_contract():
    with tempfile.TemporaryDirectory() as td:
        image = Path(td) / "dopamine.png"
        image.write_bytes(b"x" * 200)
        inj = E.from_candidate(_pubchem(str(image)), _spec())
        calls = []

        class FakeLegacy:
            WORK = td
            PROFILE = {"zoom_speed": 0.001, "grade": ",eq=contrast=1.05"}
            _last_motion_kind = None
            ARCHIVAL_SCENES = 0

            @staticmethod
            def _motion_filter(scene, frames, zspeed, idx=0, prev_kind=None):
                check(frames == 120 and idx == 2, "exact still uses spoken scene duration for motion frames")
                return ",scale=1080:1920"

            @staticmethod
            def _stat_overlay(scene, seg_dur):
                return ""

            @staticmethod
            def run(cmd):
                calls.append(cmd)

        scene = {"motion": "zoom_in", "voiceover": "This is dopamine.", "search_query": "dopamine molecule"}
        out = E.render_with_legacy_compositor(FakeLegacy, scene, 2, "voice.mp3", 4.0, inj)
        check(out.endswith("s2.mp4") and len(calls) == 1, "exact still returns normal legacy scene output path")
        cmd = calls[0]
        check("-loop" in cmd and str(image) in cmd and "voice.mp3" in cmd,
              "exact still compositor uses image + original narration audio")
        check(FakeLegacy.ARCHIVAL_SCENES == 1 and FakeLegacy._last_motion_kind == "zoom_in",
              "existing renderer accounting and motion continuity are preserved")


if __name__ == "__main__":
    test_only_exact_pubchem_local_still_is_promoted()
    test_legacy_compositor_path_preserves_existing_scene_contract()
    print("quality_exact_still tests: PASS")
