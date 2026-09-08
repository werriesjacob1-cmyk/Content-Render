#!/usr/bin/env python3
"""Deterministic evidence-only Writer seeds for private flagship certification.

This module is deliberately NOT part of unattended production generation. It
exists so the private certification lane can turn already-curated source claims
into one conservative Writer-shaped candidate when live writer providers are
quota constrained. It does not certify or render anything: every returned
candidate must still pass canonical Writer V2.1 traceability, semantic critic,
validate(), quality-floor, story-bridge, and visual-session gates.

Seeds are fail-closed against topic-bank drift: if the expected source claims or
evidence tokens are missing, no candidate is returned. No fuzzy fallback and no
model-memory completion is permitted.
"""
from __future__ import annotations

from typing import Any, Mapping


def _claim_by_ref(inventory: Mapping[str, Any], source_ref: str) -> Mapping[str, Any] | None:
    for claim in inventory.get("claims") or []:
        if str(claim.get("source_ref") or "") == source_ref:
            return claim
    return None


def _contains_all(claim: Mapping[str, Any] | None, needles: tuple[str, ...]) -> bool:
    if not claim:
        return False
    text = str(claim.get("claim_text") or "").lower()
    return all(str(n).lower() in text for n in needles)


def _venus_seed(inventory: Mapping[str, Any]) -> dict[str, Any] | None:
    central = _claim_by_ref(inventory, "topic_bank.fact")
    wow = _claim_by_ref(inventory, "topic_bank.wow")
    question = _claim_by_ref(inventory, "topic_bank.whatif_question")
    answer = _claim_by_ref(inventory, "topic_bank.whatif_answer")

    if not _contains_all(central, ("venus", "243", "225", "sun")):
        return None
    if not _contains_all(wow, ("venus", "retrograde", "west", "east")):
        return None
    if not _contains_all(question, ("year", "venus")):
        return None
    if not _contains_all(answer, ("venus", "243", "225", "day", "year")):
        return None

    c = str(central["claim_id"])
    w = str(wow["claim_id"])
    q = str(question["claim_id"])
    a = str(answer["claim_id"])

    return {
        "title": "Venus: A Day Longer Than a Year",
        "hook": "Venus has one day that is longer than its year.",
        "hook_source_claim_ids": [c],
        "beats": [
            {
                "voiceover": "What if you tried living through one full year on Venus?",
                "visual_intent": "planet Venus from space",
                "source_claim_ids": [q],
            },
            {
                "voiceover": "Venus takes 243 Earth days to complete one rotation.",
                "visual_intent": "Venus rotating in space",
                "source_claim_ids": [c],
            },
            {
                "voiceover": "Its trip around the Sun takes only 225 Earth days.",
                "visual_intent": "Venus orbit around Sun",
                "source_claim_ids": [c],
            },
            {
                "voiceover": "Venus also spins in retrograde, opposite almost every other planet.",
                "visual_intent": "Venus retrograde rotation",
                "source_claim_ids": [w],
            },
            {
                "voiceover": "There, the Sun rises in the west and sets in the east.",
                "visual_intent": "Venus sunrise horizon",
                "source_claim_ids": [w],
            },
            {
                "voiceover": "If you lived through one Venus year, you still wouldn't finish a day.",
                "visual_intent": "Venus planet slow rotation",
                "source_claim_ids": [a],
            },
        ],
        "payoff": "Venus completes a year before one of its days ends.",
        "payoff_source_claim_ids": [c, a],
    }


def _eclipse_seed(inventory: Mapping[str, Any]) -> dict[str, Any] | None:
    central = _claim_by_ref(inventory, "topic_bank.fact")
    wow = _claim_by_ref(inventory, "topic_bank.wow")

    if not _contains_all(central, ("sun", "400", "moon", "farther", "same size", "eclipse")):
        return None
    if not _contains_all(wow, ("moon", "3.8", "farther", "year", "eclipse", "vanish")):
        return None

    c = str(central["claim_id"])
    w = str(wow["claim_id"])

    # Deliberately follows SCALE_REVEAL's progression instead of merely listing
    # the same facts in a convenient order: familiar phenomenon -> first scale
    # jump -> second scale jump -> true apparent-size result -> real consequence
    # -> the larger implication. Every factual proposition is still a direct
    # paraphrase of the two curated claims above and must pass the normal critic.
    return {
        "title": "Why the Moon Fits the Sun So Perfectly",
        "hook": "The Moon can cover the Sun almost perfectly during a total eclipse.",
        "hook_source_claim_ids": [c],
        "beats": [
            {
                "voiceover": "Start with scale: the Sun is about 400 times wider than the Moon.",
                "visual_intent": "Sun Moon diameter scale comparison",
                "source_claim_ids": [c],
            },
            {
                "voiceover": "Now jump to distance: the Sun is also about 400 times farther away.",
                "visual_intent": "Sun Earth Moon distance comparison",
                "source_claim_ids": [c],
            },
            {
                "voiceover": "Those two ratios make their disks look nearly the same size.",
                "visual_intent": "Sun Moon apparent size comparison",
                "source_claim_ids": [c],
            },
            {
                "voiceover": "That apparent-size match is what makes total solar eclipses possible.",
                "visual_intent": "solar eclipse totality corona",
                "source_claim_ids": [c],
            },
            {
                "voiceover": "But the Moon drifts about 3.8 centimeters farther away every year.",
                "visual_intent": "Moon receding from Earth orbit diagram",
                "source_claim_ids": [w],
            },
            {
                "voiceover": "In a few hundred million years, total eclipses will vanish from our sky.",
                "visual_intent": "future annular eclipse Sun Moon geometry",
                "source_claim_ids": [w],
            },
        ],
        "payoff": "The perfect total eclipse is a temporary feature of Earth.",
        "payoff_source_claim_ids": [c, w],
    }


def build_evidence_seed(
    fact: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return one Writer-schema candidate made only from named evidence claims."""
    topic_id = str((fact or {}).get("id") or "")
    if topic_id == "venus_day":
        return _venus_seed(inventory)
    if topic_id == "eclipse_coincidence":
        return _eclipse_seed(inventory)
    return None
