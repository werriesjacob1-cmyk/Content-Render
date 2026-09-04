"""Deterministic editorial/retention diagnostics for Writer V2.1.

These diagnostics are deliberately NON-GATING. They surface patterns a human
short-form editor should inspect after factual/semantic validation:
- repeated premise instead of beat-to-beat information gain;
- payoff that merely restates the hook;
- monotone or overly long spoken sentences;
- generic AI moralizing / universalized endings;
- repeated or generic visual intents that would become B-roll wallpaper.

The module does not attempt to predict virality or fabricate a probability of
success. It preserves raw overlap/novelty evidence for human judgment and future
real retention data.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


STOP = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "he", "her", "hers", "him", "his", "how", "i", "if", "in", "into", "is",
    "it", "its", "just", "may", "more", "most", "not", "of", "on", "or", "our",
    "out", "over", "she", "so", "some", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "to", "too", "under",
    "up", "was", "we", "were", "what", "when", "where", "which", "while", "who",
    "why", "will", "with", "would", "you", "your",
}

GENERIC_VISUAL_TERMS = {
    "science", "scientist", "scientists", "lab", "laboratory", "technology",
    "nature", "space", "microscope", "research", "experiment", "abstract",
    "background", "cinematic", "dramatic", "stock", "animation", "footage",
}

# Small, high-precision telemetry list from repeatedly observed weak short-form
# endings. This is not a banned-phrase gate; it is an editorial warning.
AI_MORALIZING_PATTERNS = (
    r"\bremind(?:s|ing)? us that\b",
    r"\bdanger (?:often )?hides in plain sight\b",
    r"\beverything you (?:know|thought)\b",
    r"\bchanges everything\b",
    r"\bthe scale of reality itself\b",
    r"\bnature(?:'s| is) (?:ultimate|greatest|most)\b",
    r"\bwe are only beginning to understand\b",
    r"\bmore than meets the eye\b",
    r"\bthe universe (?:is|can be) stranger\b",
)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value: Any) -> set[str]:
    words = re.findall(r"[a-z0-9]+(?:['’-][a-z0-9]+)?", _text(value).lower())
    return {w.replace("’", "'") for w in words if len(w) > 2 and w not in STOP}


def _word_count(value: Any) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", _text(value)))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _novelty(current: set[str], prior: set[str]) -> float:
    if not current:
        return 0.0
    return len(current - prior) / len(current)


def _visual_text(scene: Mapping[str, Any]) -> str:
    return _text(
        scene.get("visual_intent")
        or scene.get("search_query")
        or scene.get("scientific_subject")
        or ""
    )


def editorial_diagnostics(
    *,
    hook: str,
    beats: Sequence[str],
    payoff: str,
    scenes: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return retention/editorial evidence without accepting/rejecting script."""
    hook = _text(hook)
    beats = [_text(x) for x in beats]
    payoff = _text(payoff)
    lines = [hook, *beats, payoff]
    line_tokens = [_tokens(x) for x in lines]

    warnings: list[dict[str, Any]] = []
    novelty_rows: list[dict[str, Any]] = []
    prior: set[str] = set()
    for idx, tokens in enumerate(line_tokens):
        novelty = _novelty(tokens, prior)
        novelty_rows.append({
            "beat_index": idx,
            "content_token_count": len(tokens),
            "new_content_ratio": round(novelty, 3),
        })
        # Hook has no prior content. For subsequent lines, very low new-content
        # ratio is a warning that the script may be rephrasing rather than moving.
        if idx > 0 and len(tokens) >= 3 and novelty < 0.30:
            warnings.append({
                "kind": "low_information_gain",
                "beat_index": idx,
                "value": round(novelty, 3),
                "detail": "fewer than 30% of content tokens are new versus earlier lines",
            })
        prior |= tokens

    adjacent_overlap: list[dict[str, Any]] = []
    for idx in range(1, len(line_tokens)):
        overlap = _jaccard(line_tokens[idx - 1], line_tokens[idx])
        adjacent_overlap.append({"from": idx - 1, "to": idx, "jaccard": round(overlap, 3)})
        if overlap >= 0.60:
            warnings.append({
                "kind": "adjacent_repetition",
                "beat_index": idx,
                "value": round(overlap, 3),
                "detail": "adjacent spoken lines reuse unusually similar content vocabulary",
            })

    hook_payoff_overlap = _jaccard(line_tokens[0], line_tokens[-1]) if lines else 0.0
    if hook_payoff_overlap >= 0.55:
        warnings.append({
            "kind": "payoff_restates_hook",
            "beat_index": len(lines) - 1,
            "value": round(hook_payoff_overlap, 3),
            "detail": "payoff is lexically close to the hook instead of delivering a fresh reframe",
        })

    word_counts = [_word_count(x) for x in lines]
    for idx, count in enumerate(word_counts):
        if count > 24:
            warnings.append({
                "kind": "spoken_sentence_too_long",
                "beat_index": idx,
                "value": count,
                "detail": "single spoken line exceeds 24 words and may sound written rather than spoken",
            })
    if len(word_counts) >= 4 and max(word_counts) - min(word_counts) <= 3:
        warnings.append({
            "kind": "monotone_sentence_rhythm",
            "beat_index": None,
            "value": list(word_counts),
            "detail": "nearly every line has the same word count; spoken cadence may feel templated",
        })

    moralizing_hits: list[dict[str, Any]] = []
    for idx, line in enumerate(lines):
        for pattern in AI_MORALIZING_PATTERNS:
            match = re.search(pattern, line, flags=re.I)
            if match:
                hit = {"beat_index": idx, "text": match.group(0), "pattern": pattern}
                moralizing_hits.append(hit)
                warnings.append({
                    "kind": "generic_ai_moralizing",
                    "beat_index": idx,
                    "value": match.group(0),
                    "detail": "generic universalized phrasing can weaken a specific science payoff",
                })

    visual_rows: list[dict[str, Any]] = []
    previous_visual_tokens: set[str] | None = None
    visual_intents = list(scenes or [])
    for idx, scene in enumerate(visual_intents, 1):
        visual = _visual_text(scene)
        tokens = _tokens(visual)
        generic_only = bool(tokens) and tokens.issubset(GENERIC_VISUAL_TERMS)
        overlap = _jaccard(previous_visual_tokens or set(), tokens) if previous_visual_tokens is not None else 0.0
        row = {
            "scene_index": idx,
            "visual_intent": visual,
            "content_tokens": sorted(tokens),
            "generic_only": generic_only,
            "previous_scene_overlap": round(overlap, 3),
        }
        visual_rows.append(row)
        if not visual or generic_only:
            warnings.append({
                "kind": "generic_or_missing_visual_intent",
                "beat_index": idx,
                "value": visual,
                "detail": "scene lacks a specific visible subject/mechanism and risks B-roll wallpaper",
            })
        if previous_visual_tokens is not None and tokens and overlap >= 0.65:
            warnings.append({
                "kind": "visual_subject_repetition",
                "beat_index": idx,
                "value": round(overlap, 3),
                "detail": "adjacent scenes are visually too similar for a purposeful pattern interrupt",
            })
        previous_visual_tokens = tokens

    return {
        "hook_word_count": word_counts[0] if word_counts else 0,
        "line_word_counts": word_counts,
        "beat_information_gain": novelty_rows,
        "adjacent_content_overlap": adjacent_overlap,
        "hook_payoff_overlap": round(hook_payoff_overlap, 3),
        "generic_ai_moralizing_hits": moralizing_hits,
        "visual_intents": visual_rows,
        "warnings": warnings,
        "warning_kinds": sorted({w["kind"] for w in warnings}),
        "gating": False,
        "human_review_questions": [
            "Would the first 1–2 seconds make a cold viewer need the next sentence?",
            "Does every beat add a new fact, mechanism, scale change, or reversal?",
            "Would a smart human actually say these sentences aloud?",
            "Does the visual plan show the narrated thing rather than decorate it?",
            "Does the payoff answer the opening with a specific reframe instead of a generic moral?",
        ],
    }
