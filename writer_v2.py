"""
V2 WRITER EXPERIMENT (gated behind WRITER_V2=1 in generate.py) -- 2026-09-03
mission: the two failed certification renders showed the production writer
prompt is ~10,000 tokens (measured: 40,172 chars / ~10,043 est. tokens for a
representative call) -- already past Groq's current 8,000 TPM cap on its own,
before any completion budget, regardless of LENGTH_MODE (a LONG-mode and a
SHORT-mode run both requested ~10-11k tokens, because the fixed instruction
block dominates the request, not the target script length). The handful of
drafts that DID get through scored 3.4-5.3/10 -- so this isn't purely a
capacity problem either; the mega-prompt is asking one call to do research
verification + storytelling + retention optimization + visual planning +
captions + hashtags + CTA + motion + metadata all at once.

This module is the decomposition: the writer prompt built here does ONE job
(write a hook + a small number of story beats for a given TREATMENT and a
compact, already-verified STORY PACKET). Everything mechanical -- footage
search queries, captions, hashtags, motion, hook_headline, keyword/metaphor,
vibe -- is assembled AFTERWARD by plain deterministic functions in this file,
not asked of the LLM.

Fully self-contained (no import of generate.py) so there is no import-cycle
risk; generate.py imports FROM here, never the other way around. Every
function is pure/network-free except where explicitly named _live_ or passed
a caller-supplied network call -- see generate.py for the wiring that adds
real LLM calls on top of this module's prompt/schema/assembly logic.
"""
import hashlib
import re

# ---------------------------------------------------------------------------
# TREATMENTS -- each a genuinely different BEAT PROGRESSION. The failure mode
# this fixes: every script collapsing into the same
# hook -> curiosity question -> fact list -> twist shape regardless of what
# HOOK_FRAMES flavor was picked, because the old system only varied the
# OPENING line, never the underlying STORY STRUCTURE. These vary the whole
# shape of the beats, not just the first sentence.
# ---------------------------------------------------------------------------
TREATMENTS = {
    "HIDDEN_MECHANISM": {
        "beats": [
            "the ordinary, visible thing exactly as everyone already knows it",
            "an unexpected behavior or effect that doesn't fit what you'd expect from it",
            "go BENEATH the surface -- what's actually happening, physically, that you can't see",
            "the real mechanism, stated plainly and specifically -- the how/why",
            "a concrete consequence of that mechanism playing out in the real world",
            "reframe -- how this changes the way you'll see the ordinary thing from now on",
        ],
        "default_vibe": "awe",
    },
    "CASE_FILE": {
        "beats": [
            "a strange observation or event, opened like a case file's first line",
            "the evidence noticed at the time",
            "a competing explanation that seemed to make sense but was wrong",
            "the clue that broke that wrong explanation",
            "the actual mechanism, once it was actually found",
            "why it matters now, beyond just solving the mystery",
        ],
        "default_vibe": "tense",
    },
    "ONE_OBJECT_JOURNEY": {
        "beats": [
            "introduce ONE specific particle, molecule, or object as the story's through-line",
            "follow it -- where its path actually begins",
            "a transformation it undergoes along the way",
            "an obstacle or resistance it has to get through",
            "where it actually ends up",
            "what its whole journey implies about something bigger than itself",
        ],
        "default_vibe": "peaceful",
    },
    "SCALE_REVEAL": {
        "beats": [
            "an ordinary, familiar reference point the viewer already has a feel for",
            "a first jump in scale away from that reference point",
            "a second, even bigger jump",
            "state the true scale plainly, in a way that can actually be pictured",
            "how that scale actually touches something real, not just a bigger number",
            "what it means for the viewer specifically, not just the universe in the abstract",
        ],
        "default_vibe": "awe",
    },
    "MYTH_AUTOPSY": {
        "beats": [
            "state the common belief plainly, the way most people would say it",
            "why it seemed to make sense -- its surface logic",
            "the crack -- the specific place the belief actually breaks",
            "the real evidence that broke it",
            "the corrected, true mechanism",
            "what the corrected view actually changes about how you think",
        ],
        "default_vibe": "tense",
    },
    "TIMELINE_TRANSFORMATION": {
        "beats": [
            "the starting state, anchored at a real, specific point in time",
            "a first shift away from that starting state",
            "a second shift, or an acceleration",
            "the pivotal transformation moment itself",
            "the end state, stated plainly",
            "what it means today, not just as history",
        ],
        "default_vibe": "awe",
    },
    "INSIDE_THE_SYSTEM": {
        "beats": [
            "the system exactly as the viewer already experiences it from outside",
            "step inside it / zoom into it",
            "the first internal component or process",
            "how that connects to the next part of the system",
            "the critical interaction or failure point",
            "the big-picture consequence for the whole system, including the viewer",
        ],
        "default_vibe": "eerie",
    },
    "VISUAL_EXPERIMENT": {
        "beats": [
            "pose a concrete physical question you could actually go test yourself",
            "set up the experiment or scenario plainly",
            "what you'd naturally expect to happen",
            "what ACTUALLY happens instead",
            "the mechanism behind why it happens that way, not just that it does",
            "what that result reveals about the world beyond the experiment itself",
        ],
        "default_vibe": "visceral",
    },
}


