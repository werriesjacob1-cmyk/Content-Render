"""Single source of truth for the Writer's CRAFT rules (pure, zero-network).

Why this module exists
----------------------
The user's standing complaints about the videos (purple wording, crutch phrases,
a payoff that restates the hook, scripts that never re-hook, endings nobody
argues with) were all *prompt prose only*. Prose a model is free to ignore is
not a rule. Every rule here is therefore defined ONCE, as data, and consumed by
BOTH sides:

  * ``prompt_block()``  -- the text injected into the live Writer prompt
                           (generate.build_prompt), built from these constants;
  * ``check_script()``  -- the mechanical check generate.validate() runs.

``tests/test_craft_rules.py`` asserts every banned item appears in the prompt
text and is caught by the checker, so the two can never silently drift (the
same anti-drift pattern as ``generate.writer_length_contract``).

This module imports nothing from the pipeline, so generate.py, writer_v2.py and
the tests can all import it without a cycle.
"""
from __future__ import annotations

import re

# --- 1. Purple / literary wording -----------------------------------------
# (display form shown to the model, regex that catches every inflection)
PURPLE_WORDS = (
    ("unfurls", r"unfurl\w*"),
    ("cascades", r"cascad(?:e|es|ed|ing)"),
    ("dances", r"dances"),
    ("whispers", r"whispers"),
    ("beckons", r"beckon(?:s|ed|ing)?"),
    ("undisputed", r"undisputed"),
    ("vast", r"vast(?:ly)?"),
    ("endless", r"endless(?:ly)?"),
    ("violently", r"violent(?:ly)?"),
    ("betrays", r"betray(?:s|ed|ing)?"),
)

# --- 2. Crutch / filler phrases --------------------------------------------
CRUTCH_PHRASES = (
    ("that's not even the strangest part",
     r"not even the (?:strange|strangest|weird|weirdest|craziest|wildest|best) part"),
    ("here's where it gets weird",
     r"here'?s where (?:it|things) (?:gets?|got|starts?) (?:weird|strange|crazy)"),
    ("where it stops making sense", r"where it stops making sense"),
    ("but that's not all", r"but that'?s not all"),
    ("most people still think",
     r"most people (?:still )?(?:think|believe|assume|know|don'?t (?:know|realize))"),
    ("it gets even weirder",
     r"(?:it|things) gets? (?:even )?(?:weirder|stranger|crazier)"),
)

# Words a smart 15-year-old would not know, or that read as written, not spoken. They
# come from real shipped videos (run 455: "ebullism", "tough collagen", "decompression").
# Each is a (display, regex) pair so the prompt and the check cannot drift.
EXTRA_JARGON = (
    ("ebullism", r"ebullism"),
    ("cryptobiosis", r"cryptobiosis"),
    ("decompression", r"decompress(?:ion|ed)?"),
    ("collagen", r"collagen"),
)

MAX_QUESTIONS = 3          # questions in the narration (ending question earns one more)


_PURPLE_RE = re.compile(r"\b(?:" + "|".join(p for _, p in PURPLE_WORDS) + r")\b", re.I)
_JARGON_RE = re.compile(r"\b(?:" + "|".join(p for _, p in EXTRA_JARGON) + r")\b", re.I)
_CRUTCH_RE = re.compile("(?:" + "|".join(p for _, p in CRUTCH_PHRASES) + ")", re.I)


def _norm(text):
    # curly apostrophes -> straight so "that’s" matches "that's"
    return (text or "").replace("’", "'").replace("‘", "'")


def find_purple(text):
    m = _PURPLE_RE.search(_norm(text))
    return m.group(0) if m else None


def find_jargon(text):
    m = _JARGON_RE.search(_norm(text))
    return m.group(0) if m else None


def find_crutch(text):
    m = _CRUTCH_RE.search(_norm(text))
    return m.group(0) if m else None


# --- 3. The payoff must ADD an idea, never restate the hook ----------------
_STOP = frozenset("""
a an the and or but so if then than that this these those it its it's is are was
were be been being am do does did done have has had having to of in on at by for
with from as into onto over under about above below up down out off again once
you your yours we our us they their them he she his her i me my not no yes can
could would should will just very more most much many some any each every all
there here what when where why how who whom which also even still too only own
same such now one two get got make made like really every thing things
""".split())


