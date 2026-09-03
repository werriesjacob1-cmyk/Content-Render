"""
writer_v2_repair.py -- Phases 3-8 of the 2026-09-03 traceability/repair
mission. Imports FROM writer_v2 (one-way, no cycle -- generate.py imports
this module; nothing here imports generate.py):

  - TraceabilityViolation / check_traceability(): the mechanical claim-
    support validator (Phase 3). This is what would have caught the
    razor-blade-class problem if it had been unsupported -- see its own
    docstring for the mechanism.
  - CriticVerdict / a critic prompt/schema (Phase 5): a small, narrow-role
    judge distinct from generate.score_script()'s rubric.
  - RepairLoop primitives (Phase 6-8): classify a failure, build a targeted
    (not blind-regenerate) repair prompt, bounded rounds.

Nothing here calls a network API directly -- callers (generate.py) own the
actual LLM calls, exactly like writer_v2.py's own convention, so every
decision function here stays independently, network-free testable.
"""
import re

import writer_v2 as W2

# ---------------------------------------------------------------------------
# PHASE 3 -- MECHANICAL CLAIM TRACEABILITY VALIDATOR
#
# The razor-blade regression case taught the real lesson: a prompt
# INSTRUCTION not to fabricate is not enforcement. This checks, word-by-word
# and phrase-by-phrase, whether every SPECIFIC thing a line asserts (a
# number, a unit, a named entity, a distinctive content noun -- "razor",
# "blade", "Empire", "Building", "electricity") actually appears somewhere
# in the claims that line cited (+ the fact's own globally-permitted
# key_terms). It does NOT check prose style -- ordinary connective language
# ("here's the weird part", "but that creates a problem", pronouns, common
# verbs/adjectives) is filtered by a deliberately broad common-English
# stopword list, so a line with genuinely no factual payload extracts NO
# terms at all and can never violate, cited or not.
#
# This is intentionally not solved with one enumerated blacklist of banned
# phrases ("razor blade", "Empire State Building", ...) -- it is a REUSABLE
# support check: build the allowed vocabulary from the cited claims (+
# key_terms), extract the line's own factual tokens with the SAME extractor
# writer_v2.build_claim_inventory used to build that vocabulary in the first
# place, and flag whatever appears in the line but not in what it cited.
# ---------------------------------------------------------------------------