def select_treatment(fact_id, recent_treatments=None, treatments=None):
    """Deterministic, ZERO-extra-LLM-call selection. Excludes any treatment
    used in `recent_treatments` (falls back to the full set if that would
    empty the pool -- same fail-open shape as generate.selectable_bank), then
    picks stably by hashing fact_id so the same fact always maps to the same
    treatment (reproducible for tests/debugging) while different facts spread
    across the whole set (verified in tests/test_pipeline.py)."""
    treatments = treatments or TREATMENTS
    names = sorted(treatments.keys())
    if not names:
        return None
    recent = {r for r in (recent_treatments or []) if r}
    pool = [n for n in names if n not in recent] or names
    h = int(hashlib.sha1((fact_id or "").encode("utf-8")).hexdigest(), 16)
    return pool[h % len(pool)]


# ---------------------------------------------------------------------------
# STORY PACKET -- a compact, ALREADY-VERIFIED research summary, not nine raw
# trivia bullets. Reshapes whatever grounded facts research_dossier() already
# gathered (or, absent that, the base bank fact's own human-curated angle/wow
# fields) rather than spending a second LLM call reformatting -- every field
# is a heuristic SELECTION from already-trusted content, never invented text,
# matching PR #36's fail-closed provenance contract (grounding unavailable ->
# honest degraded packet, never a silently-fabricated one).
# ---------------------------------------------------------------------------
_MECHANISM_SIGNAL = ("because", "due to", "mechanism", "causes", "cause", "works by",
                     "triggers", "releases", "reacts", "converts", "absorbs", "forms")
_IMPLICATION_SIGNAL = ("means", "implies", "reveals", "which means", "as a result",
                       "so that", "suggests", "would")


def build_story_packet(fact, dossier_facts=None, grounded=False):
    """fact: the topic_bank.json dict for this video (required -- the packet's
    central_claim always anchors to the curated base fact, never to model
    memory alone). dossier_facts: the flat list research_dossier() returns
    (possibly [] if grounding was unavailable this run). grounded: whether
    those dossier_facts actually came from live Google Search grounding
    (research_dossier()'s own contract) -- degrades the packet's own
    provenance honestly rather than claiming grounding it doesn't have."""
    fact = fact or {}
    dossier_facts = [str(d).strip() for d in (dossier_facts or []) if str(d).strip()]
    central = fact.get("fact", "")

    mechanism = next((d for d in dossier_facts
                      if any(sig in d.lower() for sig in _MECHANISM_SIGNAL)), None)
    remaining = [d for d in dossier_facts if d != mechanism]
    supporting = remaining[:3]
    implication = next((d for d in remaining
                        if any(sig in d.lower() for sig in _IMPLICATION_SIGNAL)), None)
    if not implication:
        implication = fact.get("wow", "") or (remaining[-1] if remaining else "")

    if not mechanism:
        mechanism = fact.get("angle", "") or "see the central claim"
    if not supporting:
        wow = fact.get("wow", "")
        supporting = [wow] if wow else []

    return {
        "central_claim": central,
        "mechanism": mechanism,
        "supporting_facts": supporting,
        "surprising_implication": implication,
        "caveat": "" if grounded else
                  "not independently grounded this run -- treat as the curated base fact only",
        "source": "grounded via live Google Search" if grounded
                  else "topic_bank.json (curated, ungrounded this run)",
        "visual_opportunities": list(fact.get("queries", []) or []),
        "key_terms": list(fact.get("key_terms", []) or []),
    }


