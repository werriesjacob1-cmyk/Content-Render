"""Content Render visual-director primitives.

This module is deliberately pure-stdlib and side-effect free.  It does not
fetch, generate, render, or publish media.  It converts story beats into a
machine-checkable visual contract and ranks *classes* of visual evidence
before any provider is called.

The governing rule is simple:

    show the real scientific thing/mechanism when we can;
    synthesize only what reality cannot show clearly.

Provider-specific download/generation code belongs elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Iterable, Mapping, Sequence


class VisualClass(str, Enum):
    AUTHENTIC_SCIENCE_VIDEO = "authentic_science_video"
    AUTHENTIC_ARCHIVE = "authentic_archive"
    SCIENTIFIC_VISUALIZATION = "scientific_visualization"
    MOLECULAR_RENDER = "molecular_render"
    PROGRAMMATIC_DIAGRAM = "programmatic_diagram"
    NORMAL_REAL_FOOTAGE = "normal_real_footage"
    VERIFIED_GENERATED_STILL = "verified_generated_still"
    IMAGE_TO_VIDEO = "image_to_video"
    GENERATED_VIDEO = "generated_video"
    GENERIC_STOCK = "generic_stock"


# Lower is better.  This ordering is intentionally *not* "AI-first".
BASE_PRIORITY: Mapping[VisualClass, int] = {
    VisualClass.AUTHENTIC_SCIENCE_VIDEO: 10,
    VisualClass.AUTHENTIC_ARCHIVE: 12,
    VisualClass.SCIENTIFIC_VISUALIZATION: 14,
    VisualClass.MOLECULAR_RENDER: 16,
    VisualClass.PROGRAMMATIC_DIAGRAM: 18,
    VisualClass.NORMAL_REAL_FOOTAGE: 30,
    VisualClass.VERIFIED_GENERATED_STILL: 42,
    VisualClass.IMAGE_TO_VIDEO: 46,
    VisualClass.GENERATED_VIDEO: 52,
    VisualClass.GENERIC_STOCK: 90,
}


@dataclass(frozen=True)
class RightsInfo:
    """Rights/provenance carried with every accepted asset."""

    source_name: str
    source_url: str
    license_name: str = ""
    license_url: str = ""
    public_domain: bool = False
    attribution_required: bool = False
    attribution_text: str = ""

    def is_usable(self) -> bool:
        # A source URL is mandatory.  Rights must be explicit: either public
        # domain or a named license.  "Government source" is not a license.
        return bool(self.source_name and self.source_url and
                    (self.public_domain or self.license_name))


@dataclass(frozen=True)
class SceneSpec:
    scene_id: str
    narration: str
    scientific_subject: str
    must_show: tuple[str, ...]
    mechanism: str = ""
    domain: str = ""
    authenticity_importance: int = 5  # 0..10
    motion_required: bool = False
    labels: tuple[str, ...] = ()
    forbidden_generic_substitutions: tuple[str, ...] = ()
    generated_visual_allowed: bool = True
    notes: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.scene_id.strip():
            errors.append("scene_id is required")
        if not self.narration.strip():
            errors.append("narration is required")
        if not self.scientific_subject.strip():
            errors.append("scientific_subject is required")
        if not self.must_show:
            errors.append("must_show must name at least one visible requirement")
        if not (0 <= int(self.authenticity_importance) <= 10):
            errors.append("authenticity_importance must be 0..10")
        if self.authenticity_importance >= 8 and not self.forbidden_generic_substitutions:
            errors.append(
                "high-authenticity scenes must explicitly forbid generic substitutions"
            )
        return errors


@dataclass(frozen=True)
class RouteOption:
    visual_class: VisualClass
    priority: int
    reason: str
    requires_vision_qa: bool = False
    requires_rights_check: bool = True


@dataclass(frozen=True)
class AssetCandidate:
    asset_id: str
    visual_class: VisualClass
    subject_terms: tuple[str, ...]
    relevance_score: float
    scientific_authenticity: float
    technical_quality: float
    rights: RightsInfo
    provenance_notes: str = ""
    is_generated: bool = False
    vision_verified: bool = False


@dataclass(frozen=True)
class RankedAsset:
    candidate: AssetCandidate
    score: float
    rejected_reason: str = ""


@dataclass(frozen=True)
class VisualPlan:
    scenes: tuple[SceneSpec, ...]
    routes: Mapping[str, tuple[RouteOption, ...]]

    def validate(self) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        for scene in self.scenes:
            errors.extend(f"{scene.scene_id}: {e}" for e in scene.validate())
            if scene.scene_id in seen:
                errors.append(f"duplicate scene_id: {scene.scene_id}")
            seen.add(scene.scene_id)
            if scene.scene_id not in self.routes:
                errors.append(f"{scene.scene_id}: missing route options")
        return errors


MOLECULAR_TERMS = {
    "molecule", "molecular", "protein", "enzyme", "receptor", "ligand", "dna",
    "rna", "amino acid", "compound", "chemical structure", "crystal structure",
}
SPACE_TERMS = {
    "planet", "star", "solar", "galaxy", "nebula", "asteroid", "comet",
    "orbit", "space", "moon", "sun", "black hole", "neutron star",
}
EARTH_TERMS = {
    "climate", "hurricane", "storm", "ocean", "atmosphere", "earthquake",
    "volcano", "satellite", "glacier", "wildfire", "tornado", "weather",
}
BIO_TERMS = {
    "cell", "organ", "brain", "heart", "lung", "animal", "plant", "microbe",
    "bacteria", "virus", "fungus", "tissue", "neuron", "blood", "immune",
}
PROGRAMMATIC_TERMS = {
    "scale", "compare", "comparison", "timeline", "sequence", "process",
    "force", "pressure", "orbit", "flow", "layer", "inside", "cross section",
    "how it works", "mechanism", "transformation", "before", "after",
}
ARCHIVE_TERMS = {
    "historical", "archive", "mission", "expedition", "discovered", "invented",
    "experiment", "launch", "apollo", "voyager",
}
GENERIC_VISUAL_WORDS = {
    "science", "technology", "research", "laboratory", "lab", "nature",
    "space footage", "scientist", "microscope",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%+\- ]+", " ", (text or "").lower())).strip()


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    t = f" {_norm(text)} "
    return any(f" {_norm(term)} " in t for term in terms)


def infer_domain(text: str) -> str:
    t = _norm(text)
    if _contains_any(t, MOLECULAR_TERMS):
        return "molecular"
    if _contains_any(t, SPACE_TERMS):
        return "space"
    if _contains_any(t, EARTH_TERMS):
        return "earth"
    if _contains_any(t, BIO_TERMS):
        return "biology"
    return "general"


def _subject_from_scene(scene: Mapping[str, object]) -> str:
    for key in ("scientific_subject", "subject", "visual_subject", "search_query"):
        value = str(scene.get(key, "") or "").strip()
        if value:
            return value
    narration = str(scene.get("voiceover", scene.get("narration", "")) or "")
    # A deterministic fallback is preferable to inventing a new entity.
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9+-]*", narration) if len(w) > 3]
    return " ".join(words[:6]) or "scene subject"


def _must_show_from_scene(scene: Mapping[str, object], subject: str) -> tuple[str, ...]:
    explicit = scene.get("must_show")
    if isinstance(explicit, (list, tuple)):
        cleaned = tuple(str(x).strip() for x in explicit if str(x).strip())
        if cleaned:
            return cleaned
    # search_query is existing manifest intent, so using it is not invention.
    query = str(scene.get("search_query", "") or "").strip()
    return (query or subject,)


def build_scene_spec(
    scene: Mapping[str, object],
    *,
    fact_domain: str = "",
    scene_index: int = 0,
) -> SceneSpec:
    narration = str(scene.get("voiceover", scene.get("narration", "")) or "").strip()
    subject = _subject_from_scene(scene)
    joined = " ".join(
        str(scene.get(k, "") or "")
        for k in ("voiceover", "narration", "search_query", "on_screen_text", "scientific_subject")
    )
    domain = (fact_domain or infer_domain(joined)).strip().lower()
    mechanism = str(scene.get("mechanism", "") or "").strip()
    if not mechanism and _contains_any(joined, PROGRAMMATIC_TERMS):
        mechanism = subject

    explicit_auth = scene.get("authenticity_importance")
    if explicit_auth is None:
        authenticity = 9 if domain in {"molecular", "space", "earth", "biology"} else 6
    else:
        try:
            authenticity = max(0, min(10, int(explicit_auth)))
        except (TypeError, ValueError):
            authenticity = 6

    forbidden = scene.get("forbidden_generic_substitutions")
    if isinstance(forbidden, (list, tuple)):
        forbidden_tuple = tuple(str(x).strip() for x in forbidden if str(x).strip())
    else:
        forbidden_tuple = ()
    if authenticity >= 8 and not forbidden_tuple:
        if domain == "molecular":
            forbidden_tuple = ("generic blue molecule", "generic laboratory glassware")
        elif domain == "space":
            forbidden_tuple = ("generic galaxy wallpaper", "unrelated telescope footage")
        elif domain == "earth":
            forbidden_tuple = ("generic landscape", "unrelated weather stock")
        elif domain == "biology":
            forbidden_tuple = ("generic scientist in lab", "unrelated microscope b-roll")

    labels_raw = scene.get("labels")
    labels = tuple(str(x).strip() for x in labels_raw if str(x).strip()) if isinstance(labels_raw, (list, tuple)) else ()

    scene_id = str(scene.get("id", "") or scene.get("scene_id", "") or f"scene_{scene_index + 1}")
    return SceneSpec(
        scene_id=scene_id,
        narration=narration,
        scientific_subject=subject,
        must_show=_must_show_from_scene(scene, subject),
        mechanism=mechanism,
        domain=domain,
        authenticity_importance=authenticity,
        motion_required=bool(scene.get("motion_required")) or _contains_any(joined, PROGRAMMATIC_TERMS),
        labels=labels,
        forbidden_generic_substitutions=forbidden_tuple,
        generated_visual_allowed=bool(scene.get("generated_visual_allowed", True)),
        notes=str(scene.get("visual_notes", "") or ""),
    )


def route_scene(spec: SceneSpec) -> tuple[RouteOption, ...]:
    """Return a deterministic, quality-first visual-class preference order."""

    errors = spec.validate()
    if errors:
        raise ValueError("; ".join(errors))

    text = " ".join((spec.scientific_subject, spec.narration, spec.mechanism, spec.domain))
    options: list[RouteOption] = []

    def add(vc: VisualClass, reason: str, *, delta: int = 0, vision: bool = False) -> None:
        if any(o.visual_class == vc for o in options):
            return
        options.append(RouteOption(
            visual_class=vc,
            priority=BASE_PRIORITY[vc] + delta,
            reason=reason,
            requires_vision_qa=vision,
            requires_rights_check=vc not in {
                VisualClass.PROGRAMMATIC_DIAGRAM,
                VisualClass.VERIFIED_GENERATED_STILL,
                VisualClass.IMAGE_TO_VIDEO,
                VisualClass.GENERATED_VIDEO,
            },
        ))

    molecular = spec.domain == "molecular" or _contains_any(text, MOLECULAR_TERMS)
    space = spec.domain == "space" or _contains_any(text, SPACE_TERMS)
    earth = spec.domain == "earth" or _contains_any(text, EARTH_TERMS)
    biology = spec.domain == "biology" or _contains_any(text, BIO_TERMS)
    programmatic = bool(spec.mechanism) or spec.motion_required or _contains_any(text, PROGRAMMATIC_TERMS)
    archive = _contains_any(text, ARCHIVE_TERMS)

    if molecular:
        add(VisualClass.MOLECULAR_RENDER, "real molecular/structure rendering is preferable to invented molecule imagery", delta=-8)
        add(VisualClass.SCIENTIFIC_VISUALIZATION, "use source-backed molecular or cellular visualization")
    if space or earth:
        add(VisualClass.AUTHENTIC_SCIENCE_VIDEO, "prefer observational or agency scientific media for this domain", delta=-4)
        add(VisualClass.SCIENTIFIC_VISUALIZATION, "use a real scientific simulation/visualization when mechanism is not directly observable")
    if biology and not molecular:
        add(VisualClass.AUTHENTIC_SCIENCE_VIDEO, "prefer real organism/anatomy/microscopy media", delta=-2)
        add(VisualClass.SCIENTIFIC_VISUALIZATION, "use source-backed anatomy or microscopy visualization")
    if archive:
        add(VisualClass.AUTHENTIC_ARCHIVE, "historical/mission claims should show authentic archive material", delta=-5)
    if programmatic:
        add(VisualClass.PROGRAMMATIC_DIAGRAM, "the narration describes a mechanism/scale/process that code can explain precisely", delta=-3)

    # Always allow relevant real footage, but never let it suppress scientific evidence.
    add(VisualClass.NORMAL_REAL_FOOTAGE, "use directly relevant real-world footage when it shows the narrated subject")

    if spec.generated_visual_allowed:
        add(VisualClass.VERIFIED_GENERATED_STILL, "generate a controllable still only when authentic/procedural visuals cannot show the idea", vision=True)
        if spec.motion_required:
            add(VisualClass.IMAGE_TO_VIDEO, "animate a vision-verified reference frame for controlled motion", vision=True)
        add(VisualClass.GENERATED_VIDEO, "free-form synthetic video is a selective fallback for otherwise unshowable scenes", vision=True)

    # Stock exists only as a last resort; high-authenticity scenes receive an
    # even larger penalty so it cannot win through mediocre relevance scores.
    stock_delta = 30 if spec.authenticity_importance >= 8 else 0
    add(VisualClass.GENERIC_STOCK, "generic stock is last resort and must still be subject-relevant", delta=stock_delta)

    return tuple(sorted(options, key=lambda o: (o.priority, o.visual_class.value)))


def build_visual_plan(manifest: Mapping[str, object], *, fact_domain: str = "") -> VisualPlan:
    raw_scenes = manifest.get("scenes")
    if not isinstance(raw_scenes, Sequence) or isinstance(raw_scenes, (str, bytes)):
        raise ValueError("manifest.scenes must be a sequence")
    scenes: list[SceneSpec] = []
    routes: dict[str, tuple[RouteOption, ...]] = {}
    for idx, raw in enumerate(raw_scenes):
        if not isinstance(raw, Mapping):
            raise ValueError(f"scene {idx + 1} must be an object")
        spec = build_scene_spec(raw, fact_domain=fact_domain, scene_index=idx)
        scenes.append(spec)
        routes[spec.scene_id] = route_scene(spec)
    plan = VisualPlan(tuple(scenes), routes)
    errors = plan.validate()
    if errors:
        raise ValueError("; ".join(errors))
    return plan


def _term_overlap(required: Sequence[str], candidate_terms: Sequence[str]) -> float:
    req_tokens = set(re.findall(r"[a-z0-9]+", _norm(" ".join(required))))
    cand_tokens = set(re.findall(r"[a-z0-9]+", _norm(" ".join(candidate_terms))))
    # Stopwords intentionally small: scientific nouns should survive.
    stop = {"the", "a", "an", "of", "to", "and", "in", "on", "with", "for", "from", "show"}
    req_tokens -= stop
    cand_tokens -= stop
    if not req_tokens:
        return 1.0
    return len(req_tokens & cand_tokens) / len(req_tokens)


def rank_asset_candidates(
    spec: SceneSpec,
    candidates: Sequence[AssetCandidate],
) -> tuple[RankedAsset, ...]:
    """Rank assets while failing closed on rights and unverified generation.

    Scores are diagnostic, not fake probabilities.
    """

    route_rank = {o.visual_class: idx for idx, o in enumerate(route_scene(spec))}
    ranked: list[RankedAsset] = []

    for c in candidates:
        reject = ""
        if not c.rights.is_usable() and not c.is_generated:
            reject = "rights/provenance incomplete"
        elif c.is_generated and not c.vision_verified:
            reject = "generated asset has not passed vision QA"

        overlap = _term_overlap(spec.must_show, c.subject_terms)
        if not reject and overlap <= 0.0:
            reject = "asset does not visibly cover any must_show requirement"

        route_position = route_rank.get(c.visual_class, 99)
        authenticity_weight = 2.2 if spec.authenticity_importance >= 8 else 1.3
        score = (
            100.0
            - 7.5 * route_position
            + 18.0 * max(0.0, min(1.0, c.relevance_score))
            + 14.0 * max(0.0, min(1.0, c.technical_quality))
            + 12.0 * authenticity_weight * max(0.0, min(1.0, c.scientific_authenticity))
            + 20.0 * overlap
        )

        # Strongly penalize known generic substitutions even if an upstream
        # stock search reports them as "relevant".
        hay = _norm(" ".join(c.subject_terms))
        if any(_norm(x) and _norm(x) in hay for x in spec.forbidden_generic_substitutions):
            reject = reject or "explicitly forbidden generic substitution"

        ranked.append(RankedAsset(c, round(score, 3), reject))

    # Accepted assets first, then quality score; rejected items remain visible
    # for diagnostics instead of disappearing silently.
    return tuple(sorted(
        ranked,
        key=lambda r: (bool(r.rejected_reason), -r.score, r.candidate.asset_id),
    ))


def choose_best_asset(spec: SceneSpec, candidates: Sequence[AssetCandidate]) -> AssetCandidate | None:
    for ranked in rank_asset_candidates(spec, candidates):
        if not ranked.rejected_reason:
            return ranked.candidate
    return None
