#!/usr/bin/env python3
"""Normalize provider-specific media into Visual Director AssetCandidate objects.

This is the adapter seam between retrieval/generation tools and one ranking policy.
Providers no longer get to define their own notion of 'good enough'.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence
import urllib.parse

import visual_director as VD
import molecular_media as MM
import vision_gateway as VG


def nasa_svs_asset(row: Mapping[str, object], subject_terms: Sequence[str], *, relevance_score: float = 0.85, technical_quality: float = 0.85) -> VD.AssetCandidate:
    """Convert scientific_media.svs_candidates() output to the shared contract."""
    asset_id = str(row.get("id") or "").strip()
    media_url = str(row.get("url") or "").strip()
    page_url = str(row.get("page_url") or media_url).strip()
    if not asset_id.startswith("svs:") or not media_url or not page_url:
        raise ValueError("invalid NASA SVS candidate")
    desc = str(row.get("desc") or "").strip()
    return VD.AssetCandidate(
        asset_id=asset_id,
        visual_class=VD.VisualClass.AUTHENTIC_SCIENCE_VIDEO,
        subject_terms=tuple(str(x).strip() for x in subject_terms if str(x).strip()) or (desc[:160] or "NASA scientific visualization",),
        relevance_score=max(0.0, min(1.0, float(relevance_score))),
        scientific_authenticity=1.0,
        technical_quality=max(0.0, min(1.0, float(technical_quality))),
        rights=VD.RightsInfo(
            source_name="NASA Scientific Visualization Studio",
            source_url=page_url,
            license_name="NASA media usage guidelines",
            license_url="https://www.nasa.gov/nasa-brand-center/images-and-media/",
            public_domain=False,
            attribution_required=False,
            attribution_text="NASA Scientific Visualization Studio",
        ),
        provenance_notes=f"authentic NASA SVS source; media={media_url}; {desc[:300]}",
    )


def pubchem_asset(resolved_name: str, image_path: str, *, relevance_score: float = 0.95, technical_quality: float = 0.95) -> VD.AssetCandidate:
    """Normalize an exact PubChem structure depiction after successful retrieval.

    PubChem's own PUG notice says the NLM/U.S. Government software/database is
    freely available for public use/reproduction. We preserve that wording as the
    usage basis instead of over-claiming that every downstream PubChem record is
    generically 'public domain'.
    """
    name = str(resolved_name or "").strip()
    path = str(image_path or "").strip()
    if not name or not path:
        raise ValueError("resolved PubChem name and image path are required")
    source_url = "https://pubchem.ncbi.nlm.nih.gov/compound/" + urllib.parse.quote(name, safe="")
    return VD.AssetCandidate(
        asset_id="pubchem:" + name.lower().replace(" ", "_"),
        visual_class=VD.VisualClass.MOLECULAR_RENDER,
        subject_terms=(name, "chemical structure"),
        relevance_score=max(0.0, min(1.0, float(relevance_score))),
        scientific_authenticity=1.0,
        technical_quality=max(0.0, min(1.0, float(technical_quality))),
        rights=VD.RightsInfo(
            source_name="PubChem / National Library of Medicine",
            source_url=source_url,
            license_name="NLM/U.S. Government unrestricted use and reproduction notice",
            license_url="https://pubchem.ncbi.nlm.nih.gov/pug/",
            public_domain=False,
            attribution_required=False,
            attribution_text=f"PubChem structure depiction: {name}",
        ),
        provenance_notes=f"exact PubChem PUG-REST structure depiction; local_image={path}",
    )


def rcsb_asset(entry: MM.PDBEntry, subject_terms: Sequence[str], *, relevance_score: float = 0.9, technical_quality: float = 0.95) -> VD.AssetCandidate:
    """Normalize an experimental RCSB PDB structure into the shared contract."""
    if not isinstance(entry, MM.PDBEntry):
        raise TypeError("entry must be molecular_media.PDBEntry")
    return VD.AssetCandidate(
        asset_id=f"rcsb:{entry.pdb_id}",
        visual_class=VD.VisualClass.MOLECULAR_RENDER,
        subject_terms=tuple(str(x).strip() for x in subject_terms if str(x).strip()) or (entry.title,),
        relevance_score=max(0.0, min(1.0, float(relevance_score))),
        scientific_authenticity=1.0,
        technical_quality=max(0.0, min(1.0, float(technical_quality))),
        rights=VD.RightsInfo(
            source_name=f"RCSB PDB {entry.pdb_id}",
            source_url=entry.structure_url,
            license_name=entry.license_name,
            license_url=entry.license_url,
            public_domain=entry.public_domain,
            attribution_required=False,
            attribution_text=entry.attribution(),
        ),
        provenance_notes=(
            f"experimental structure; methods={','.join(entry.experimental_methods)}; "
            f"coordinates={entry.coordinate_url}; citation={entry.primary_citation_doi or entry.pdb_doi}"
        ),
    )


def science_motion_asset(asset_id: str, subject_terms: Sequence[str], claim_ids: Sequence[str], *, technical_quality: float = 1.0) -> VD.AssetCandidate:
    """Represent a deterministic claim-bound graphic after its render succeeds."""
    claims = tuple(str(x).strip() for x in claim_ids if str(x).strip())
    if not claims:
        raise ValueError("science motion asset requires source claim IDs")
    return VD.AssetCandidate(
        asset_id=str(asset_id).strip(),
        visual_class=VD.VisualClass.PROGRAMMATIC_DIAGRAM,
        subject_terms=tuple(str(x).strip() for x in subject_terms if str(x).strip()),
        relevance_score=1.0,
        scientific_authenticity=0.95,
        technical_quality=max(0.0, min(1.0, float(technical_quality))),
        rights=VD.RightsInfo(
            source_name="Content Render deterministic science motion",
            source_url="internal://science-motion",
            license_name="generated-from-cited-claims",
            public_domain=False,
        ),
        provenance_notes="source_claim_ids=" + ",".join(claims),
        is_generated=False,
        vision_verified=True,
    )


def generated_asset(
    asset_id: str,
    visual_class: VD.VisualClass,
    subject_terms: Sequence[str],
    provider_reference: str,
    *,
    relevance_score: float = 1.0,
    scientific_authenticity: float = 0.45,
    technical_quality: float = 1.0,
    vision_verified: bool = False,
) -> VD.AssetCandidate:
    if visual_class not in {
        VD.VisualClass.VERIFIED_GENERATED_STILL,
        VD.VisualClass.IMAGE_TO_VIDEO,
        VD.VisualClass.GENERATED_VIDEO,
    }:
        raise ValueError("generated_asset requires a generated visual class")
    if not str(provider_reference).strip():
        raise ValueError("provider_reference is required")
    return VD.AssetCandidate(
        asset_id=str(asset_id).strip(),
        visual_class=visual_class,
        subject_terms=tuple(str(x).strip() for x in subject_terms if str(x).strip()),
        relevance_score=max(0.0, min(1.0, float(relevance_score))),
        scientific_authenticity=max(0.0, min(1.0, float(scientific_authenticity))),
        technical_quality=max(0.0, min(1.0, float(technical_quality))),
        rights=VD.RightsInfo(
            source_name="generated media",
            source_url=str(provider_reference).strip(),
            license_name="generated-output",
        ),
        provenance_notes="generated candidate; independent vision QA required before eligibility",
        is_generated=True,
        vision_verified=bool(vision_verified),
    )


def apply_vision_verdict(candidate: VD.AssetCandidate, verdict: VG.VisionVerdict | None) -> VD.AssetCandidate:
    """A provider score alone cannot approve generated media; use full mechanical verdict."""
    if not candidate.is_generated:
        return candidate
    approved = bool(verdict and verdict.production_eligible)
    return replace(
        candidate,
        vision_verified=approved,
        provenance_notes=(candidate.provenance_notes + (
            f"; vision={verdict.provider}/{verdict.model}:{verdict.score}:{verdict.reason}" if verdict else "; vision=unavailable"
        )),
    )


def choose_for_scene(spec: VD.SceneSpec, candidates: Sequence[VD.AssetCandidate]) -> VD.AssetCandidate | None:
    """One ranking/gating authority for authentic, deterministic, and generated media."""
    return VD.choose_best_asset(spec, list(candidates))
