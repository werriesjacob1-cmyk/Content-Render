"""Writer V2.1 render-manifest assembly.

Claude's V2 writer correctly models hook and payoff as distinct spoken lines, but
``writer_v2.assemble_manifest_v2`` only puts the middle beats into ``scenes``.
The production renderer synthesizes narration from ``m['scenes'][*]['voiceover']``
only, so the hook/payoff would be scored and fact-checked but never spoken.

This adapter makes the story structure literal in the render contract:

    scene 1        = HOOK
    scenes 2..N+1 = treatment beats
    final scene    = PAYOFF

No LLM calls. Claim IDs are preserved on the exact spoken scene. Hook/payoff
visual queries are deterministic from the topic's curated visual opportunities,
falling back to their own spoken text only when the bank has no usable query.
"""
from __future__ import annotations

from typing import Any, Mapping

import writer_v2 as W


def _on_screen(text: str) -> str:
    return " ".join(str(text or "").strip().split()[:3]).upper()


def _visual_query(raw: str, banned_query_re=None) -> str:
    return W.derive_search_query(str(raw or ""), banned_query_re)


def assemble_manifest_v21(
    writer_out: Mapping[str, Any] | None,
    fact: Mapping[str, Any] | None,
    treatment_name: str,
    job_name: str = "CURIOSITY_ITCH",
    cta_style: str = "SAVE_WORTHY",
    banned_query_re=None,
) -> dict[str, Any]:
    writer_out = dict(writer_out or {})
    fact = dict(fact or {})
    beats = list(writer_out.get("beats") or [])
    curated_queries = [str(q).strip() for q in (fact.get("queries") or []) if str(q).strip()]

    title = str(writer_out.get("title") or "")
    hook = str(writer_out.get("hook") or "").strip()
    payoff = str(writer_out.get("payoff") or "").strip()
    keyword, metaphor = W.derive_keyword_metaphor(fact, title)

    # The first curated query is already the topic bank's best opening visual
    # opportunity. The last is the best deterministic payoff fallback. When a
    # topic has only one query, use it for the hook and derive the payoff from
    # its actual spoken line rather than showing the same visual twice by force.
    hook_visual = curated_queries[0] if curated_queries else hook
    payoff_visual = (
        curated_queries[-1]
        if len(curated_queries) >= 2
        else payoff
    )

    spoken_units: list[dict[str, Any]] = [{
        "voiceover": hook,
        "visual_intent": hook_visual,
        "source_claim_ids": list(writer_out.get("hook_source_claim_ids") or []),
        "role": "hook",
    }]
    for beat in beats:
        spoken_units.append({
            "voiceover": str(beat.get("voiceover") or "").strip(),
            "visual_intent": str(beat.get("visual_intent") or "").strip(),
            "source_claim_ids": list(beat.get("source_claim_ids") or []),
            "role": "beat",
        })
    spoken_units.append({
        "voiceover": payoff,
        "visual_intent": payoff_visual,
        "source_claim_ids": list(writer_out.get("payoff_source_claim_ids") or []),
        "role": "payoff",
    })

    scenes: list[dict[str, Any]] = []
    for idx, unit in enumerate(spoken_units, 1):
        voiceover = unit["voiceover"]
        scenes.append({
            "id": idx,
            "duration": 4,
            "voiceover": voiceover,
            "on_screen_text": _on_screen(voiceover),
            "search_query": _visual_query(unit["visual_intent"], banned_query_re),
            "motion": W.MOTION_CYCLE[(idx - 1) % len(W.MOTION_CYCLE)],
            "source_claim_ids": list(unit["source_claim_ids"]),
            # Internal role survives for diagnostics/Visual Director. Existing
            # renderer ignores unknown scene fields safely.
            "_v2_role": unit["role"],
        })

    script = " ".join(s["voiceover"] for s in scenes if s["voiceover"])
    return {
        "title": title,
        "viewer_job": job_name,
        "keyword": keyword,
        "metaphor": metaphor,
        "vibe": W.derive_vibe(treatment_name),
        "hook": hook,
        "hook_source_claim_ids": list(writer_out.get("hook_source_claim_ids") or []),
        "hook_headline": W.derive_hook_headline(hook),
        "script": script,
        "scenes": scenes,
        "captions": W.derive_captions(hook, cta_style),
        "hashtags": W.derive_hashtags(fact.get("domain", "")),
        "render": {"voice": "en-US-GuyNeural", "rate": "-5%", "resolution": "1080x1920"},
        "treatment": treatment_name,
        "cta_style": cta_style,
        "payoff": payoff,
        "payoff_source_claim_ids": list(writer_out.get("payoff_source_claim_ids") or []),
        "_v2_spoken_scene_count": len(scenes),
    }
