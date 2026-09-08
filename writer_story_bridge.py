#!/usr/bin/env python3
"""Bridge canonical Writer V2.1 claim inventory into the quality StoryPacket.

Writer V2.1 already owns the mechanical factual vocabulary and exact claim IDs
used by hook/beats/payoff. The quality stack must preserve those IDs verbatim;
generating a second set of semantically-similar claim IDs would sever the
traceability chain exactly where visuals begin.

This module is pure/zero-network. It does not invent evidence or upgrade source
provenance. Grounded-dossier entries retain the honest source kind/reference
available from Writer V2.1; curated base-fact entries remain curated base fact.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

import story_packet as SP


def _source_id(kind: str, ref: str) -> str:
    raw = f"{kind}\x1f{ref}".encode("utf-8")
    return "wsrc_" + hashlib.sha256(raw).hexdigest()[:12]


def _named_entities_from_allowed(raw: Mapping[str, Any]) -> tuple[str, ...]:
    vals = raw.get("allowed_entities") or []
    return tuple(dict.fromkeys(str(x).strip() for x in vals if str(x).strip()))


def _numbers_from_allowed(raw: Mapping[str, Any]) -> tuple[str, ...]:
    vals = raw.get("allowed_numbers") or []
    return tuple(dict.fromkeys(str(x).strip() for x in vals if str(x).strip()))


def from_writer_inventory(topic_id: str, inventory: Mapping[str, Any]) -> SP.StoryPacket:
    """Build a StoryPacket using Writer V2.1's exact claim IDs and text.

    ``inventory`` must be the direct output of ``writer_v2.build_claim_inventory``.
    No claim is paraphrased, merged, dropped because it is inconvenient, or
    assigned stronger provenance than Writer supplied.
    """
    if not isinstance(inventory, Mapping):
        raise TypeError("inventory must be a mapping")
    claims_raw = inventory.get("claims") or []
    if not isinstance(claims_raw, list):
        raise ValueError("writer claim inventory claims must be a list")

    sources_by_id: dict[str, SP.StorySource] = {}
    claims: list[SP.StoryClaim] = []
    seen_claims: set[str] = set()

    for raw in claims_raw:
        if not isinstance(raw, Mapping):
            raise ValueError("writer claim inventory contains non-object claim")
        cid = str(raw.get("claim_id") or "").strip()
        text = str(raw.get("claim_text") or "").strip()
        kind = str(raw.get("source_kind") or "").strip()
        ref = str(raw.get("source_ref") or "").strip()
        confidence = str(raw.get("confidence") or "").strip() or "unknown"
        if not cid or not text or not kind or not ref:
            raise ValueError("writer claim requires claim_id, claim_text, source_kind, source_ref")
        if cid in seen_claims:
            raise ValueError(f"duplicate writer claim_id {cid}")
        seen_claims.add(cid)

        sid = _source_id(kind, ref)
        if sid not in sources_by_id:
            source_type = "grounded_dossier" if kind == "grounded_dossier" else "curated_base_fact"
            sources_by_id[sid] = SP.StorySource(
                source_id=sid,
                source_type=source_type,
                label=f"Writer V2.1 {kind}: {ref}",
                url="",
                excerpts=(text,),
            )
        claims.append(SP.StoryClaim(
            claim_id=cid,
            text=text,
            source_ids=(sid,),
            confidence=confidence,
            allowed_numbers=_numbers_from_allowed(raw),
            allowed_named_entities=_named_entities_from_allowed(raw),
        ))

    grounding_mode = "grounded_writer_dossier" if inventory.get("grounded") is True else "curated_base_fact"
    packet = SP.StoryPacket(
        topic_id=str(topic_id or "").strip(),
        claims=tuple(claims),
        sources=tuple(sources_by_id.values()),
        grounding_mode=grounding_mode,
    )
    errors = packet.validate()
    if errors:
        raise ValueError("invalid Writer V2.1 StoryPacket bridge: " + "; ".join(errors))
    if not packet.claims:
        raise ValueError("Writer V2.1 StoryPacket bridge produced no claims")
    return packet


def manifest_claim_ids(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    """All claim IDs actually referenced by the canonical spoken manifest."""
    out: list[str] = []
    for raw in manifest.get("hook_source_claim_ids") or []:
        val = str(raw).strip()
        if val and val not in out:
            out.append(val)
    for scene in manifest.get("scenes") or []:
        if not isinstance(scene, Mapping):
            continue
        for raw in scene.get("source_claim_ids") or []:
            val = str(raw).strip()
            if val and val not in out:
                out.append(val)
    for raw in manifest.get("payoff_source_claim_ids") or []:
        val = str(raw).strip()
        if val and val not in out:
            out.append(val)
    return tuple(out)


def verify_manifest_refs(manifest: Mapping[str, Any], packet: SP.StoryPacket) -> tuple[bool, tuple[str, ...]]:
    """Fail closed if any spoken manifest reference is absent from the packet."""
    problems: list[str] = []
    if manifest.get("_semantic_verified") is not True:
        problems.append("manifest is not marked semantic_verified by canonical Writer V2.1")
    refs = manifest_claim_ids(manifest)
    if not refs:
        problems.append("manifest carries no source_claim_ids")
    cmap = packet.claim_map()
    for cid in refs:
        if cid not in cmap:
            problems.append(f"manifest references unknown Writer claim ID {cid}")
    return (not problems, tuple(dict.fromkeys(problems)))
