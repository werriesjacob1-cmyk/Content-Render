"""Zero-network pre-render visual feasibility diagnostics for Writer V2.1.

Non-gating by design: expose scenes whose visual plan cannot literally show the
spoken science before asset acquisition/render spend.
"""
from __future__ import annotations
import re
from typing import Any, Mapping, Sequence

GENERIC = {"science","scientist","lab","laboratory","research","technology","space","nature","person","people","thinking","abstract","background","cinematic","dramatic","footage","animation"}
ABSTRACT = {"idea","concept","truth","reality","mystery","danger","power","scale","importance","possibility","knowledge","future"}
VISIBLE_ACTION = re.compile(r"\b(hit|hits|strike|strikes|punch|punches|break|breaks|dissolv|regenerat|spin|orbit|collid|crush|flow|freeze|melt|grow|move|climb|measure|compare|split|bend|explode|erupt|sink|fall|rise|rotate|pulse|flash|form)\w*\b", re.I)

def _tokens(v: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(v or "").lower())

def scene_visual_feasibility(scene: Mapping[str, Any]) -> dict[str, Any]:
    visual = str(scene.get("visual_intent") or scene.get("search_query") or scene.get("scientific_subject") or "").strip()
    voice = str(scene.get("voiceover") or "").strip()
    vt = _tokens(visual); content = [t for t in vt if len(t)>2 and t not in GENERIC]
    voice_tokens = {t for t in _tokens(voice) if len(t)>2}
    visual_tokens = set(content)
    shared = sorted(voice_tokens & visual_tokens)
    generic_only = bool(vt) and not content
    abstract_only = bool(content) and all(t in ABSTRACT for t in content)
    action = bool(VISIBLE_ACTION.search(visual))
    warnings=[]
    if not visual: warnings.append("missing_visual_intent")
    if generic_only: warnings.append("generic_visual_wallpaper")
    if abstract_only: warnings.append("abstract_nonshowable_visual")
    if visual and content and not shared and not action: warnings.append("visual_not_anchored_to_voiceover")
    if visual and len(content)<2 and not action: warnings.append("underspecified_visual_subject")
    return {"scene_id":scene.get("id"),"visual":visual,"shared_subject_tokens":shared,"visible_action":action,"specific_content_tokens":content,"warnings":warnings,"showable":not warnings}

def visual_feasibility_report(scenes: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    rows=[scene_visual_feasibility(s) for s in (scenes or [])]
    bad=[r for r in rows if r["warnings"]]
    return {"scenes":rows,"scene_count":len(rows),"problem_scene_count":len(bad),"problem_scene_ids":[r["scene_id"] for r in bad],"warning_kinds":sorted({w for r in bad for w in r["warnings"]}),"all_scenes_showable":bool(rows) and not bad,"gating":False}