# ---------------------------------------------------------------------------
# CLAIM INVENTORY -- 2026-09-03 traceability mission. build_story_packet()
# above gives the writer a compact PROSE summary; this gives it (and, more
# importantly, the validator in writer_v2_repair.py) a set of individually
# CITABLE, mechanically-sourced claims. The razor-blade hallucination found
# in the live bakeoff (both legacy AND V2 independently invented the same
# "stomach acid dissolves a razor blade" line, despite an explicit "never
# invent" prompt instruction) is exactly the failure this exists to catch:
# a prompt INSTRUCTION not to fabricate is not enforcement. Every claim here
# is a verbatim slice of already-trusted text (topic_bank fields or a
# genuinely grounded dossier item) -- never LLM-authored, never paraphrased,
# never merged. IDs are deterministic (stable field order + list position)
# so the same fact+dossier always produces the same inventory.
# ---------------------------------------------------------------------------
_TYPOGRAPHIC_QUOTES_RE = re.compile("[‘’ʼ′]")
_TYPOGRAPHIC_DOUBLE_QUOTES_RE = re.compile("[“”″]")
_TYPOGRAPHIC_DASH_RE = re.compile("[–—]")
# exotic Unicode space characters a model can emit in place of a plain ASCII
# space -- 2026-09-04 V2.1 fix, same class of bug as the apostrophe one
# below: "Mauna Kea" written with U+202F (narrow no-break space) between the
# words survived 3 live repair rounds unrepaired because the entity string
# never matched the allowed vocabulary's plain-space "mauna kea" at all. A
# small, bounded set of known Unicode space codepoints, not indefinite --
# regular space/tab/newline are left untouched.
_UNICODE_SPACE_RE = re.compile("[   -   　]")


def _normalize_text(text):
    """2026-09-04 V2.1 fix (mission Phase 5): a curly/typographic apostrophe
    ("didn't" with U+2019) previously tokenized to the fragment "didn" + "t"
    (the word-char regex elsewhere only matches [a-zA-Z], not the smart-quote
    codepoint), and "didn" wasn't a recognized stopword -- a live bakeoff run
    flagged it as an unsupported_term. Normalizing curly quotes/dashes/exotic
    spaces to their plain ASCII equivalents BEFORE any tokenization makes
    "didn't" and "didn't" (and "Mauna Kea" with any Unicode space style)
    behave identically everywhere text is extracted or compared, instead of
    patching each specific malformed fragment into a stopword list (which
    would only fix that one instance, not the class of bug)."""
    text = text or ""
    text = _TYPOGRAPHIC_QUOTES_RE.sub("'", text)
    text = _TYPOGRAPHIC_DOUBLE_QUOTES_RE.sub('"', text)
    text = _TYPOGRAPHIC_DASH_RE.sub("-", text)
    text = _UNICODE_SPACE_RE.sub(" ", text)
    return text


_NUMBER_WORD_RE = re.compile(
    r"\b(zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen|"
    r"hundred|thousand|million|billion|trillion|"
    r"twice|thrice|double|triple|quadruple|half|quarter)s?\b", re.I)