# A deliberately broad common-English function-word/generic-word list --
# NOT the science-anti-jargon lists elsewhere in this codebase, a plain
# stopword list, so ordinary spoken connective language extracts zero terms
# regardless of citation state. Specific content nouns ("razor", "blade",
# "electricity", "mechanism" as a literal claimed mechanism name) are NOT on
# this list and so remain checkable.
_CONNECTIVE_STOPWORDS = {
    # pronouns / determiners
    "this", "that", "these", "those", "your", "yours", "their", "theirs",
    "them", "they", "here", "there", "what", "which", "whose", "whom",
    "some", "such", "each", "every", "other", "another", "both", "none",
    "same", "only", "just", "even", "still", "also", "very", "really",
    "actually", "quite", "rather", "more", "most", "much", "many", "any",
    "all", "own",
    # common verbs (any tense) -- rhetorical/transition/state verbs
    "have", "has", "had", "having", "does", "did", "doing", "will", "would",
    "could", "should", "shall", "might", "must", "gets", "getting", "went",
    "goes", "going", "comes", "coming", "came", "makes", "making", "made",
    "takes", "taking", "took", "sees", "seeing", "saw", "looks", "looking",
    "looked", "knows", "knowing", "knew", "thinks", "thinking", "thought",
    "wants", "wanting", "wanted", "gives", "giving", "gave", "uses", "using",
    "used", "finds", "finding", "found", "tells", "telling", "told", "asks",
    "asking", "asked", "works", "working", "worked", "seems", "seeming",
    "seemed", "feels", "feeling", "felt", "tries", "trying", "tried",
    "leaves", "leaving", "left", "calls", "calling", "called", "keeps",
    "keeping", "kept", "lets", "letting", "mean", "means", "meaning", "meant",
    "becomes", "becoming", "became", "shows", "showing", "showed",
    "happen", "happens", "happening", "happened", "turns", "turning",
    "turned", "starts", "starting", "started", "needs", "needing", "needed",
    "wonder", "wondering", "wondered", "imagine", "imagining", "imagined",
    "sound", "sounds", "sounding", "sounded", "guess", "guesses", "guessing",
    "guessed", "create", "creates", "creating", "created", "notice",
    "notices", "noticing", "noticed",
    # generic adjectives / adverbs / abstract nouns -- rhetorical framing,
    # not factual payload
    "real", "true", "false", "whole", "entire", "part", "parts", "simple",
    "weird", "strange", "wild", "normal", "ordinary", "hidden", "secret",
    "deep", "huge", "tiny", "small", "large", "little", "good", "bad",
    "better", "worse", "best", "worst", "next", "ever", "never", "always",
    "thing", "things", "way", "ways", "point", "story", "moment", "problem",
    "question", "answer", "reason", "kind", "sort", "case", "fact", "facts",
    "look", "closer", "wait", "here's", "heres", "there's", "theres",
    "it's", "its", "that's", "thats", "what's", "whats", "let's", "lets",
    "now", "body", "self",
    # prepositions / conjunctions -- pure function words, never factual
    # payload regardless of what they connect
    "into", "onto", "unto", "like", "unlike", "within", "without", "about",
    "above", "below", "between", "among", "against", "toward", "towards",
    "upon", "atop", "beside", "besides", "despite", "unless", "until",
    "since", "though", "although", "whether", "either", "neither", "nor",
    "across", "along", "around", "behind", "beyond", "during", "except",
    "inside", "outside", "throughout", "underneath", "while", "than", "then",
    "when", "once", "in", "on", "at", "of", "to", "as", "or", "an", "is",
    "it", "by", "be", "if", "so", "up", "out", "off", "for", "and", "but",
    "not", "no", "do", "we", "us", "you", "he", "she", "his", "her", "him",
    "was", "are", "am",
    # ---------------------------------------------------------------------
    # GENERAL-ENGLISH HIGH-FREQUENCY VOCABULARY -- 2026-09-03 false-positive
    # hardening. Live smoke-testing against a full drafted script (not just
    # isolated example sentences) showed the categories above were nowhere
    # near broad enough: ordinary descriptive verbs/adjectives/adverbs that
    # any natural paraphrase uses ("handles", "third", "separate", "quietly",
    # "briefly", "cases", "main", "exhausting", "runs") were being flagged as
    # unsupported factual content even though they carry no independent
    # factual payload -- they're just how a sentence is WORDED. This is a
    # broad common-vocabulary ALLOWLIST, not a per-phrase blacklist (contrast
    # with the mission's explicit "don't solve with one giant blacklist" --
    # a blacklist targets specific hallucinated phrases; this recognizes
    # ordinary English broadly, on purpose, so genuinely distinctive/specific
    # nouns like "razor", "blade", "syndrome", "electricity" still register).
    # ---------------------------------------------------------------------
    "runs", "handle", "handles", "handling", "handled", "hold", "holds",
    "holding", "held", "move", "moves", "moving", "moved", "help", "helps",
    "helping", "helped", "begin", "begins", "beginning", "began", "talk",
    "talks", "talking", "talked", "play", "plays", "playing", "played",
    "live", "lives", "living", "lived", "believe", "believes", "believing",
    "believed", "bring", "brings", "bringing", "brought", "write", "writes",
    "writing", "wrote", "written", "sit", "sits", "sitting", "sat", "stand",
    "stands", "standing", "stood", "lose", "loses", "losing", "lost", "pay",
    "pays", "paying", "paid", "meet", "meets", "meeting", "met", "include",
    "includes", "including", "included", "set", "sets", "setting", "learn",
    "learns", "learning", "learned", "change", "changes", "changing",
    "changed", "lead", "leads", "leading", "led", "understand",
    "understands", "understanding", "understood", "watch", "watches",
    "watching", "watched", "follow", "follows", "following", "followed",
    "stop", "stops", "stopping", "stopped", "speak", "speaks", "speaking",
    "spoke", "spoken", "read", "reads", "reading", "allow", "allows",
    "allowing", "allowed", "spend", "spends", "spending", "spent", "grow",
    "grows", "growing", "grew", "grown", "open", "opens", "opening",
    "opened", "walk", "walks", "walking", "walked", "win", "wins",
    "winning", "won", "offer", "offers", "offering", "offered", "remember",
    "remembers", "remembering", "remembered", "love", "loves", "loving",
    "loved", "consider", "considers", "considering", "considered", "appear",
    "appears", "appearing", "appeared", "buy", "buys", "buying", "bought",
    "wait", "waits", "waiting", "waited", "serve", "serves", "serving",
    "served", "die", "dies", "dying", "died", "send", "sends", "sending",
    "sent", "expect", "expects", "expecting", "expected", "build", "builds",
    "building", "built", "stay", "stays", "staying", "stayed", "fall",
    "falls", "falling", "fell", "fallen", "reach", "reaches", "reaching",
    "reached", "remain", "remains", "remaining", "remained", "burn",
    "burns", "burning", "burned", "burnt", "carry", "carries", "carrying",
    "carried", "pull", "pulls", "pulling", "pulled", "push", "pushes",
    "pushing", "pushed", "cross", "crosses", "crossing", "crossed",
    "close", "closes", "closing", "closed", "drop", "drops", "dropping",
    "dropped", "raise", "raises", "raising", "raised", "cover", "covers",
    "covering", "covered", "break", "breaks", "breaking", "broke",
    "broken", "control", "controls", "controlling", "controlled",
    "produce", "produces", "producing", "produced", "act", "acts",
    "acting", "acted", "wear", "wears", "wearing", "wore", "worn",
    "care", "cares", "caring", "cared", "sends", "reduce", "reduces",
    "reducing", "reduced", "add", "adds", "adding", "added",
    "main", "third", "second", "first", "fourth", "fifth", "separate",
    "separately", "whole", "general", "generally", "specific",
    "specifically", "particular", "particularly", "certain", "certainly",
    "sure", "clear", "clearly", "possible", "possibly", "important",
    "different", "difficult", "available", "likely", "unlikely", "short",
    "long", "high", "low", "early", "late", "young", "old", "further",
    "national", "local", "social", "political", "economic", "human",
    "natural", "original", "originally", "final", "finally", "average",
    "typical", "typically", "common", "commonly", "usual", "usually",
    "normally", "standard", "regular", "regularly", "special",
    "extra", "exact", "exactly", "roughly", "approximately", "directly",
    "immediately", "suddenly", "eventually", "currently", "recently",
    "previously", "initially", "ultimately", "basically", "literally",
    "effectively", "significantly", "dramatically", "gradually",
    "constantly", "frequently", "rarely", "occasionally", "briefly",
    "quietly", "slowly", "quickly", "easily", "simply", "probably",
    "especially", "mostly", "mainly", "largely", "nearly", "almost",
    "case", "cases", "matter", "matters", "situation", "condition",
    "process", "result", "results", "effect", "effects", "cause",
    "causes", "level", "levels", "rate", "rates", "amount", "amounts",
    "extent", "range", "form", "forms", "example", "examples", "instance",
    "exhausted", "exhausting", "tired", "tiring", "system", "systems",
    "heart", "hearts", "swim", "swims", "swimming", "swum", "swam",
}


