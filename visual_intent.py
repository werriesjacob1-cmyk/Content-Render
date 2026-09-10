#!/usr/bin/env python3
"""The single visual-intent contract: what a scene must SHOW, and how to ask for it.

WHY THIS MODULE EXISTS

The same idea had grown in two places that cannot import each other. `generate.py`
`validate()` decides a `search_query` is unusable; `main.py`
`_subject_anchored_query` builds a replacement when a query duplicates. Neither
could see the other's rules, so the validator could reject a query the builder
would happily construct, and the builder had no way to check its own output
against the rule that would judge it.

`main.py` and `generate.py` do not import each other, so this is a LEAF module --
stdlib only, importing nothing from the codebase -- exactly the shape
`delivery_contract.py` already established for the audio contract. Both sides
import from here, so the rule and the repair are one source of truth. That drift
between "what the prompt/builder produces" and "what validate() enforces" is the
same class of bug that produced the Writer length-contract failure.

THE THREE LAYERS THIS SEPARATES

A. WHAT MUST BE SHOWN -- the literal subject of the scene, taken from the
   video's own subject plus nouns already present in that scene's narration.
B. HOW IT MAY BE SHOWN -- not decided here. Existing production code owns lane
   selection (stock, scientific media, deterministic explanatory motion). This
   module only refuses to let a metaphor become the visual subject.
C. THE RETRIEVAL QUERY -- literal, subject-led text for whichever lane runs.

WHAT THIS MODULE MAY NEVER DO

Only `search_query` is retrieval metadata. Narration, `source_claim_ids`, numbers,
entities and every evidence field are untouchable here: a repair may reorder
retrieval words, never restate science. Everything below is built from material
ALREADY in the manifest -- the subject and the scene's own narration -- so a
repair cannot introduce a claim the Writer did not make.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------
# The shared rule: what makes a visual query unusable.
# Moved here verbatim from generate.py, which now imports them, so validator and
# repairer cannot disagree.
# --------------------------------------------------------------------------

# Stock libraries return junk (flesh closeups, random labs, a random texture the
# judge then rates a false match) for these. Say the plain subject instead.
UNSTOCKABLE_Q = re.compile(r"\b(anatom\w*|organs?|cells?|microscop\w*|diagrams?|x-?ray|molecul\w*|"
                           r"atoms?|quantum|abstracts?|concept\w*|"
                           r"(?<!solar )(?<!root )(?<!river )(?<!weather )(?<!mountain )"
                           r"(?<!cave )(?<!reef )(?<!canyon )systems?|"
                           r"rhizomorph\w*|myceli\w*|hyphae?|antisolar)\b", re.I)

# render-209: a human-ancestry payoff line shipped with 'night sky stars'.
# Cosmic imagery is the default a writer reaches for when it cannot think of
# anything concrete.
COSMIC_FILLER_Q_RE = re.compile(r"\b(night sky|starry|star field|starfield|milky way|deep space|"
                                r"outer space|nebula|galaxy|galaxies|constellation|solar system|"
                                r"cosmos|cosmic|planets? orbit\w*)\b", re.I)
SPACE_CONTEXT_RE = re.compile(r"\b(stars?|sky|galaxy|galaxies|nebula|cosmic|cosmos|universe|orbit\w*|"
                              r"planets?|moon|sun|space|asteroids?|comets?|constellation|milky way|"
                              r"black hole)\b", re.I)

# Precise, machine-readable defect codes. A production controller needs to tell
# "this candidate's VISUALS are wrong" apart from "the provider was down" -- the
# chess run was diagnosed as a quota failure when Gemini had worked fine.
DEFECT_UNSTOCKABLE = "visual_intent:unstockable_terms"
DEFECT_COSMIC_FILLER = "visual_intent:cosmic_filler"
DEFECT_EMPTY = "visual_intent:empty_query"

_QUERY_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "at", "is", "are", "was", "were", "be", "and",
    "but", "or", "so", "that", "this", "these", "those", "it", "its", "as", "by", "for", "with",
    "from", "into", "your", "you", "we", "our", "their", "they", "not", "even", "more", "most",
    "than", "then", "when", "where", "why", "how", "what", "which", "can", "could", "would",
    "will", "just", "only", "about", "over", "under", "up", "down", "out", "same", "one", "two",
    "here", "there", "part", "thing", "things", "actually", "really", "very", "another", "other",
    "every", "each", "some", "any", "all", "both", "much", "many", "such", "own", "still",
    "almost", "nearly", "enough", "quite", "rather", "less", "least", "entire", "whole", "total",
    "makes", "made", "make", "take", "takes", "took", "gets", "get", "got", "goes", "went",
    "comes", "came", "give", "gives", "gave", "know", "knows", "think", "thinks", "seem",
    "seems", "look", "looks", "feel", "feels", "become", "becomes", "happen", "happens",
}


def query_defect(query, voiceover="", domain_family=""):
    """The ONE predicate both sides use. Returns a defect code, or None if usable.

    `domain_family` is the fact's family, so an astronomy story is still allowed
    to say 'galaxy' -- cosmic imagery is only filler when the story is not about
    space AND this scene's own narration never mentions anything space-related.
    That second condition keeps a deliberate space metaphor legal.
    """
    q = (query or "").strip()
    if not q:
        return DEFECT_EMPTY
    if UNSTOCKABLE_Q.search(q):
        return DEFECT_UNSTOCKABLE
    if (domain_family != "space"
            and COSMIC_FILLER_Q_RE.search(q)
            and not SPACE_CONTEXT_RE.search(voiceover or "")):
        return DEFECT_COSMIC_FILLER
    return None


def literal_terms(text, subject=""):
    """Concrete words from a scene's own narration, longest-first.

    Longest-first is inherited from the behaviour this replaces. Words already in
    the subject are dropped (they add nothing to a subject-led query), as are
    stopwords and the light verbs / quantity words that produced unsearchable
    phrases like 'kingdom entire lunch'.
    """
    subj = set(re.findall(r"[a-z][a-z-]+", (subject or "").lower()))
    words = re.findall(r"[A-Za-z][A-Za-z-]+", (text or "").lower())
    cand = [w for w in words
            if w not in _QUERY_STOPWORDS and len(w) > 3 and w not in subj]
    seen, ordered = set(), []
    for w in sorted(cand, key=len, reverse=True):
        if w not in seen:
            seen.add(w)
            ordered.append(w)
    return ordered


def subject_led_query(subject, voiceover, taken=None, domain_family=""):
    """'<subject> <one literal term from THIS scene>', or "" if none is safe.

    Every candidate is checked against `query_defect` before being returned, so
    the repairer can never hand back something the validator will reject -- the
    drift that made these two rules disagree in the first place.

    Returns "" rather than inventing filler. The caller decides what to do with
    that: keep the original, try another lane, or fail the candidate honestly.
    """
    subject = (subject or "").strip()
    taken = taken or {}
    if not subject:
        return ""
    for w in literal_terms(voiceover, subject):
        q = f"{subject} {w}"
        if q.lower() in taken:
            continue
        if query_defect(q, voiceover, domain_family) is None:
            return q
    if subject.lower() not in taken and query_defect(subject, voiceover, domain_family) is None:
        return subject
    return ""


def repair_scene_queries(scenes, subject, domain_family=""):
    """Deterministically repair ONLY defective `search_query` fields, in place.

    Returns [(scene_index, old_query, new_query, defect_code)] for what changed.

    Three properties this guarantees, each covered by a test:

    * A query with NO defect is never touched. Diversification and relevance
      decisions belong to their own code paths; this only rescues the broken.
    * A repaired query is built from the subject plus this scene's OWN narration,
      and is re-checked against `query_defect`, so it is grounded and legal.
    * Nothing outside `search_query` is read for writing or modified. Narration,
      claim ids and every other field are left byte-identical.

    A scene whose query cannot be safely repaired keeps its original text and is
    NOT reported as repaired, so the candidate still fails validation honestly
    rather than shipping unrelated footage.
    """
    changed = []
    if not isinstance(scenes, list):
        return changed
    taken = {}
    for sc in scenes:
        if isinstance(sc, dict):
            q = (sc.get("search_query") or "").strip().lower()
            if q:
                taken[q] = True
    for i, sc in enumerate(scenes, 1):
        if not isinstance(sc, dict):
            continue
        old = (sc.get("search_query") or "").strip()
        vo = sc.get("voiceover") or ""
        defect = query_defect(old, vo, domain_family)
        if defect is None:
            continue
        taken.pop(old.lower(), None)
        new = subject_led_query(subject, vo, taken, domain_family)
        if not new or new.lower() == old.lower():
            if old:
                taken[old.lower()] = True
            continue
        sc["search_query"] = new
        taken[new.lower()] = True
        changed.append((i, old, new, defect))
    return changed