_DIGIT_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_UNIT_RE = re.compile(
    r"\b(kg|kilograms?|grams?|tons?|tonnes?|mm|cm|km|kilometers?|kilometres?|miles?|"
    r"feet|foot|inch(?:es)?|meters?|metres?|seconds?|minutes?|hours?|days?|weeks?|"
    r"months?|years?|degrees?|celsius|fahrenheit|ph|volts?|watts?|liters?|litres?|"
    r"gallons?|mph|percent|%)\b", re.I)
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-zA-Z'.-]*(?:\s+[A-Z][a-zA-Z'.-]*){0,3}\b")
_SENTENCE_START_STOP = {"the", "a", "an", "this", "that", "these", "those", "some",
                        "your", "you", "it", "its", "if", "so", "but", "and", "or",
                        "when", "while", "because", "there", "here", "what", "how",
                        "why", "one", "every", "each", "no", "not", "never", "always"}
_TERM_STOPWORDS = {
    "that", "this", "these", "those", "with", "from", "your", "into", "than", "then",
    "have", "has", "had", "will", "would", "could", "should", "about", "their", "them",
    "they", "there", "here", "when", "while", "because", "even", "just", "also", "only",
    "actually", "still", "some", "such", "each", "every", "more", "most", "much", "many",
    "over", "under", "through", "which", "what", "where", "being", "been", "were", "was",
}


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _extract_factual_tokens(text):
    text = _normalize_text(text)
    numbers = sorted(set(_DIGIT_NUMBER_RE.findall(text)) |
                     {w.lower() for w in _NUMBER_WORD_RE.findall(text)})
    units = sorted({w.lower() for w in _UNIT_RE.findall(text)})
    entities = set()
    weak_entities = set()
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        for m in _PROPER_NOUN_RE.finditer(sentence):
            cand = m.group(0).strip()
            if cand.lower() in _SENTENCE_START_STOP:
                continue
            entities.add(cand)
            if " " not in cand and m.start() == 0:
                weak_entities.add(cand)
    words = re.findall(r"[a-zA-Z]{4,}", text.replace("'", "").lower())
    terms = sorted({w for w in words if w not in _TERM_STOPWORDS})
    return {"numbers": numbers, "units": units, "entities": sorted(entities),
            "weak_entities": sorted(weak_entities), "terms": terms}


def _make_claim(prefix, idx, text, source_kind, source_ref):
    tok = _extract_factual_tokens(text)
    return {
        "claim_id": f"{prefix}_{idx:03d}",
        "claim_text": text,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "confidence": "grounded" if source_kind == "grounded_dossier" else "verified_base_fact",
        "allowed_numbers": tok["numbers"],
        "allowed_units": tok["units"],
        "allowed_entities": tok["entities"],
        "allowed_terms": tok["terms"],
    }


def build_claim_inventory(fact, dossier_facts=None, grounded=False):
    fact = fact or {}
    dossier_facts = [str(d).strip() for d in (dossier_facts or []) if str(d).strip()]
    claims = []

    base = (fact.get("fact") or "").strip()
    if base:
        claims.append(_make_claim("base", 1, base, "base_fact", "topic_bank.fact"))
    wow = (fact.get("wow") or "").strip()
    if wow:
        claims.append(_make_claim("base", 2, wow, "base_fact", "topic_bank.wow"))
    whatif = (fact.get("whatif") or "").strip()
    next_base_id = 3
    if whatif:
        question, sep, answer = whatif.partition("?")
        question = question.strip()
        answer = answer.strip()
        if question and len(question.split()) >= 3:
            claims.append(_make_claim("base", next_base_id, question, "base_fact", "topic_bank.whatif_question"))
            next_base_id += 1
        if sep and answer:
            claims.append(_make_claim("base", next_base_id, answer, "base_fact", "topic_bank.whatif_answer"))
            next_base_id += 1
    angle = (fact.get("angle") or "").strip()
    if angle and len(angle.split()) >= 3:
        claims.append(_make_claim("base", next_base_id, angle, "base_fact", "topic_bank.angle"))
        next_base_id += 1

    for i, d in enumerate(dossier_facts):
        if grounded:
            claims.append(_make_claim("dossier", i + 1, d, "grounded_dossier", "research_dossier.grounded"))
        else:
            claims.append(_make_claim("base", next_base_id + i, d, "base_fact", "research_dossier.ungrounded_opt_out"))

    key_terms = [str(k).strip() for k in (fact.get("key_terms") or []) if str(k).strip()]

    return {
        "claims": claims,
        "key_terms": key_terms,
        "grounded": grounded,
        "provenance_note": (
            "grounded via live Google Search" if grounded else
            "no grounding available this run -- claim inventory is CURATED BASE FACT ONLY, "
            "nothing from ungrounded model memory"
        ),
    }