def _stem(word):
    """Very light suffix-stripping so a natural paraphrase using a different
    verb inflection of an already-supported word ("compressed" in the cited
    claim vs. "compressing" in the writer's line) doesn't register as a NEW,
    unsupported term. Deliberately crude (no real morphology) -- this is a
    provenance check, not a linguistics tool, and a false NEGATIVE here just
    means a genuinely novel term still has to independently clear the raw-word
    check, so over-stemming is the safe direction to err in."""
    w = word
    if w.endswith("ing") and len(w) - 3 >= 4:
        stem = w[:-3]
        # doubled-consonant gerund: swimming->swim, running->run, stopping->stop
        if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
            stem = stem[:-1]
        return stem
    if w.endswith("edly") and len(w) - 4 >= 4:
        return w[:-4]
    if w.endswith("ed") and len(w) - 2 >= 4:
        stem = w[:-2]
        if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
            stem = stem[:-1]
        return stem
    if w.endswith(("ches", "shes", "xes", "ses", "zes")) and len(w) - 2 >= 4:
        return w[:-2]  # boxes->box, watches->watch, glasses->glass
    if w.endswith("s") and not w.endswith("ss") and len(w) - 1 >= 4:
        return w[:-1]  # blades->blade
    return w


class TraceabilityViolation:
    """beat_index: 0 = hook, 1..N = beats (1-indexed, matches manifest scene
    ids), N+1 = payoff. kind: 'unknown_claim_id' | 'uncited_factual_content'
    | 'unsupported_number' | 'unsupported_unit' | 'unsupported_entity' |
    'unsupported_term'."""

    def __init__(self, beat_index, kind, value, cited_claim_ids=None, detail=""):
        self.beat_index = beat_index
        self.kind = kind
        self.value = value
        self.cited_claim_ids = list(cited_claim_ids or [])
        self.detail = detail

    def __repr__(self):
        return (f"TraceabilityViolation(beat_index={self.beat_index}, kind={self.kind!r}, "
                f"value={self.value!r}, cited_claim_ids={self.cited_claim_ids})")

    def __eq__(self, other):
        return isinstance(other, TraceabilityViolation) and self.to_dict() == other.to_dict()

    def to_dict(self):
        return {"beat_index": self.beat_index, "kind": self.kind, "value": self.value,
                "cited_claim_ids": self.cited_claim_ids, "detail": self.detail}


