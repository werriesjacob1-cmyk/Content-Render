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
    }


# ---------------------------------------------------------------------------
# WRITER PROMPT -- static/stable prefix FIRST (genuinely identical text on
# every call, for provider-side prompt-caching to actually have a chance to
# help), dynamic per-call material (treatment, packet, avoid-list, visual
# evidence) AFTER. The legacy build_prompt() interleaves fact/dossier/avoid
# blocks ahead of the stable rules, which defeats any prefix cache before it
# starts.
# ---------------------------------------------------------------------------
WRITER_V2_STATIC = """You write scripts for "Stranger Than It Sounds", a faceless science page built to make people FOLLOW and binge.

VOICE: calm, precise, never hype-y ("you won't BELIEVE"), never an exclamation salesman. State astonishing true things plainly and let the strangeness do the work. Match your emotional color to what the fact actually earns (awe, eerie, visceral, tense, peaceful, chaotic) -- never default to one mood.

THE POINT IS A THOUGHT, NOT A NUMBER. Every video must leave a smart adult THINKING differently, not just having heard a stat. Mentally strip every number out of your beats -- if no interesting idea remains, the script has no soul. Magnitude alone (how big/small/many/fast) is dead trivia unless it reframes something or matters to a real person.

HOOK (the first spoken line, 8-14 words):
- Front-load the shock: the most surprising word lands in the first 3-4 words. No wind-up. BANNED openers: "Did you know", "Have you ever", "Imagine", "What if I told you", "Here's", "This is".
- A concrete claim the viewer instantly PICTURES, self-contained, no setup needed -- never a mood or musing that only makes sense after the twist.
- Never a dangling comparative ("closer", "bigger", "faster"...) without stating "...than ___" in the same sentence.
- Never open ON a question mark -- open on a statement; a literal question, if the story needs one, belongs in a later beat.
- Address the viewer directly ("you"/"your") when it strengthens the stakes, not by default.

ACCURACY (non-negotiable): every claim, name, and number in the script must come from the STORY PACKET below or the base fact. Never invent a number. If unsure of a figure, describe the mechanism instead. Never state two different numbers for the same thing.

BANNED: vague philosophy, fortune-cookie lines, "everything you know/learned about X is wrong", "myth busted", "this changes everything", "you've been lied to", stating a hypothetical danger as though it just literally happened to the viewer (a hypothetical must be conditional: "If..."/"Suppose..."), unexplained jargon, scientific notation spoken aloud (say "a billion billion", never "10^18").

STRUCTURE: follow the BEAT PROGRESSION given below exactly, in order -- it is a genuinely different shape from a generic hook -> question -> fact-list -> twist, and the whole point of this treatment is that the page doesn't feel formulaic. Each beat is ONE sentence a narrator would actually say out loud, building on the beat before it, never restating an earlier beat's point.

Return ONLY valid JSON matching this exact shape, no markdown, no commentary:
{"title": "...", "hook": "the first spoken line, 8-14 words", "beats": [{"voiceover": "one spoken sentence", "visual_intent": "the concrete filmable subject on screen for this beat -- a real thing, not a mood"}], "payoff": "the final beat's realization in one sentence -- a resonant thought, never a command like 'save this' and never a restatement of the hook"}"""


def build_writer_prompt_v2(treatment_name, packet, avoid_topics=None,
                            visual_evidence=None, treatments=None):
    """Assembles the full V2 writer prompt: WRITER_V2_STATIC (stable) + this
    call's treatment beats + story packet + avoid-list + visual evidence
    (dynamic). See estimate_tokens() for the size this is designed to hit."""
    treatments = treatments or TREATMENTS
    t = treatments[treatment_name]
    beat_lines = "\n".join(f"  {i + 1}. {b}" for i, b in enumerate(t["beats"]))

    packet = packet or {}
    packet_lines = [
        f"STORY PACKET (this is TRUE -- build every beat from this, nothing outside it):",
        f"  Central claim: {packet.get('central_claim', '')}",
        f"  Mechanism: {packet.get('mechanism', '')}",
    ]
    supporting = packet.get("supporting_facts") or []
    if supporting:
        packet_lines.append(f"  Supporting facts: {'; '.join(supporting)}")
    if packet.get("surprising_implication"):
        packet_lines.append(f"  Surprising implication: {packet['surprising_implication']}")
    if packet.get("caveat"):
        packet_lines.append(f"  Caveat: {packet['caveat']}")
    packet_lines.append(f"  Source: {packet.get('source', '')}")
    packet_block = "\n".join(packet_lines)

    visual_block = ""
    ve = visual_evidence or packet.get("visual_opportunities")
    if ve:
        visual_block = f"\n\nVISUAL OPPORTUNITIES (real, filmable subjects available for this topic): {', '.join(ve)}"

    avoid_block = f"\n\nAVOID these recent topics entirely: {avoid_topics}" if avoid_topics else ""

    return (
        WRITER_V2_STATIC
        + f"\n\nTHIS VIDEO'S TREATMENT: {treatment_name} -- write EXACTLY {len(t['beats'])} beats, in this order:\n"
        + beat_lines
        + "\n\n" + packet_block
        + visual_block
        + avoid_block
    )


