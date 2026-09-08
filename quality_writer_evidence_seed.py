#!/usr/bin/env python3
"""Deterministic evidence-only Writer seed for private flagship certification.

This module is deliberately NOT part of unattended production generation.  It
exists so the private certification lane can turn already-curated source claims
into one conservative Writer-shaped candidate when live writer providers are
quota constrained.  It does not certify or render anything: the returned
candidate must still pass the canonical Writer V2.1 traceability, semantic
critic, validate(), quality-floor, story-bridge, and visual-session gates.

The first supported seed is ``venus_day`` because the September 8 flagship run
proved three live candidates were reaching ordinary form failures while the
curated base evidence itself already contained every beat needed for a strong
story.  The seed is fail-closed against topic-bank drift: if the expected source
claims or evidence tokens are missing, no candidate is returned.
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


def build_evidence_seed(
    fact: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return one Writer-schema candidate made only from named evidence claims.

    ``None`` means the topic is unsupported or its curated evidence no longer
    matches the exact assumptions under which this seed was written.  No fuzzy
    fallback and no model-memory completion is permitted.
    """
    if str((fact or {}).get("id") or "") != "venus_day":
        return None

    central = _claim_by_ref(inventory, "topic_bank.fact")
    wow = _claim_by_ref(inventory, "topic_bank.wow")
    question = _claim_by_ref(inventory, "topic_bank.whatif_question")
    answer = _claim_by_ref(inventory, "topic_bank.whatif_answer")

    # Bind the wording below to the actual curated evidence.  If the bank is
    # edited later, certification must stop rather than silently use a stale
    # handcrafted script.
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

    # 84 spoken words: safely inside the current SHORT hard range (68-108).
    # Hook is a statement; beat 1 carries the required early curiosity question.
    # Every factual line cites the exact curated claim(s) that support it.
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