def _content_terms(text):
    """Same-length-4+-word extraction as writer_v2._extract_factual_tokens'
    `terms`, but filtered through the broader connective-language stopword
    list above (that extractor's own stopword list is narrower -- it's the
    permissive ALLOWED-vocabulary side; this is the stricter CHECKING side,
    on purpose, per the mission's own "be careful not to reject ordinary
    language" instruction)."""
    words = re.findall(r"[a-zA-Z]{4,}", (text or "").lower())
    return sorted({w for w in words if w not in _CONNECTIVE_STOPWORDS})


def _line_factual_payload(text):
    tok = W2._extract_factual_tokens(text)
    # writer_v2's proper-noun extractor is deliberately generous (it also
    # feeds the ALLOWED-vocabulary side, where over-matching is harmless) --
    # a sentence-initial capitalized common word ("Here's", "Now") gets
    # caught as an "entity" there. Re-filter through the same stricter
    # connective list used for `terms` so a capitalized rhetorical opener
    # isn't mistaken for a named entity on the CHECKING side.
    entities = [e for e in tok["entities"] if e.lower() not in _CONNECTIVE_STOPWORDS]
    return {
        "numbers": tok["numbers"],
        "units": tok["units"],
        "entities": entities,
        "terms": _content_terms(text),
    }


def _allowed_vocab(cited_claims, key_terms):
    numbers, units, entities, terms = set(), set(), set(), set()
    for c in cited_claims:
        numbers.update(c.get("allowed_numbers") or [])
        units.update(c.get("allowed_units") or [])
        entities.update(e.lower() for e in (c.get("allowed_entities") or []))
        terms.update(c.get("allowed_terms") or [])
    for kt in key_terms or []:
        kt_tok = W2._extract_factual_tokens(kt)
        numbers.update(kt_tok["numbers"])
        units.update(kt_tok["units"])
        entities.update(e.lower() for e in kt_tok["entities"])
        terms.update(kt_tok["terms"])
        # the raw key_term words themselves count as allowed terms too, even
        # short ones or ones _extract_factual_tokens wouldn't flag alone
        terms.update(w.lower() for w in re.findall(r"[a-zA-Z]{3,}", kt))
    stems = {_stem(t) for t in terms}
    return {"numbers": numbers, "units": units, "entities": entities, "terms": terms,
            "stems": stems}


def _check_line(beat_index, text, cited_ids, claims_by_id, key_terms):
    violations = []
    cited_claims = []
    for cid in cited_ids:
        claim = claims_by_id.get(cid)
        if claim is None:
            violations.append(TraceabilityViolation(
                beat_index, "unknown_claim_id", cid, cited_ids,
                detail=f"cited claim id {cid!r} does not exist in the evidence packet"))
        else:
            cited_claims.append(claim)

    payload = _line_factual_payload(text)
    allowed = _allowed_vocab(cited_claims, key_terms)

    if not cited_ids:
        # No citation at all. Still allowed IF the line genuinely has no
        # factual payload (pure connective/rhetorical tissue) -- but the
        # moment it names a number, unit, entity, or distinctive term, that
        # is uncited factual content, full stop. This is the closed version
        # of the "connective language" escape hatch the mission asked for:
        # the WRITER doesn't get to self-declare a line connective, the
        # extractor decides based on what's actually in the line.
        found_any = payload["numbers"] or payload["units"] or payload["entities"] or payload["terms"]
        if found_any:
            for kind, vals in (("uncited_factual_content", payload["numbers"] + payload["units"]),
                               ("uncited_factual_content", payload["entities"] + payload["terms"])):
                for v in vals:
                    violations.append(TraceabilityViolation(
                        beat_index, "uncited_factual_content", v, [],
                        detail="line asserts specific factual content but cites no evidence claim"))
        return violations

    for n in payload["numbers"]:
        if n not in allowed["numbers"]:
            violations.append(TraceabilityViolation(
                beat_index, "unsupported_number", n, cited_ids,
                detail=f"number {n!r} not found in the cited claim(s) or key_terms"))
    for u in payload["units"]:
        if u not in allowed["units"]:
            violations.append(TraceabilityViolation(
                beat_index, "unsupported_unit", u, cited_ids,
                detail=f"unit {u!r} not found in the cited claim(s) or key_terms"))
    for e in payload["entities"]:
        if e.lower() not in allowed["entities"] and e.lower() not in allowed["terms"]:
            violations.append(TraceabilityViolation(
                beat_index, "unsupported_entity", e, cited_ids,
                detail=f"entity {e!r} not found in the cited claim(s) or key_terms"))
    for t in payload["terms"]:
        if (t not in allowed["terms"] and t not in allowed["entities"]
                and _stem(t) not in allowed["stems"]):
            violations.append(TraceabilityViolation(
                beat_index, "unsupported_term", t, cited_ids,
                detail=f"term {t!r} not found in the cited claim(s) or key_terms"))
    return violations


