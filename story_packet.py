#!/usr/bin/env python3
"""Provider-neutral evidence packet between research, Writer V2 and visuals.

This module does not write prose. It turns research/base-fact evidence into stable
claim objects that any writer can cite by ID and any visual can carry forward as
`source_claim_ids`.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Mapping, Sequence

import research_grounding as RG


@dataclass(frozen=True)
class StorySource:
    source_id: str
    source_type: str  # web | curated_base_fact
    label: str
    url: str = ""
    excerpts: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoryClaim:
    claim_id: str
    text: str
    source_ids: tuple[str, ...]
    confidence: str
    allowed_numbers: tuple[str, ...] = ()
    allowed_named_entities: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoryPacket:
    topic_id: str
    claims: tuple[StoryClaim, ...]
    sources: tuple[StorySource, ...]
    grounding_mode: str

    def claim_map(self) -> dict[str, StoryClaim]:
        return {c.claim_id: c for c in self.claims}

    def source_map(self) -> dict[str, StorySource]:
        return {s.source_id: s for s in self.sources}

    def validate(self) -> list[str]:
        errors: list[str] = []
        smap = self.source_map()
        seen: set[str] = set()
        for claim in self.claims:
            if not claim.claim_id.strip():
                errors.append("claim_id required")
            if claim.claim_id in seen:
                errors.append(f"duplicate claim_id: {claim.claim_id}")
            seen.add(claim.claim_id)
            if not claim.text.strip():
                errors.append(f"{claim.claim_id}: claim text required")
            if not claim.source_ids:
                errors.append(f"{claim.claim_id}: source_ids required")
            for sid in claim.source_ids:
                if sid not in smap:
                    errors.append(f"{claim.claim_id}: unknown source_id {sid}")
        return errors

    def require_claim_ids(self, ids: Sequence[str]) -> tuple[StoryClaim, ...]:
        cmap = self.claim_map()
        out: list[StoryClaim] = []
        for raw in ids:
            cid = str(raw or "").strip()
            if not cid:
                continue
            if cid not in cmap:
                raise ValueError(f"unknown source_claim_id {cid}")
            if cmap[cid] not in out:
                out.append(cmap[cid])
        if not out:
            raise ValueError("at least one valid source_claim_id is required")
        return tuple(out)


def _stable(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(re.sub(r"\s+", " ", str(p or "")).strip().lower() for p in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def _numbers(text: str) -> tuple[str, ...]:
    """Literal numeric tokens a writer may reuse without inventing new magnitudes."""
    vals = re.findall(r"(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?(?:%|°[CF]?|x)?)(?![A-Za-z0-9])", text or "")
    return tuple(dict.fromkeys(vals))


def _named_entities(text: str) -> tuple[str, ...]:
    """Conservative multi-word proper names; intentionally avoids guessing nouns."""
    vals = re.findall(r"\b(?:[A-Z][A-Za-z0-9.-]+(?:\s+|$)){2,5}", text or "")
    return tuple(dict.fromkeys(re.sub(r"\s+", " ", v).strip(" .,") for v in vals if v.strip()))


def from_research(bundle: RG.ResearchBundle, topic_id: str) -> StoryPacket:
    if not isinstance(bundle, RG.ResearchBundle):
        raise TypeError("bundle must be research_grounding.ResearchBundle")
    source_map = bundle.source_map()
    sources = tuple(
        StorySource(
            source_id=s.source_id,
            source_type="web",
            label=s.title or s.url,
            url=s.url,
            excerpts=s.excerpts,
        )
        for s in bundle.sources if s.is_verifiable()
    )
    valid_source_ids = {s.source_id for s in sources}
    claims: list[StoryClaim] = []
    for c in bundle.load_bearing_claims():
        if not c.source_ids or not all(sid in valid_source_ids for sid in c.source_ids):
            continue
        claims.append(StoryClaim(
            claim_id=c.claim_id,
            text=c.text,
            source_ids=c.source_ids,
            confidence=c.confidence,
            allowed_numbers=_numbers(c.text),
            allowed_named_entities=_named_entities(c.text),
        ))
    packet = StoryPacket(str(topic_id or "").strip(), tuple(claims), sources, "grounded_web")
    errors = packet.validate()
    if errors:
        raise ValueError("invalid grounded story packet: " + "; ".join(errors))
    return packet


def from_curated_fact(fact: Mapping[str, object]) -> StoryPacket:
    """Build the honest fallback packet from the curated topic-bank fact itself.

    This is not represented as web-grounded. It merely makes the provenance
    explicit when external grounding is unavailable, matching Writer V2's
    fail-open-to-curated-base-fact design without pretending model memory is a
    source.
    """
    topic_id = str(fact.get("id") or "curated_fact").strip()
    sid = "base:" + topic_id
    source = StorySource(
        source_id=sid,
        source_type="curated_base_fact",
        label=f"curated topic bank fact {topic_id}",
    )
    fields: list[tuple[str, str]] = []
    for key in ("fact", "whatif", "wow"):
        value = str(fact.get(key) or "").strip()
        if value:
            fields.append((key, value))
    claims: list[StoryClaim] = []
    for key, text in fields:
        cid = _stable("claim", topic_id, key, text)
        claims.append(StoryClaim(
            claim_id=cid,
            text=text,
            source_ids=(sid,),
            confidence="curated-base-fact",
            allowed_numbers=_numbers(text),
            allowed_named_entities=_named_entities(text),
        ))
    packet = StoryPacket(topic_id, tuple(claims), (source,), "curated_base_fact")
    errors = packet.validate()
    if errors:
        raise ValueError("invalid curated story packet: " + "; ".join(errors))
    return packet


def writer_payload(packet: StoryPacket) -> dict:
    """Compact JSON-safe payload for V2/V2.1 without provider prose or mega-prompts."""
    errors = packet.validate()
    if errors:
        raise ValueError("invalid story packet: " + "; ".join(errors))
    return {
        "topic_id": packet.topic_id,
        "grounding_mode": packet.grounding_mode,
        "claims": [
            {
                "claim_id": c.claim_id,
                "claim_text": c.text,
                "source_ids": list(c.source_ids),
                "confidence": c.confidence,
                "allowed_numbers": list(c.allowed_numbers),
                "allowed_named_entities": list(c.allowed_named_entities),
            }
            for c in packet.claims
        ],
    }