def _stem(w):
    w = re.sub(r"[^a-z0-9]", "", w.lower())
    for suf in ("ing", "ed", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def content_stems(text):
    return {s for s in (_stem(w) for w in re.findall(r"[A-Za-z0-9']+", _norm(text)))
            if s and len(s) > 2 and s not in _STOP}


# A payoff line is "restating the hook" when most of its meaningful words were
# already spoken in the hook. Both numbers are exposed so the test can pin them.
PAYOFF_MIN_CONTENT_WORDS = 3
PAYOFF_MAX_HOOK_OVERLAP = 0.6


def payoff_overlap(hook, final_line):
    """(overlap_fraction, n_content_words) of the final line vs the hook."""
    f = content_stems(final_line)
    if not f:
        return 0.0, 0
    return len(f & content_stems(hook)) / len(f), len(f)


def payoff_restates_hook(hook, final_line):
    frac, n = payoff_overlap(hook, final_line)
    return n >= PAYOFF_MIN_CONTENT_WORDS and frac >= PAYOFF_MAX_HOOK_OVERLAP


# --- 4. Re-hook at ~15 s and ~30 s -----------------------------------------
REHOOK_MARKS_S = (15.0, 30.0)
SPOKEN_WORDS_PER_SECOND = 2.5     # ~105 words ~= 42 s on the live voices
REHOOK_MIN_TAIL_S = 5.0           # no re-hook needed if the video ends within 5 s


REHOOK_WINDOW_S = 3.0             # "~15 s" means any scene overlapping 15 s +/- 3 s


def rehook_windows(word_counts):
    """One list of scene indexes per re-hook mark: every scene (never scene 0, the
    hook) whose spoken span overlaps mark +/- REHOOK_WINDOW_S.

    A mark only counts when the video runs at least REHOOK_MIN_TAIL_S past it
    (a ~30 s short has no 30 s re-hook)."""
    total_s = sum(word_counts) / SPOKEN_WORDS_PER_SECOND
    spans, acc = [], 0.0
    for wc in word_counts:
        spans.append((acc / SPOKEN_WORDS_PER_SECOND, (acc + wc) / SPOKEN_WORDS_PER_SECOND))
        acc += wc
    out = []
    for mark in REHOOK_MARKS_S:
        if total_s < mark + REHOOK_MIN_TAIL_S:
            continue
        lo, hi = mark - REHOOK_WINDOW_S, mark + REHOOK_WINDOW_S
        idx = [i for i, (a, b) in enumerate(spans) if i >= 1 and a < hi and b > lo]
        if idx:
            out.append(idx)
    return out


def has_rehook(voiceover):
    """A re-hook is a fresh question the viewer now wants answered."""
    return "?" in (voiceover or "")


# --- 5. Ending: a question/belief people will argue with -------------------
ENDING_STATEMENT_RULE = (
    "ENDING: end on a plain STATEMENT that adds one new idea the hook did not contain -- the "
    "implication, the consequence, or the proof. Do NOT end on a question: this fact has no "
    "genuinely open question, and a manufactured one reads as fake outrage. Never restate the "
    "hook or the reveal in new words."
)


def ending_open_question_rule(question):
    return (
        "ENDING: end on THIS genuinely open question from the verified material, in your own plain "
        f"words: \"{question}\" Both answers must be defensible with the facts you gave. It must ADD "
        "an idea the hook did not contain; never restate the hook."
    )


def misconception_rule(misconception):
    return (
        "- MISCONCEPTION FIRST: the hook states the TRUE claim that contradicts this common belief, in "
        f"plain words, in its first line: \"{misconception}\" The mechanism comes AFTER the hook, as "
        "the answer to it -- never open on the mechanism. BAD (mechanism first, belief never "
        "challenged): \"Right now, atmospheric pressure is keeping the water inside your body from "
        "boiling.\" GOOD: \"Your body would not explode in space.\"\n"
    )


def effective_cta_style(cta_style, fact):
    """COMMENT means 'end on the open question'. A fact with no open_question has none,
    so COMMENT becomes a resonant payoff instead of a manufactured argument."""
    if cta_style == "COMMENT" and not (fact or {}).get("open_question"):
        return "SAVE_WORTHY"
    return cta_style


def prompt_block(fact=None):
    """The craft-rules text for the live Writer prompt, built from the constants
    above so the prompt can never name a rule check_script() does not enforce."""
    fact = fact or {}
    purple = ", ".join(w for w, _ in PURPLE_WORDS)
    crutch = "; ".join(f'"{c}"' for c, _ in CRUTCH_PHRASES)
    jargon = ", ".join(w for w, _ in EXTRA_JARGON)
    oq = (fact.get("open_question") or "").strip()
    mis = (fact.get("misconception") or "").strip()
    return (
        "CRAFT RULES (each one is checked MECHANICALLY after you write -- a script that breaks one is "
        "rejected and you will have to redo it):\n"
        + (misconception_rule(mis) if mis else "")
        + f"- BANNED PURPLE WORDS (any form): {purple}. Say it the way a person talking would.\n"
        f"- BANNED CRUTCH PHRASES: {crutch}. Just state the next real fact.\n"
        f"- BANNED JARGON: {jargon}. Explain the thing in plain words; never name it.\n"
        "- SEARCH QUERIES LEAD WITH THE SUBJECT NOUN: 'space stars', 'lungs breathing' -- never an "
        f"adjective first ({', '.join(sorted(GENERIC_QUERY_MODIFIERS)[:8])}, ...).\n"
        f"- THE PAYOFF ADDS A NEW IDEA. The final line may reuse at most {int(PAYOFF_MAX_HOOK_OVERLAP * 100)}% "
        "of its meaningful words from the hook; if you are circling back to the opening claim, "
        "you have not written a payoff yet. BAD (restates the hook): hook \"This fungus is one "
        "living thing.\" ending \"So you were standing on one endless living thing.\" GOOD: an "
        "implication the hook never said.\n"
        "- RE-HOOK TWICE: somewhere in the scenes spoken around the 15-second mark (about word 38) AND "
        "around the 30-second mark (about word 75; a ~30 s short only needs the first), ask a fresh "
        "QUESTION the viewer now wants answered -- a new open loop, not a recap.\n"
        f"- AT MOST {MAX_QUESTIONS} QUESTIONS in the narration" +
        (" (plus the one ending question)" if oq else "") +
        ": more than that is a wall of interrogatives, not a story. Everything else is a statement.\n"
        f"- {ending_open_question_rule(oq) if oq else ENDING_STATEMENT_RULE}\n"
    )


def _shared(a, b):
    return len(content_stems(a) & content_stems(b))


def check_script(hook, voiceovers, fact=None):
    """Mechanical enforcement of the rules above. Returns an error string or None.

    `voiceovers` is the list of scene voiceovers in order; `fact` (optional) is the bank
    fact, whose misconception/open_question fields switch on the hook and ending rules.
    Order of checks is the order a writer can most cheaply fix them."""
    fact = fact or {}
    texts = [hook or ""] + [v or "" for v in voiceovers]
    for i, t in enumerate(texts):
        where = "hook" if i == 0 else f"scene {i - 1} voiceover"
        p = find_purple(t)
        if p:
            return (f"{where} uses the banned purple word {p!r} — say it plainly, the way a person "
                    f"talking would")
        j = find_jargon(t)
        if j:
            return (f"{where} uses the jargon word {j!r} — a smart 15-year-old would not know it; "
                    f"describe the thing in plain words instead of naming it")
        c = find_crutch(t)
        if c:
            return (f"{where} uses the banned crutch phrase {c!r} — just state the next real fact "
                    f"instead of announcing that something is coming")
    mis = (fact.get("misconception") or "").strip()
    if mis:
        anchor = mis + " " + " ".join(str(k) for k in fact.get("key_terms", []))
        if _shared(hook, anchor) < 2:
            return (f"the hook {hook!r} does not state the claim that contradicts the common belief "
                    f"{mis!r} — open on the surprising TRUE claim first; the mechanism answers it afterwards")
    if voiceovers:
        final = voiceovers[-1]
        if payoff_restates_hook(hook, final):
            frac, _ = payoff_overlap(hook, final)
            return (f"the final line {final!r} restates the hook ({int(frac * 100)}% of its meaningful "
                    f"words were already in the hook) — the payoff must add a NEW idea, not circle back")
        oq = (fact.get("open_question") or "").strip()
        ends_q = final.rstrip().endswith("?")
        if ends_q and not oq:
            return (f"the final line {final!r} is a question but this fact has no genuinely open "
                    f"question — end on a plain statement that adds a new idea")
        if oq and not (ends_q and _shared(final, oq) >= 2):
            return (f"this fact has a genuinely open question ({oq!r}) — the final line must pose it "
                    f"(as a question, in plain words); got {final!r}")
        n_q = sum(v.count("?") for v in voiceovers)
        cap = MAX_QUESTIONS + (1 if ends_q else 0)
        if n_q > cap:
            return (f"{n_q} questions in the narration (max {cap}) — it reads as a wall of "
                    f"interrogatives; turn the extras into plain statements")
        counts = [len(v.split()) for v in voiceovers]
        for idxs in rehook_windows(counts):
            if not any(has_rehook(voiceovers[i]) for i in idxs):
                return (f"no question near the ~15s/~30s re-hook mark (scenes {idxs[0]}-{idxs[-1]} "
                        f"cover it) — re-hook the viewer there with a fresh question (a new open "
                        f"loop), not a recap")
    return None


# --- 6. Search queries must LEAD with the subject noun -----------------------
# The footage code treats a query's first content word as its SUBJECT and gates extra clips on
# it. Run 457's "empty space stars" and "human lungs breathing" led with an adjective, so the
# gate matched an empty parking structure and a tortoise. One set, used by the validator and
# by main._subject_word, so the two can never disagree.
GENERIC_QUERY_MODIFIERS = frozenset({
    "empty", "human", "real", "whole", "entire", "single", "outer", "inner", "typical", "generic",
    "abstract", "natural",
})


def leading_modifier(query):
    """The first content word of a search query if it is a generic modifier, else None."""
    for w in re.findall(r"[a-z]+", (query or "").lower()):
        if len(w) > 2 and w not in _STOP:
            return w if w in GENERIC_QUERY_MODIFIERS else None
    return None