WRITER_V2_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string"},
        "beats": {
            "type": "array",
            "minItems": 5,
            "maxItems": 7,
            "items": {
                "type": "object",
                "properties": {
                    "voiceover": {"type": "string"},
                    "visual_intent": {"type": "string"},
                },
                "required": ["voiceover", "visual_intent"],
                "additionalProperties": False,
            },
        },
        "payoff": {"type": "string"},
    },
    "required": ["title", "hook", "beats", "payoff"],
    "additionalProperties": False,
}


def estimate_tokens(text):
    """Cheap chars/4 heuristic, no tokenizer dependency. Live-verified against
    Groq's own 'Requested' TPM figure in the 2026-09-03 mission logs (a
    ~40,172-char legacy prompt estimated at ~10,043 tokens vs Groq's reported
    Requested ~10,033-11,492 across several real calls -- within ~1-2%),
    good enough to prove a size reduction without adding a dependency."""
    return len(text or "") // 4


# ---------------------------------------------------------------------------
# DOWNSTREAM MECHANICAL ASSEMBLY -- everything the legacy mega-prompt used to
# ask the LLM for, done here instead as plain deterministic functions. These
# are intentionally simple heuristics for THIS experiment (the bakeoff is
# judging the WRITING, not caption/hashtag polish) -- production-quality
# versions are follow-up work once the writer-side split is validated.
# ---------------------------------------------------------------------------
MOTION_CYCLE = ["zoom_in", "zoom_out", "pan_left", "pan_right"]
_STOPWORDS = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "with", "and", "or",
             "is", "are", "was", "were", "its", "your", "you", "this", "that", "it", "as",
             "into", "from", "than", "so", "not", "be", "by"}


def derive_search_query(visual_intent, banned_re=None, max_words=5):
    """Turns a beat's visual_intent into a short filmable noun-phrase query --
    mechanical, no LLM call. `banned_re` is an optional caller-supplied regex
    (e.g. generate.UNSTOCKABLE_Q) of jargon/un-filmable terms to avoid --
    matched and dropped WORD BY WORD (not just truncated) so a banned term
    anywhere in the phrase can't survive by sitting inside the kept slice.
    The real production gate is still generate.validate()'s own check on the
    assembled manifest; this is just a decent-effort mechanical query."""
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", visual_intent or "")
    kept = [w for w in words if w.lower() not in _STOPWORDS]
    if banned_re is not None:
        kept = [w for w in kept if not banned_re.search(w)]
    q = " ".join(kept[:max_words]).lower()
    return q or "science footage"


def derive_hook_headline(hook, max_chars=22):
    """Mechanical ALL-CAPS cover headline from the spoken hook (was an extra
    LLM-authored field in the legacy schema) -- keeps the strongest content
    words, drops stopwords, truncates to fit the cover design."""
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
    """Deliberately minimal placeholder captions -- caption craft isn't part
    of what the bakeoff is judging (see the mission's own judging criteria);
    real per-platform caption generation is explicit follow-up work."""
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
    """Combines the writer's creative-only output with every mechanical field
    the legacy schema also carried, producing a manifest shape validate()/
    score_script() can consume unchanged (same field names: title,
    viewer_job, keyword, metaphor, vibe, hook, hook_headline, script,
    scenes[id/duration/voiceover/on_screen_text/search_query/motion],
    captions, hashtags, render) plus an extra `treatment` field for
    memory/analytics."""
    writer_out = writer_out or {}
    beats = writer_out.get("beats") or []
    scenes = []
    for i, b in enumerate(beats):
        vo = (b.get("voiceover") or "").strip()
        vi = (b.get("visual_intent") or "").strip()
        on_screen = " ".join(w for w in vo.split()[:3]).upper()
        scenes.append({
            "id": i + 1,
            "duration": 4,
            "voiceover": vo,
            "on_screen_text": on_screen,
            "search_query": derive_search_query(vi, banned_query_re),
            "motion": MOTION_CYCLE[i % len(MOTION_CYCLE)],
        })
    title = writer_out.get("title") or ""
    hook = writer_out.get("hook") or ""
    keyword, metaphor = derive_keyword_metaphor(fact, title)
    script = " ".join(s["voiceover"] for s in scenes if s["voiceover"])
    return {
        "title": title,
        "viewer_job": job_name,
        "keyword": keyword,
        "metaphor": metaphor,
        "vibe": derive_vibe(treatment_name),
        "hook": hook,
        "hook_headline": derive_hook_headline(hook),
        "script": script,
        "scenes": scenes,
        "captions": derive_captions(hook, cta_style),
        "hashtags": derive_hashtags((fact or {}).get("domain", "")),
        "render": {"voice": "en-US-GuyNeural", "rate": "-5%", "resolution": "1080x1920"},
        "treatment": treatment_name,
        "cta_style": cta_style,
        "payoff": writer_out.get("payoff", ""),
    }
