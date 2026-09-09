#!/usr/bin/env python3
"""Deterministic visual-intent + continuity contract for one Content Render video.

The visual bible is planned before asset search. It tells the asset router what
each scene must *do* visually, gives recurring subjects stable IDs, and defines
continuity/reuse rules. It makes no provider calls and contains no factual claims
beyond the accepted manifest.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


class VisualIntent(str, Enum):
    HOOK_PROOF = "hook_proof"
    ORIENT = "orient"
    DEMONSTRATE = "demonstrate"
    REVEAL = "reveal"
    COMPARE = "compare"
    ESTABLISH_SCALE = "establish_scale"
    SHOW_CONSEQUENCE = "show_consequence"
    PROCESS = "process"
    CONTINUITY_BRIDGE = "continuity_bridge"
    PAYOFF_PROOF = "payoff_proof"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())).strip()


def _subject(scene: Mapping[str, Any]) -> str:
    for key in ("scientific_subject", "visual_subject", "subject", "search_query"):
        text = str(scene.get(key) or "").strip()
        if text:
            return text
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]+", str(scene.get("voiceover") or ""))
    return " ".join(words[:5]) or "scene subject"


def _subject_id(subject: str) -> str:
    norm = _norm(subject)
    stem = "_".join(norm.split()[:4]) or "subject"
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:6]
    return f"{stem}_{digest}"


def infer_visual_intent(scene: Mapping[str, Any], index: int, total: int) -> VisualIntent:
    role = str(scene.get("_v2_role") or "").lower()
    text = _norm(" ".join(str(scene.get(k) or "") for k in ("voiceover", "search_query", "on_screen_text")))
    if index == 0 or role == "hook":
        return VisualIntent.HOOK_PROOF
    if index == total - 1 or role == "payoff":
        return VisualIntent.PAYOFF_PROOF
    if any(x in text for x in ("compared", "versus", " vs ", "more than", "less than", "twice", "times")):
        return VisualIntent.COMPARE
    if any(x in text for x in ("million", "billion", "trillion", "scale", "size", "distance", "tiny", "huge")):
        return VisualIntent.ESTABLISH_SCALE
    if any(x in text for x in ("because", "process", "inside", "flows", "moves", "turns into", "converts", "mechanism")):
        return VisualIntent.PROCESS
    if any(x in text for x in ("causes", "means", "result", "consequence", "leads to", "so that")):
        return VisualIntent.SHOW_CONSEQUENCE
    if any(x in text for x in ("reveals", "actually", "instead", "but", "unexpected", "turns out")):
        return VisualIntent.REVEAL
    if index == 1:
        return VisualIntent.ORIENT
    return VisualIntent.DEMONSTRATE


@dataclass(frozen=True)
class SceneVisualContract:
    scene_id: str
    scene_index: int
    role: str
    intent: str
    subject_id: str
    subject: str
    must_show: tuple[str, ...]
    continuity_with: tuple[str, ...]
    preferred_camera_language: str
    preferred_source_family: str
    avoid: tuple[str, ...]


@dataclass(frozen=True)
class VisualBible:
    schema: str
    treatment: str
    typography_rule: str
    scale_rule: str
    recurring_subjects: Mapping[str, str]
    scenes: tuple[SceneVisualContract, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "treatment": self.treatment,
            "typography_rule": self.typography_rule,
            "scale_rule": self.scale_rule,
            "recurring_subjects": dict(self.recurring_subjects),
            "scenes": [asdict(x) for x in self.scenes],
        }

    def validate(self) -> list[str]:
        errors: list[str] = []
        ids: set[str] = set()
        for scene in self.scenes:
            if scene.scene_id in ids:
                errors.append(f"duplicate scene_id {scene.scene_id}")
            ids.add(scene.scene_id)
            if not scene.subject or not scene.subject_id:
                errors.append(f"{scene.scene_id}: missing stable subject")
            if not scene.intent:
                errors.append(f"{scene.scene_id}: missing visual intent")
            if not scene.must_show:
                errors.append(f"{scene.scene_id}: must_show empty")
        return errors


def _camera_for(intent: VisualIntent) -> str:
    return {
        VisualIntent.HOOK_PROOF: "immediate literal subject; decisive close/medium reveal; no abstract opener",
        VisualIntent.ORIENT: "stable establishing view that teaches where/what before motion",
        VisualIntent.DEMONSTRATE: "clear subject-following shot; motion only if it explains the claim",
        VisualIntent.REVEAL: "withhold secondary detail, then reveal the literal evidence cleanly",
        VisualIntent.COMPARE: "matched framing or split/graphic comparison with common scale",
        VisualIntent.ESTABLISH_SCALE: "anchored reference then controlled zoom/diagram; preserve scale semantics",
        VisualIntent.SHOW_CONSEQUENCE: "show the real downstream effect, not metaphorical reaction footage",
        VisualIntent.PROCESS: "directional/cross-section/process view; camera follows causal order",
        VisualIntent.CONTINUITY_BRIDGE: "reuse approved subject representation and camera axis",
        VisualIntent.PAYOFF_PROOF: "literal proof/reframe asset; strongest concrete image of the realization",
    }[intent]


def _source_family(intent: VisualIntent, subject: str) -> str:
    text = _norm(subject)
    if any(x in text for x in ("planet", "space", "star", "moon", "sun", "galaxy", "orbit")):
        return "authentic_science_space"
    if any(x in text for x in ("molecule", "protein", "chemical", "compound", "dna", "rna")):
        return "molecular_or_scientific_render"
    if intent in {VisualIntent.COMPARE, VisualIntent.ESTABLISH_SCALE, VisualIntent.PROCESS}:
        return "deterministic_explanatory"
    return "authentic_real_subject"


def build_visual_bible(manifest: Mapping[str, Any]) -> VisualBible:
    scenes = [s for s in (manifest.get("scenes") or []) if isinstance(s, Mapping)]
    treatment = str(manifest.get("treatment") or manifest.get("_v2_treatment") or "")
    subjects: dict[str, str] = {}
    prior_by_subject: dict[str, list[str]] = {}
    contracts: list[SceneVisualContract] = []
    for idx, scene in enumerate(scenes):
        sid = str(scene.get("id") or scene.get("scene_id") or idx + 1)
        subject = _subject(scene)
        subject_id = _subject_id(subject)
        subjects.setdefault(subject_id, subject)
        intent = infer_visual_intent(scene, idx, len(scenes))
        continuity = tuple(prior_by_subject.get(subject_id, [])[-2:])
        prior_by_subject.setdefault(subject_id, []).append(sid)
        explicit = scene.get("must_show")
        if isinstance(explicit, (list, tuple)):
            must_show = tuple(str(x).strip() for x in explicit if str(x).strip())
        else:
            query = str(scene.get("search_query") or "").strip()
            must_show = (query or subject,)
        avoid = (
            "metaphorical substitute for the literal scientific subject",
            "unrelated generic B-roll sharing only a modifier word",
            "new labels/text baked into generated media",
        )
        contracts.append(SceneVisualContract(
            scene_id=sid,
            scene_index=idx + 1,
            role=str(scene.get("_v2_role") or "scene"),
            intent=intent.value,
            subject_id=subject_id,
            subject=subject,
            must_show=must_show,
            continuity_with=continuity,
            preferred_camera_language=_camera_for(intent),
            preferred_source_family=_source_family(intent, subject),
            avoid=avoid,
        ))
    bible = VisualBible(
        schema="content-render-visual-bible-v1",
        treatment=treatment,
        typography_rule="captions/labels use renderer typography only; never rely on provider-baked explanatory text",
        scale_rule="when scale/comparison is claimed, preserve one common reference and never imply unsupported relative dimensions",
        recurring_subjects=subjects,
        scenes=tuple(contracts),
    )
    errors = bible.validate()
    if errors:
        raise ValueError("; ".join(errors))
    return bible


def write_visual_bible(manifest: Mapping[str, Any], path: str | Path) -> dict[str, Any]:
    bible = build_visual_bible(manifest)
    payload = bible.to_dict()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
