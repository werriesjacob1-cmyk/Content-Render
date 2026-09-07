"""Non-gating hook-surface separation and payoff-proof diagnostics for Writer V2.1.

A short-form video's spoken hook, cover headline, first-frame visual, and payoff
are four separate jobs. This module detects when they collapse into duplicate
text/ideas or when the payoff fails to resolve the opening curiosity.
"""
from __future__ import annotations
import re
from typing import Any, Mapping

STOP={"a","an","and","are","as","at","be","because","but","by","can","could","did","do","does","for","from","had","has","have","how","if","in","into","is","it","its","just","of","on","or","so","that","the","their","then","there","this","to","too","was","we","were","what","when","where","which","who","why","will","with","would","you","your"}
GENERIC_FIRST_FRAME={"science","lab","laboratory","scientist","research","space","stars","technology","abstract","background","cinematic","dramatic","person","thinking","microscope","nature","stock","footage"}
GENERIC_PAYOFF_PATTERNS=(r"\bchanges everything\b",r"\bmore than meets the eye\b",r"\bremind(?:s|ing)? us that\b",r"\bdanger (?:often )?hides in plain sight\b",r"\bthe universe (?:is|can be) stranger\b",r"\bwe are only beginning to understand\b")
RESOLUTION_CUES=re.compile(r"\b(?:because|which means|that means|so |therefore|turns out|actually|instead|the reason|the answer|what matters|this happens|that happens)\b",re.I)
def _clean(v:Any)->str:return re.sub(r"\s+"," ",str(v or "")).strip()
def _tokens(v:Any)->set[str]:return {w for w in re.findall(r"[a-z0-9]+(?:['’-][a-z0-9]+)?",_clean(v).lower()) if len(w)>2 and w not in STOP}
def _jaccard(a:set[str],b:set[str])->float:
    if not a and not b:return 1.0
    if not a or not b:return 0.0
    return len(a&b)/len(a|b)

def hook_surface_report(*,spoken_hook:str,cover_headline:str,first_frame_visual:str,on_screen_hook_text:str="")->dict[str,Any]:
    spoken_hook=_clean(spoken_hook);cover_headline=_clean(cover_headline);first_frame_visual=_clean(first_frame_visual);on_screen_hook_text=_clean(on_screen_hook_text)
    spoken=_tokens(spoken_hook);cover=_tokens(cover_headline);onscreen=_tokens(on_screen_hook_text);visual=_tokens(first_frame_visual)
    spoken_cover=_jaccard(spoken,cover);spoken_onscreen=_jaccard(spoken,onscreen) if onscreen else None;cover_onscreen=_jaccard(cover,onscreen) if onscreen else None
    opening_subject_tokens=(spoken|cover)-GENERIC_FIRST_FRAME
    shared_subject=opening_subject_tokens&visual
    # Anchoring is intentionally containment-like, not Jaccard. A useful visual
    # should get MORE specific ("stomach lining epithelial cells"), and those
    # extra visual nouns must not dilute one correct shared subject token.
    visual_subject_overlap=(len(shared_subject)/max(1,min(len(opening_subject_tokens),len(visual)))) if visual else 0.0
    visual_generic_only=bool(visual) and visual.issubset(GENERIC_FIRST_FRAME)
    warnings=[]
    if spoken_cover>=.70:warnings.append("cover_repeats_spoken_hook")
    if spoken_onscreen is not None and spoken_onscreen>=.80:warnings.append("on_screen_text_repeats_spoken_hook")
    if cover_onscreen is not None and cover_onscreen>=.80:warnings.append("on_screen_text_repeats_cover")
    if not first_frame_visual or visual_generic_only:warnings.append("first_frame_visual_is_generic_or_missing")
    if visual and not visual_generic_only and not shared_subject:warnings.append("first_frame_visual_not_anchored_to_hook_subject")
    return {"spoken_hook":spoken_hook,"cover_headline":cover_headline,"on_screen_hook_text":on_screen_hook_text,"first_frame_visual":first_frame_visual,"spoken_cover_overlap":round(spoken_cover,3),"spoken_onscreen_overlap":round(spoken_onscreen,3) if spoken_onscreen is not None else None,"cover_onscreen_overlap":round(cover_onscreen,3) if cover_onscreen is not None else None,"visual_subject_overlap":round(visual_subject_overlap,3),"shared_visual_subject_tokens":sorted(shared_subject),"visual_generic_only":visual_generic_only,"warnings":warnings,"gating":False}

def payoff_proof_report(*,hook:str,payoff:str,central_question:str="")->dict[str,Any]:
    hook=_clean(hook);payoff=_clean(payoff);central_question=_clean(central_question);opening=_tokens(central_question or hook);ht=_tokens(hook);pt=_tokens(payoff)
    hp=_jaccard(ht,pt);op=_jaccard(opening,pt);resolution=bool(RESOLUTION_CUES.search(payoff));generic=[m.group(0) for p in GENERIC_PAYOFF_PATTERNS if (m:=re.search(p,payoff,re.I))]
    warnings=[]
    if hp>=.60:warnings.append("payoff_restates_hook")
    if generic:warnings.append("generic_ai_payoff")
    if opening and op<.08 and not resolution:warnings.append("payoff_has_no_visible_connection_to_opening")
    if payoff.endswith("?"):warnings.append("payoff_opens_new_question_instead_of_resolving")
    return {"hook":hook,"central_question":central_question,"payoff":payoff,"hook_payoff_overlap":round(hp,3),"opening_payoff_overlap":round(op,3),"resolution_cue_present":resolution,"generic_payoff_hits":generic,"warnings":warnings,"gating":False,"human_review_question":"Does this ending specifically pay off the reason a cold viewer stayed?"}

def manifest_hook_payoff_report(manifest:Mapping[str,Any])->dict[str,Any]:
    scenes=list(manifest.get("scenes") or []);first=scenes[0] if scenes else {};last=scenes[-1] if scenes else {};hook=manifest.get("hook") or first.get("voiceover") or "";payoff=last.get("voiceover") or manifest.get("payoff") or ""
    return {"hook_surfaces":hook_surface_report(spoken_hook=hook,cover_headline=manifest.get("hook_headline") or "",on_screen_hook_text=first.get("on_screen_text") or "",first_frame_visual=(first.get("visual_intent") or first.get("search_query") or first.get("scientific_subject") or "")),"payoff_proof":payoff_proof_report(hook=hook,payoff=payoff,central_question=manifest.get("central_question") or manifest.get("whatif") or ""),"gating":False}
