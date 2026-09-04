#!/usr/bin/env python3
"""Compatibility seam between the integrated quality stack and Writer V2.1.

The adapter is deliberately fail-closed at the convergence boundary: downstream
quality work may start only from a candidate that was accepted, structurally
valid, scored, AND explicitly marked as semantically verified by the takeover
runtime. Claude-era ``accepted=True`` alone is not sufficient.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence

import quality_session as QS
import quality_stack as Q
import generated_media_controller as GMC
import story_packet as SP

_NUMBER_WORD_RE = re.compile(r"\b(zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen|hundred|thousand|million|billion|trillion|twice|thrice|double|triple|quadruple|half|quarter)\b", re.I)
_DIGIT_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_UNIT_RE = re.compile(r"\b(kg|kilograms?|grams?|tons?|tonnes?|mm|cm|km|kilometers?|kilometres?|miles?|feet|foot|inch(?:es)?|meters?|metres?|seconds?|minutes?|hours?|days?|weeks?|months?|years?|degrees?|celsius|fahrenheit|ph|volts?|watts?|liters?|litres?|gallons?|mph|percent|%)\b", re.I)
_PROPER_RE = re.compile(r"\b[A-Z][A-Za-z0-9'.-]*(?:\s+[A-Z][A-Za-z0-9'.-]*){0,3}\b")
_TERM_STOP = {"that","this","these","those","with","from","your","into","than","then","have","has","had","will","would","could","should","about","their","them","they","there","here","when","while","because","even","just","also","only","actually","still","some","such","each","every","more","most","much","many","over","under","through","which","what","where","being","been","were","was"}


def _tokens(text: str) -> dict[str, list[str]]:
    text = str(text or "").replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    numbers = sorted(set(_DIGIT_NUMBER_RE.findall(text)) | {x.lower() for x in _NUMBER_WORD_RE.findall(text)})
    units = sorted({x.lower() for x in _UNIT_RE.findall(text)})
    entities = sorted({m.group(0).strip() for m in _PROPER_RE.finditer(text)})
    words = re.findall(r"[A-Za-z]{4,}", text.replace("'", "").lower())
    terms = sorted({w for w in words if w not in _TERM_STOP})
    return {"numbers": numbers, "units": units, "entities": entities, "terms": terms}


def _source_id(source_kind: str, source_ref: str) -> str:
    return "v21src_" + hashlib.sha256(f"{source_kind}\x1f{source_ref}".encode()).hexdigest()[:12]


def story_packet_from_v21_inventory(topic_id: str, inventory: Mapping[str, Any]) -> SP.StoryPacket:
    inventory = inventory or {}
    source_rows = {}
    claims = []
    for raw in inventory.get("claims") or []:
        if not isinstance(raw, Mapping): continue
        cid, text = str(raw.get("claim_id") or "").strip(), str(raw.get("claim_text") or "").strip()
        sk, sr = str(raw.get("source_kind") or "unknown").strip(), str(raw.get("source_ref") or "unknown").strip()
        if not cid or not text: continue
        sid, key = _source_id(sk, sr), (sk, sr)
        if key not in source_rows:
            source_rows[key] = SP.StorySource(sid, sk, sr, "", (text,))
        claims.append(SP.StoryClaim(cid, text, (sid,), str(raw.get("confidence") or "unknown"), tuple(str(x) for x in raw.get("allowed_numbers") or []), tuple(str(x) for x in raw.get("allowed_entities") or [])))
    mode = "writer_v21_grounded_dossier_text" if inventory.get("grounded") is True else "writer_v21_curated_inventory"
    packet = SP.StoryPacket(str(topic_id or "").strip(), tuple(claims), tuple(source_rows.values()), mode)
    errors = packet.validate()
    if errors: raise ValueError("invalid V2.1 story packet: " + "; ".join(errors))
    return packet


def v21_inventory_from_story_packet(packet: SP.StoryPacket, key_terms: Sequence[str] = ()) -> dict[str, Any]:
    errors = packet.validate()
    if errors: raise ValueError("invalid StoryPacket: " + "; ".join(errors))
    smap, claims = packet.source_map(), []
    for c in packet.claims:
        tok = _tokens(c.text)
        urls = [smap[sid].url for sid in c.source_ids if sid in smap and smap[sid].url]
        kinds = [smap[sid].source_type for sid in c.source_ids if sid in smap]
        source_kind = "grounded_story_packet" if any(k == "web" for k in kinds) else "curated_story_packet"
        claims.append({"claim_id":c.claim_id,"claim_text":c.text,"source_kind":source_kind,"source_ref":",".join(c.source_ids),"source_ids":list(c.source_ids),"source_urls":urls,"confidence":c.confidence,"allowed_numbers":list(c.allowed_numbers) or tok["numbers"],"allowed_units":tok["units"],"allowed_entities":list(c.allowed_named_entities) or tok["entities"],"allowed_terms":tok["terms"]})
    grounded = packet.grounding_mode == "grounded_web" or any(c["source_kind"] == "grounded_story_packet" for c in claims)
    return {"claims":claims,"key_terms":[str(x).strip() for x in key_terms if str(x).strip()],"grounded":grounded,"provenance_note":"exact source-backed StoryPacket claims" if grounded else "curated StoryPacket claims; no external grounding asserted"}


def accepted_traceability(debug: Mapping[str, Any] | None, manifest: Mapping[str, Any] | None = None) -> bool:
    """Require explicit takeover semantic proof; never infer it from acceptance."""
    if not isinstance(debug, Mapping) or not isinstance(manifest, Mapping):
        return False
    rounds = [r for r in (debug.get("rounds") or []) if isinstance(r, Mapping)]
    return bool(debug.get("accepted") is True and debug.get("validate_err") is None and isinstance(debug.get("score"), (int, float)) and manifest.get("_semantic_verified") is True and any(r.get("semantic_verified") is True for r in rounds))


def session_from_v21(manifest: Mapping[str, Any], claim_inventory: Mapping[str, Any], debug: Mapping[str, Any] | None, topic_id: str, policy: Q.QualityPolicy | None = None, generated_config: GMC.GeneratedMediaConfig | None = None) -> QS.QualitySessionPlan:
    packet = story_packet_from_v21_inventory(topic_id, claim_inventory)
    return QS.build_session_plan(manifest, packet, policy, generated_config, upstream_traceability_passed=accepted_traceability(debug, manifest))


def debug_traceability_summary(debug: Mapping[str, Any] | None, manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(debug, Mapping): return {"accepted":False,"rounds":[],"hard_total":0,"soft_total":0,"semantic_verified":False}
    rows=[]; hard_total=soft_total=0
    for raw in debug.get("rounds") or []:
        if not isinstance(raw, Mapping): continue
        violations=[v for v in raw.get("violations") or [] if isinstance(v, Mapping)]
        hard=sum(1 for v in violations if v.get("severity")=="hard"); soft=sum(1 for v in violations if v.get("severity")=="soft")
        hard_total+=hard; soft_total+=soft
        rows.append({"round":raw.get("round"),"semantic_verified":raw.get("semantic_verified") is True,"mechanical_hard_count":raw.get("mechanical_hard_count",0),"semantic_violation_count":raw.get("semantic_violation_count",0),"hard_count_from_payload":hard,"soft_count_from_payload":soft,"validate_err":raw.get("validate_err"),"score":raw.get("score"),"critic_avg":raw.get("critic_avg"),"repair_plan":raw.get("repair_plan")})
    accepted=accepted_traceability(debug, manifest)
    return {"accepted":accepted,"semantic_verified":accepted,"rounds":rows,"hard_total":hard_total,"soft_total":soft_total,"repair_rounds":debug.get("repair_rounds",0),"total_calls":debug.get("total_calls",0)}