WRITER_V2_STATIC = """You write scripts for "Stranger Than It Sounds", a faceless science page built to make people FOLLOW and binge.

VOICE: calm, precise, never hype-y ("you won't BELIEVE"), never an exclamation salesman. State astonishing true things plainly and let the strangeness do the work. Match your emotional color to what the fact actually earns (awe, eerie, visceral, tense, peaceful, chaotic) -- never default to one mood.

THE POINT IS A THOUGHT, NOT A NUMBER. Every video must leave a smart adult THINKING differently, not just having heard a stat. Mentally strip every number out of your beats -- if no interesting idea remains, the script has no soul. Magnitude alone (how big/small/many/fast) is dead trivia unless it reframes something or matters to a real person.

HOOK (the first spoken line, 8-14 words):
- Front-load the shock: the most surprising word lands in the first 3-4 words. No wind-up. BANNED openers: "Did you know", "Have you ever", "Imagine", "What if I told you", "Here's", "This is".
- A concrete claim the viewer instantly PICTURES, self-contained, no setup needed -- never a mood or musing that only makes sense after the twist.
- Never a dangling comparative ("closer", "bigger", "faster"...) without stating "...than ___" in the same sentence.
- Never open ON a question mark -- open on a statement; a literal question, if the story needs one, belongs in a later beat.
- Address the viewer directly ("you"/"your") when it strengthens the stakes, not by default.

ACCURACY (non-negotiable): every factual claim, name, and number in the script must be traceable to one of the numbered EVIDENCE CLAIMS below -- never the base fact/packet in prose form, never your own general knowledge, even something you're confident is true. If a fact you know isn't in the evidence list, LEAVE IT OUT. If unsure of a figure, describe the mechanism instead. Never state two different numbers for the same thing.

CITE YOUR SOURCES (mechanically checked, not optional): every beat, the hook, and the payoff each carry a "source_claim_ids" list naming which EVIDENCE CLAIM ID(s) below support what you just said. A beat may cite more than one. Paraphrase naturally -- never quote a claim's exact sentence back verbatim -- but the substance must genuinely come from the claim(s) you cite. Leave source_claim_ids EMPTY only for a line with zero factual content -- pure connective tissue like "So what does that mean?" or "Here's the strange part" that asserts no number, name, or fact of its own. The moment a line names a real thing, a number, or a specific claim, it needs a citation. This is mechanically verified after you answer: an uncited line caught naming something concrete gets rejected and repaired, not silently shipped.

BANNED: vague philosophy, fortune-cookie lines, "everything you know/learned about X is wrong", "myth busted", "this changes everything", "you've been lied to", stating a hypothetical danger as though it just literally happened to the viewer (a hypothetical must be conditional: "If..."/"Suppose..."), unexplained jargon, scientific notation spoken aloud (say "a billion billion", never "10^18"). BANNED formal connector words in any beat -- nobody talks like this out loud: however, nevertheless, furthermore, consequently, notably, essentially, arguably, thus, hence, moreover, whereas. Say it plainly instead ("but", "so", "still").

STRUCTURE: follow the BEAT PROGRESSION given below exactly, in order -- it is a genuinely different shape from a generic hook -> question -> fact-list -> twist, and the whole point of this treatment is that the page doesn't feel formulaic. Each beat is ONE sentence a narrator would actually say out loud, building on the beat before it, never restating an earlier beat's point.

CURIOSITY GAP (hard requirement): the hook OR one of the first 3 beats must literally end in a question mark "?" -- a genuine question the story then actually answers by the payoff, not a rhetorical throwaway. A script with no "?" anywhere in the hook or first 3 beats is invalid. The hook itself does not have to be the question (it usually shouldn't be, per the HOOK rule above) -- put it in beat 1, 2, or 3 instead.

Return ONLY valid JSON matching this exact shape, no markdown, no commentary:
{"title": "...", "hook": "the first spoken line, 8-14 words", "hook_source_claim_ids": ["claim_001"], "beats": [{"voiceover": "one spoken sentence", "visual_intent": "the concrete filmable subject on screen for this beat -- a real thing, not a mood", "source_claim_ids": ["claim_002"]}], "payoff": "the final beat's realization in one sentence -- a resonant thought, never a command like 'save this' and never a restatement of the hook", "payoff_source_claim_ids": ["claim_003"]}"""


