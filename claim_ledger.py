"""Claim ledger: one entry per scene, derived deterministically from the script (no LLM).

Each scene states ONE claim (its voiceover sentence). The ledger records what each scene
adds -- its new content words and its numbers -- so a scene that only re-says earlier
material is caught before any footage is fetched, and so the rendered manifest carries an
auditable record of what each beat was supposed to teach.

Complements validate(): its checks look at adjacent pairs and at the core number; this
one measures every scene against EVERYTHING said before it.
"""
from __future__ import annotations

import re

import craft_rules

MIN_CONTENT_WORDS = 4          # shorter lines are transitions, not claims
MIN_NOVEL_FRACTION = 0.15      # measured: clean scripts bottom out at >=0.5; 8 of 54 historical rejected rounds hit 0.0
_NUM = re.compile(r"\b\d[\d,\.]*\b")


def build_ledger(voiceovers):
    """[{scene, claim, content_words, new_words, novel_fraction, numbers}] (pure)."""
    seen, out = set(), []
    for i, vo in enumerate(voiceovers):
        stems = craft_rules.content_stems(vo)
        new = stems - seen
        out.append({
            "scene": i, "claim": (vo or "").strip(), "content_words": len(stems),
            "new_words": len(new),
            "novel_fraction": round(len(new) / len(stems), 2) if stems else 1.0,
            "numbers": _NUM.findall(vo or ""),
        })
        seen |= stems
    return out


def lint(voiceovers):
    """Error string or None. Scene 0 (the hook) and short transition lines are exempt."""
    for e in build_ledger(voiceovers)[1:]:
        if e["content_words"] >= MIN_CONTENT_WORDS and e["novel_fraction"] < MIN_NOVEL_FRACTION:
            return (f"scene {e['scene']} ({e['claim']!r}) adds almost nothing new "
                    f"({e['new_words']} of {e['content_words']} content words are new) — every "
                    f"scene must state a claim that has not been made yet")
    return None