def check_traceability(writer_out, claim_inventory):
    """Runs the full mechanical check over hook (beat_index=0), each beat
    (1..N), and payoff (N+1). Returns a list of TraceabilityViolation
    (empty = clean). Never raises on malformed input -- a missing field is
    just treated as empty/uncited, which will itself surface as violations
    if it contains factual content, which is the correct behavior (fail
    loud, not silently pass)."""
    writer_out = writer_out or {}
    claim_inventory = claim_inventory or {}
    claims_by_id = {c["claim_id"]: c for c in (claim_inventory.get("claims") or [])}
    key_terms = claim_inventory.get("key_terms") or []

    violations = []
    violations += _check_line(0, writer_out.get("hook") or "",
                              list(writer_out.get("hook_source_claim_ids") or []),
                              claims_by_id, key_terms)
    beats = writer_out.get("beats") or []
    for i, b in enumerate(beats):
        violations += _check_line(i + 1, b.get("voiceover") or "",
                                  list(b.get("source_claim_ids") or []),
                                  claims_by_id, key_terms)
    violations += _check_line(len(beats) + 1, writer_out.get("payoff") or "",
                              list(writer_out.get("payoff_source_claim_ids") or []),
                              claims_by_id, key_terms)
    return violations


# ---------------------------------------------------------------------------
# PHASE 5 -- SMALL INDEPENDENT CREATIVE CRITIC
#
# A narrow-role judge, deliberately separate from generate.score_script()'s
# rubric (which stays the untouched production quality floor) and from this
# module's own mechanical check_traceability() (which stays the untouched
# provenance floor). The critic's ONLY job is qualitative craft: does this
# read as something a person wrote and would want to watch. It does NOT
# research, does not invent facts, does not touch hashtags/visual editing --
# and its own factual-support diagnosis, if any, must point at EXISTING claim
# IDs, never propose new factual material (enforced by construction: the
# schema below has no field where the critic could write replacement facts,
# only `target_beats` (indices) and `diagnosis`/`must_preserve` (prose about
# craft, not content)).
# ---------------------------------------------------------------------------

CRITIC_STATIC = """You are a blunt, experienced short-form video script editor. You do NOT write scripts, research facts, or invent replacement material -- you only diagnose what is wrong with a script that has ALREADY been written and grounded, and say which beats need a targeted rewrite.

Score each dimension 1-10 (10 = excellent, honest ratings -- most first drafts should NOT all score 8+):
- hook_strength: does the first line grab attention in <2 seconds without gimmicks?
- clarity: is the central idea instantly graspable, no confusing referents?
- escalation: does each beat raise the stakes/surprise over the last, never flatline or repeat a point?
- payoff: does the ending land as a genuine resonant idea, not a restated hook or a command?
- spoken_naturalness: would a real person actually SAY these sentences out loud?
- cliche_ai_smell: score LOW (1-3) if it reads like generic AI copy (fortune-cookie lines, "here's the wild part", forced enthusiasm); score HIGH (8-10) if it sounds genuinely human-written and specific.
- structural_distinctiveness: does this feel like a different shape from a generic hook->fact->fact->twist video?
- visual_tellability: can each beat actually be SHOWN on screen, not just narrated over generic B-roll?
- claim_traceability: does every specific claim in the script feel like it's actually anchored to real evidence, not decorated with plausible-sounding invented specifics?

Then decide exactly ONE repair_type for the single most damaging problem (or NONE if the script is genuinely ready):
NONE | PROVENANCE | HOOK | ESCALATION | PAYOFF | NATURALNESS | STRUCTURAL

target_beats: the beat_index integers that need rewriting for that ONE repair_type. beat_index 0 = hook, 1..N = beats in order, N+1 = payoff. Keep this list as SHORT as possible -- only the beats that genuinely need to change, never the whole script unless the structure itself is broken.

diagnosis: one or two sentences on the SPECIFIC problem (not generic feedback).

must_preserve: a short list of specific things in the beats you are NOT flagging that the rewrite must not disturb (a phrase, a fact, a transition that already works).

You do not have access to write new facts. If the problem is a claim that feels unsupported or invented, set repair_type to PROVENANCE and name the beat -- someone else will supply the allowed replacement material.

Return ONLY valid JSON, no markdown, no commentary."""


CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {
                "hook_strength": {"type": "integer"},
                "clarity": {"type": "integer"},
                "escalation": {"type": "integer"},
                "payoff": {"type": "integer"},
                "spoken_naturalness": {"type": "integer"},
                "cliche_ai_smell": {"type": "integer"},
                "structural_distinctiveness": {"type": "integer"},
                "visual_tellability": {"type": "integer"},
                "claim_traceability": {"type": "integer"},
            },
            "required": ["hook_strength", "clarity", "escalation", "payoff", "spoken_naturalness",
                        "cliche_ai_smell", "structural_distinctiveness", "visual_tellability",
                        "claim_traceability"],
            "additionalProperties": False,
        },
        "repair_type": {
            "type": "string",
            "enum": ["NONE", "PROVENANCE", "HOOK", "ESCALATION", "PAYOFF", "NATURALNESS", "STRUCTURAL"],
        },
        "target_beats": {"type": "array", "items": {"type": "integer"}},
        "diagnosis": {"type": "string"},
        "must_preserve": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["scores", "repair_type", "target_beats", "diagnosis", "must_preserve"],
    "additionalProperties": False,
}

CRITIC_SCORE_DIMENSIONS = tuple(CRITIC_SCHEMA["properties"]["scores"]["required"])


def _script_lines_block(writer_out):
    """Shared compact rendering of a writer_out's spoken content, one line
    per beat_index, used by both the critic prompt and the repair prompt so
    a beat_index in the critic's target_beats always refers to the exact
    same line a human (or the repairer) would see."""
    writer_out = writer_out or {}
    lines = [f"[0 HOOK] {writer_out.get('hook', '')}"]
    beats = writer_out.get("beats") or []
    for i, b in enumerate(beats):
        lines.append(f"[{i + 1}] {b.get('voiceover', '')}")
    lines.append(f"[{len(beats) + 1} PAYOFF] {writer_out.get('payoff', '')}")
    return "\n".join(lines), len(beats)


def build_critic_prompt(writer_out, claim_inventory=None, traceability_violations=None):
    """Compact, separate prompt -- deliberately NOT the writer prompt with an
    extra instruction bolted on. Gives the critic the script text and, when
    present, a short summary of any mechanical provenance violations already
    found (so its own claim_traceability score and PROVENANCE diagnosis, if
    it independently agrees, are informed rather than guessing blind)."""
    script_block, _ = _script_lines_block(writer_out)
    violations_block = ""
    if traceability_violations:
        lines = [f"  - beat {v.beat_index}: {v.kind} ({v.value!r})" for v in traceability_violations[:12]]
        violations_block = (
            "\n\nMECHANICAL PROVENANCE CHECK ALREADY FOUND THESE UNSUPPORTED ITEMS "
            "(you do not need to re-derive these, just factor them into your diagnosis):\n"
            + "\n".join(lines)
        )
    return (
        CRITIC_STATIC
        + "\n\nSCRIPT TO JUDGE:\n" + script_block
        + violations_block
    )


# ---------------------------------------------------------------------------
# PHASE 6-8 -- BOUNDED TARGETED REPAIR LOOP
#
# classify_repair() decides WHAT needs fixing from the mechanical + critic
# signals (mechanical provenance violations always win -- a script cannot
# ship with an unsupported claim no matter how the critic scored it).
# build_repair_prompt() asks the model to rewrite ONLY the flagged beats,
# with the exact allowed evidence for those beats and an explicit
# instruction to leave everything else untouched. merge_repair() then
# applies just those beats onto a COPY of the previous candidate, so every
# beat not targeted for repair survives byte-for-byte (Phase 7: protecting
# already-good work). MAX_REPAIR_ROUNDS bounds total calls -- see
# generate.generate_candidate_v2 for the orchestration and the deterministic
# best-candidate selection rule (Phase 7).
# ---------------------------------------------------------------------------