def build_writer_prompt_v2(treatment_name, claim_inventory, avoid_topics=None,
                            visual_evidence=None, treatments=None):
    treatments = treatments or TREATMENTS
    t = treatments[treatment_name]
    beat_lines = "\n".join(f"  {i + 1}. {b}" for i, b in enumerate(t["beats"]))

    claim_inventory = claim_inventory or {}
    claims = claim_inventory.get("claims") or []
    claim_lines = [f"EVIDENCE CLAIMS ({claim_inventory.get('provenance_note', '')}):"]
    for c in claims:
        claim_lines.append(f"  [{c['claim_id']}] {c['claim_text']}")
    if not claims:
        claim_lines.append("  (none available -- write only the hook/structure, no factual specifics)")
    claims_block = "\n".join(claim_lines)

    key_terms_block = ""
    key_terms = claim_inventory.get("key_terms") or []
    if key_terms:
        key_terms_block = (
            f"\n\nNAME THE REAL THING: across your beats, explicitly say AT LEAST 2 of these exact "
            f"terms verbatim (say \"{key_terms[0]}\", never a vague paraphrase like \"a naturally "
            f"occurring isotope\"): {key_terms} -- and still cite the claim ID that term comes from."
        )

    visual_block = ""
    if visual_evidence:
        visual_block = f"\n\nVISUAL OPPORTUNITIES (real, filmable subjects available for this topic): {', '.join(visual_evidence)}"

    avoid_block = f"\n\nAVOID these recent topics entirely: {avoid_topics}" if avoid_topics else ""

    return (
        WRITER_V2_STATIC
        + f"\n\nTHIS VIDEO'S TREATMENT: {treatment_name} -- write EXACTLY {len(t['beats'])} beats, in this order:\n"
        + beat_lines
        + "\n\n" + claims_block
        + key_terms_block
        + visual_block
        + avoid_block
    )


WRITER_V2_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string"},
        "hook_source_claim_ids": {"type": "array", "items": {"type": "string"}},
        "beats": {
            "type": "array",
            "minItems": 5,
            "maxItems": 7,
            "items": {
                "type": "object",
                "properties": {
                    "voiceover": {"type": "string"},
                    "visual_intent": {"type": "string"},
                    "source_claim_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["voiceover", "visual_intent", "source_claim_ids"],
                "additionalProperties": False,
            },
        },
        "payoff": {"type": "string"},
        "payoff_source_claim_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "hook", "hook_source_claim_ids", "beats", "payoff", "payoff_source_claim_ids"],
    "additionalProperties": False,
}


def estimate_tokens(text):
    return len(text or "") // 4


MOTION_CYCLE = ["zoom_in", "zoom_out", "pan_left", "pan_right"]
_STOPWORDS = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "with", "and", "or",
             "is", "are", "was", "were", "its", "your", "you", "this", "that", "it", "as",
             "into", "from", "than", "so", "not", "be", "by"}


