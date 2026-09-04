"""Non-gating hook-surface separation and payoff-proof diagnostics for Writer V2.1.

A short-form video's spoken hook, cover headline, first-frame visual, and payoff
are four separate jobs. This module detects when they collapse into duplicate
text/ideas or when the payoff fails to resolve the opening curiosity.

No acceptance/rejection decision is made here; output is evidence for bakeoff
and human editorial review.
"""
from __future__ import annotations

import re
from typing import Any, Mapping


STOP = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by", "can",
    "could", "did", "do", "does", "for", "from", "had", "has", "have", "how",
    "if", "in", "into", "is", "it", "its", "just", "of", "on", "or", "so",
    "that", "the", "their", "then", "there", "this", "to", "too", "was", "we",
    "were", "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your",
}

GENERIC_FIRST_FRAME = {
    "science", "lab", "laboratory", "scientist", "research", "space", "stars",
    "technology", "abstract", "background", "cinematic", "dramatic", "person",
    "thinking", "microscope", "nature", "stock", "footage",
}

GENERIC_PAYOFF_PATTERNS = (
    r"\bchanges everything\b",
    r"\bmore than meets the eye\b",
    r"\bremind(?:s|ing)? us that\b",
    r"\bdanger (?:often )?hides in plain sight\b",
    r"\bthe universe (?:is|can be) stranger\b",
    r"\bwe are only beginning to understand\b",
)

RESOLUTION_CUES = re.compile(
    r"\b(?:because|which means|that means|so |therefore|turns out|actually|instead|the reason|the answer|what matters|this happens|that happens)\b",
    re.I,
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value: Any) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+(?:['’-][a-z0-9]+)?", _clean(value).lower())
        if len(w) > 2 and w not in STOP
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def hook_surface_report(
    *,
    spoken_hook: str,
    cover_headline: str,
    first_frame_visual: str,
    on_screen_hook_text: str = "",
) -> dict[str, Any]:
    """Measure whether four hook surfaces are coordinated without duplication."""
    spoken_hook = _clean(spoken_hook)
    cover_headline = _clean(cover_headline)
    first_frame_visual = _clean(first_frame_visual)
    on_screen_hook_text = _clean(on_screen_hook_text)

    spoken = _tokens(spoken_hook)
    cover = _tokens(cover_headline)
    onscreen = _tokens(on_screen_hook_text)
    visual = _tokens(first_frame_visual)

    spoken_cover = _jaccard(spoken, cover)
    spoken_onscreen = _jaccard(spoken, onscreen) if onscreen else None
    cover_onscreen = _jaccard(cover, onscreen) if onscreen else None
    visual_overlap = _jaccard(spoken | cover, visual)
    visual_generic_only = bool(visual) and visual.issubset(GENERIC_FIRST_FRAME)

    warnings: list[str] = []
    if spoken_cover >= 0.70:
        warnings.append("cover_repeats_spoken_hook")
    if spoken_onscreen is not None and spoken_onscreen >= 0.80:
        warnings.append("on_screen_text_repeats_spoken_hook")
    if cover_onscreen is not None and cover_onscreen >= 0.80:
        warnings.append("on_screen_text_repeats_cover")
    if not first_frame_visual or visual_generic_only:
        warnings.append("first_frame_visual_is_generic_or_missing")
    if visual and visual_overlap < 0.08:
        warnings.append("first_frame_visual_not_anchored_to_hook_subject")

    return {
        "spoken_hook": spoken_hook,
        "cover_headline": cover_headline,
        "on_screen_hook_text": on_screen_hook_text,
        "first_frame_visual": first_frame_visual,
        "spoken_cover_overlap": round(spoken_cover, 3),
        "spoken_onscreen_overlap": round(spoken_onscreen, 3) if spoken_onscreen is not None else None,
        "cover_onscreen_overlap": round(cover_onscreen, 3) if cover_onscreen is not None else None,
        "visual_subject_overlap": round(visual_overlap, 3),
        "visual_generic_only": visual_generic_only,
        "warnings": warnings,
        "gating": False,
    }


def payoff_proof_report(*, hook: str, payoff: str, central_question: str = "") -> dict[str, Any]:
    """Check whether a payoff appears to answer/reframe rather than merely echo.

    This is deliberately conservative: lexical overlap and resolution cues are
    evidence, not truth. A human still decides whether the ending actually lands.
    """
    hook = _clean(hook)
    payoff = _clean(payoff)
    central_question = _clean(central_question)

    opening_tokens = _tokens(central_question or hook)
    hook_tokens = _tokens(hook)
    payoff_tokens = _tokens(payoff)
    hook_payoff_overlap = _jaccard(hook_tokens, payoff_tokens)
    question_payoff_overlap = _jaccard(opening_tokens, payoff_tokens)
    resolution_cue = bool(RESOLUTION_CUES.search(payoff))
    generic_hits = [m.group(0) for p in GENERIC_PAYOFF_PATTERNS if (m := re.search(p, payoff, re.I))]

    warnings: list[str] = []
    if hook_payoff_overlap >= 0.60:
        warnings.append("payoff_restates_hook")
    if generic_hits:
        warnings.append("generic_ai_payoff")
    if opening_tokens and question_payoff_overlap < 0.08 and not resolution_cue:
        warnings.append("payoff_has_no_visible_connection_to_opening")
    if payoff.endswith("?"):
        warnings.append("payoff_opens_new_question_instead_of_resolving")

    return {
        "hook": hook,
        "central_question": central_question,
        "payoff": payoff,
        "hook_payoff_overlap": round(hook_payoff_overlap, 3),
        "opening_payoff_overlap": round(question_payoff_overlap, 3),
        "resolution_cue_present": resolution_cue,
        "generic_payoff_hits": generic_hits,
        "warnings": warnings,
        "gating": False,
        "human_review_question": "Does this ending specifically pay off the reason a cold viewer stayed?",
    }


def manifest_hook_payoff_report(manifest: Mapping[str, Any]) -> dict[str, Any]:
    scenes = list(manifest.get("scenes") or [])
    first = scenes[0] if scenes else {}
    last = scenes[-1] if scenes else {}
    hook = manifest.get("hook") or first.get("voiceover") or ""
    payoff = last.get("voiceover") or manifest.get("payoff") or ""
    return {
        "hook_surfaces": hook_surface_report(
            spoken_hook=hook,
            cover_headline=manifest.get("hook_headline") or "",
            on_screen_hook_text=first.get("on_screen_text") or "",
            first_frame_visual=(first.get("visual_intent") or first.get("search_query") or first.get("scientific_subject") or ""),
        ),
        "payoff_proof": payoff_proof_report(
            hook=hook,
            payoff=payoff,
            central_question=manifest.get("central_question") or manifest.get("whatif") or "",
        ),
        "gating": False,
    }