MAX_REPAIR_ROUNDS = 2

REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "repairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "beat_index": {"type": "integer"},
                    "voiceover": {"type": "string"},
                    "visual_intent": {"type": "string"},
                    "source_claim_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["beat_index", "voiceover", "visual_intent", "source_claim_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["repairs"],
    "additionalProperties": False,
}
# `voiceover` doubles as the replacement text for beat_index 0 (hook) and
# N+1 (payoff) too -- merge_repair() knows those indices carry no on-screen
# visual_intent field on the manifest and ignores it there. One schema
# shape keeps the repair call itself small and structured-output-friendly.


def classify_repair(critic_verdict, violations, num_beats):
    """Pure decision function -- no network call. Mechanical provenance
    violations ALWAYS take priority over the critic's own repair_type: a
    script with an unsupported claim gets PROVENANCE repair regardless of
    what the critic diagnosed, because provenance is the harder, non-
    negotiable floor (Phase 3/7). Only when there are zero mechanical
    violations does the critic's own diagnosis drive the repair. Falls back
    to NONE (nothing to do) on a malformed/missing critic_verdict rather than
    guessing -- callers should treat NONE + zero violations as "accept as
    is", and NONE + violations as "should not happen" (classify_repair itself
    prevents that combination, see below)."""
    if violations:
        target_beats = sorted({v.beat_index for v in violations if 0 <= v.beat_index <= num_beats + 1})
        diagnosis = "; ".join(sorted({f"beat {v.beat_index}: {v.kind} {v.value!r}" for v in violations}))[:500]
        return {
            "repair_type": "PROVENANCE",
            "target_beats": target_beats or list(range(0, num_beats + 2)),
            "diagnosis": diagnosis or "mechanical traceability violations found",
            "must_preserve": [],
        }

    critic_verdict = critic_verdict or {}
    repair_type = critic_verdict.get("repair_type") or "NONE"
    valid_types = {"NONE", "PROVENANCE", "HOOK", "ESCALATION", "PAYOFF", "NATURALNESS", "STRUCTURAL"}
    if repair_type not in valid_types:
        repair_type = "NONE"
    raw_targets = critic_verdict.get("target_beats") or []
    target_beats = sorted({t for t in raw_targets if isinstance(t, int) and 0 <= t <= num_beats + 1})
    if repair_type != "NONE" and not target_beats:
        # a critic that names a repair_type but no usable target_beats hasn't
        # given us anything actionable -- fail closed to NONE rather than
        # guessing which beats it meant (a full-script repair is the
        # explicit exception, not something we invent from an empty list)
        repair_type = "NONE"
    return {
        "repair_type": repair_type,
        "target_beats": target_beats,
        "diagnosis": (critic_verdict.get("diagnosis") or "")[:500],
        "must_preserve": list(critic_verdict.get("must_preserve") or []),
    }