def derive_search_query(visual_intent, banned_re=None, max_words=5):
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", visual_intent or "")
    kept = [w for w in words if w.lower() not in _STOPWORDS]
    if banned_re is not None:
        kept = [w for w in kept if not banned_re.search(w)]
    q = " ".join(kept[:max_words]).lower()
    return q or "science footage"


def derive_hook_headline(hook, max_chars=22):
    words = re.findall(r"[A-Za-z0-9'-]+", hook or "")
    kept = [w for w in words if w.lower() not in _STOPWORDS] or words
    out, total = [], 0
    for w in kept:
        add = len(w) + (1 if out else 0)
        if total + add > max_chars:
            break
        out.append(w)
        total += add
    return (" ".join(out) or (hook or "")[:max_chars]).upper()


def derive_vibe(treatment_name, treatments=None):
    treatments = treatments or TREATMENTS
    return (treatments.get(treatment_name) or {}).get("default_vibe", "awe")


def derive_keyword_metaphor(fact, title):
    fact = fact or {}
    key_terms = fact.get("key_terms") or []
    keyword = key_terms[0] if key_terms else " ".join((title or "").split()[:3])
    metaphor_words = re.findall(r"[A-Za-z]+", title or "")[:4]
    metaphor = " ".join(metaphor_words) or keyword
    return keyword, metaphor


def derive_captions(hook, cta_style="SAVE_WORTHY"):
    base = (hook or "Something you won't unsee").rstrip(".!")
    return [f"{base}...", "Wait for it.", "The real reason why."]


_HASHTAG_BY_DOMAIN = {
    "space": ["#space", "#astronomy", "#universe"],
    "ocean": ["#ocean", "#marinebiology", "#deepsea"],
    "earth": ["#earth", "#geology", "#nature"],
    "body": ["#humanbody", "#biology", "#anatomy"],
    "animals": ["#animals", "#wildlife", "#nature"],
    "physics": ["#physics", "#science", "#quantum"],
    "chemistry": ["#chemistry", "#science", "#reaction"],
    "neurology": ["#brain", "#neuroscience", "#psychology"],
}


def derive_hashtags(domain):
    return (_HASHTAG_BY_DOMAIN.get((domain or "").lower())
            or ["#science", "#facts", "#didyouknow"])