def build_repair_prompt(writer_out, claim_inventory, treatment_name, plan, treatments=None):
    """`plan` is classify_repair()'s output dict. Builds a SMALL prompt --
    only the targeted beats' current text, the evidence claims available to
    them, the diagnosis, and an explicit do-not-touch instruction -- never
    the full writer mega-prompt. This is the actual mechanism behind Phase 8:
    a repair round costs a fraction of the original writer call's tokens."""
    import writer_v2 as _W2  # local import mirrors the module-level one; avoids a hard cycle if this ever moves
    treatments = treatments or _W2.TREATMENTS
    script_block, num_beats = _script_lines_block(writer_out)
    target_beats = plan.get("target_beats") or []

    claim_inventory = claim_inventory or {}
    claims = claim_inventory.get("claims") or []
    claim_lines = [f"  [{c['claim_id']}] {c['claim_text']}" for c in claims]
    claims_block = "\n".join(claim_lines) if claim_lines else "  (none available)"

    preserve_block = ""
    if plan.get("must_preserve"):
        preserve_block = "\n\nMUST PRESERVE EXACTLY (do not rephrase or drop these): " + "; ".join(
            str(p) for p in plan["must_preserve"])

    repair_type = plan.get("repair_type", "STRUCTURAL")
    if repair_type == "PROVENANCE":
        instruction = (
            "The beats listed below contain factual material NOT supported by the evidence claims. "
            "Rewrite ONLY these beats so every specific claim, name, or number they contain is "
            "genuinely supported by the EVIDENCE CLAIMS list -- remove or replace unsupported "
            "specifics using ONLY what the cited claims actually say. Do not invent new facts, even "
            "plausible-sounding ones. It is fine for a rewritten beat to be more general/qualitative "
            "if the evidence doesn't support a specific number or name."
        )
    else:
        instruction = (
            f"The script has a {repair_type} problem in the beats listed below. Rewrite ONLY these "
            f"beats to fix it. Keep the same evidence claims cited (or cite different ones from the "
            f"list below if genuinely more relevant) -- every rewritten line must still be traceable "
            f"to a cited claim, exactly like the original writing rules."
        )

    return (
        f"You are doing a TARGETED REPAIR on an existing script, not writing a new one. "
        f"Treatment: {treatment_name}.\n\n"
        f"CURRENT FULL SCRIPT (for context -- beat_index labels each line):\n{script_block}\n\n"
        f"EVIDENCE CLAIMS (cite by ID, paraphrase naturally, never invent beyond these):\n{claims_block}\n\n"
        f"DIAGNOSIS: {plan.get('diagnosis', '')}\n\n"
        f"{instruction}\n\n"
        f"ONLY rewrite beat_index {target_beats}. Do not return any other beat_index. "
        f"Every returned beat needs voiceover + visual_intent (use \"\" for visual_intent on beat_index "
        f"0 or {num_beats + 1}) + source_claim_ids (the claim IDs that support the rewritten text)."
        + preserve_block
        + "\n\nReturn ONLY valid JSON in EXACTLY this shape -- a single object with one key \"repairs\" "
          "holding an array (never a bare array on its own, never anything else at the top level):\n"
          '{"repairs": [{"beat_index": ' + str(target_beats[0] if target_beats else 0) + ', '
          '"voiceover": "...", "visual_intent": "...", "source_claim_ids": ["claim_001"]}]}'
    )


def merge_repair(writer_out, repairs, num_beats=None):
    """Pure, deep-copying merge: applies ONLY the repaired beat_index entries
    onto a copy of writer_out, leaving every other beat/hook/payoff exactly
    as it was (Phase 7 -- protecting already-good work from an unrelated
    repair round touching it). beat_index 0 = hook, N+1 = payoff, 1..N =
    beats[idx-1]. An out-of-range or malformed repair entry is silently
    skipped (fail closed: never crash the loop over one bad repair item, and
    never let an out-of-range index corrupt the beats list)."""
    out = {
        "title": writer_out.get("title", ""),
        "hook": writer_out.get("hook", ""),
        "hook_source_claim_ids": list(writer_out.get("hook_source_claim_ids") or []),
        "beats": [dict(b) for b in (writer_out.get("beats") or [])],
        "payoff": writer_out.get("payoff", ""),
        "payoff_source_claim_ids": list(writer_out.get("payoff_source_claim_ids") or []),
    }
    n = num_beats if num_beats is not None else len(out["beats"])
    for r in (repairs or []):
        idx = r.get("beat_index")
        if not isinstance(idx, int):
            continue
        vo = (r.get("voiceover") or "").strip()
        if not vo:
            continue
        cids = list(r.get("source_claim_ids") or [])
        if idx == 0:
            out["hook"] = vo
            out["hook_source_claim_ids"] = cids
        elif idx == n + 1:
            out["payoff"] = vo
            out["payoff_source_claim_ids"] = cids
        elif 1 <= idx <= n:
            vi = (r.get("visual_intent") or "").strip()
            beat = dict(out["beats"][idx - 1])
            beat["voiceover"] = vo
            if vi:
                beat["visual_intent"] = vi
            beat["source_claim_ids"] = cids
            out["beats"][idx - 1] = beat
    return out


def select_best_candidate(candidates):
    """Pure, deterministic selection over a list of candidate dicts, each
    shaped {"writer_out":..., "violations": [...], "validate_err": str|None,
    "score": float|None}. A candidate is CLEAN iff it has zero traceability
    violations AND no validate() error. Among clean candidates, the highest
    `score` wins (ties broken by earliest/first-seen index, i.e. prefer the
    EARLIER round -- do not keep spending repair rounds once something
    already clean and good exists). If no candidate is clean, returns None
    (Phase 7: never accept a lower-quality or provenance-violating candidate
    just because the loop ran out of rounds -- the caller aborts)."""
    best = None
    best_score = float("-inf")
    for c in candidates or []:
        if c.get("violations"):
            continue
        if c.get("validate_err"):
            continue
        score = c.get("score")
        if score is None:
            continue
        if score > best_score:
            best = c
            best_score = score
    return best