def assemble_manifest_v2(writer_out, fact, treatment_name, job_name="CURIOSITY_ITCH",
                          cta_style="SAVE_WORTHY", banned_query_re=None):
    """Canonical Writer V2.1 render-manifest assembly.

    The certified semantic surfaces are made literal in the render contract:
    scene 1 is the hook, scenes 2..N+1 are the treatment beats, and the final
    scene is the payoff. Claim IDs travel with the exact spoken scene. This is
    the only Writer V2.1 manifest assembler used by the canonical orchestrator.
    """
    writer_out = dict(writer_out or {})
    fact = dict(fact or {})
    beats = list(writer_out.get("beats") or [])
    curated_queries = [str(q).strip() for q in (fact.get("queries") or []) if str(q).strip()]

    title = str(writer_out.get("title") or "")
    hook = str(writer_out.get("hook") or "").strip()
    payoff = str(writer_out.get("payoff") or "").strip()
    keyword, metaphor = derive_keyword_metaphor(fact, title)

    hook_visual = curated_queries[0] if curated_queries else hook
    payoff_visual = curated_queries[-1] if len(curated_queries) >= 2 else payoff

    spoken_units = [{
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

    scenes = []
    for idx, unit in enumerate(spoken_units, 1):
        voiceover = unit["voiceover"]
        scenes.append({
            "id": idx,
            "duration": 4,
            "voiceover": voiceover,
            "on_screen_text": " ".join(voiceover.split()[:3]).upper(),
            "search_query": derive_search_query(unit["visual_intent"], banned_query_re),
            "motion": MOTION_CYCLE[(idx - 1) % len(MOTION_CYCLE)],
            "source_claim_ids": list(unit["source_claim_ids"]),
            "_v2_role": unit["role"],
        })

    script = " ".join(s["voiceover"] for s in scenes if s["voiceover"])
    return {
        "title": title,
        "viewer_job": job_name,
        "keyword": keyword,
        "metaphor": metaphor,
        "vibe": derive_vibe(treatment_name),
        "hook": hook,
        "hook_source_claim_ids": list(writer_out.get("hook_source_claim_ids") or []),
        "hook_headline": derive_hook_headline(hook),
        "script": script,
        "scenes": scenes,
        "captions": derive_captions(hook, cta_style),
        "hashtags": derive_hashtags(fact.get("domain", "")),
        "render": {"voice": "en-US-GuyNeural", "rate": "-5%", "resolution": "1080x1920"},
        "treatment": treatment_name,
        "cta_style": cta_style,
        "payoff": payoff,
        "payoff_source_claim_ids": list(writer_out.get("payoff_source_claim_ids") or []),
        "_v2_spoken_scene_count": len(scenes),
    }


GENERIC_FILLER_QUERIES = {
    "night sky stars", "ocean waves", "abstract background", "close up hands",
    "clock ticking", "digital data", "computer screen",
}
_RICH_VISUAL_DOMAINS = {"space", "ocean", "animals", "earth", "nature", "weather",
                        "geology", "plants", "physics", "materials"}
_THIN_VISUAL_DOMAINS = {"psychology", "math", "mathematics", "language", "linguistics",
                        "neurology", "neuroscience", "senses", "history"}
_MECHANISM_ACTION_WORDS = ("moves", "grows", "flows", "erupts", "freezes", "glows",
                           "breathes", "swims", "flies", "burns", "melts", "spins",
                           "collapses", "explodes", "orbits", "rotates", "vibrates")


def _filmable(q, banned_re=None):
    words = (q or "").split()
    if len(words) < 2:
        return False
    if banned_re is not None and banned_re.search(q):
        return False
    return True


def visual_scout_score(fact, banned_re=None):
    fact = fact or {}
    queries = [str(q).strip() for q in (fact.get("queries") or []) if str(q).strip()]
    domain = (fact.get("domain") or "").lower()

    filmable_queries = [q for q in queries if _filmable(q, banned_re)]
    distinct = len({q.lower() for q in filmable_queries})
    hook_visual = 10 if (queries and _filmable(queries[0], banned_re)) else (3 if queries else 0)
    distinct_subjects_score = min(10, distinct * 10 // 3)
    if domain in _RICH_VISUAL_DOMAINS:
        domain_coverage = 9
    elif domain in _THIN_VISUAL_DOMAINS:
        domain_coverage = 4
    else:
        domain_coverage = 6
    key_terms = fact.get("key_terms") or []
    mech_hit = any(a in " ".join(list(key_terms) + queries).lower() for a in _MECHANISM_ACTION_WORDS)
    mechanism_visual = 8 if mech_hit else 5
    generic_hits = sum(1 for q in queries if q.lower().strip() in GENERIC_FILLER_QUERIES)

    score = (hook_visual * 0.3 + distinct_subjects_score * 0.3 +
            domain_coverage * 0.2 + mechanism_visual * 0.2) - generic_hits * 1.5
    score = max(0.0, min(10.0, round(score, 2)))

    if score >= 7:
        verdict = "strong -- likely to look genuinely edited, not generic B-roll"
    elif score >= 4.5:
        verdict = "workable -- will need careful footage selection"
    else:
        verdict = "weak -- real risk of generic/off-topic B-roll"

    return {
        "score": score,
        "hook_visual": hook_visual,
        "distinct_subjects": distinct,
        "domain_coverage": domain_coverage,
        "mechanism_visual": mechanism_visual,
        "generic_filler_hits": generic_hits,
        "verdict": verdict,
    }


def rank_topics_by_visual_score(facts, banned_re=None):
    scored = [(f, visual_scout_score(f, banned_re)) for f in (facts or [])]
    scored.sort(key=lambda pair: pair[1]["score"], reverse=True)
    return scored
