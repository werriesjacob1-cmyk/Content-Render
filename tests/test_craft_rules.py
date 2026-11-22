#!/usr/bin/env python3
"""Zero-network regressions for craft_rules.py (the Writer's craft layer).

The user's standing complaints -- purple wording, crutch phrases, a payoff that
restates the hook, no re-hook, endings nobody argues with -- used to live ONLY
as prompt prose. The load-bearing tests here are the DRIFT tests: every item the
live prompt names is mechanically caught, and what validate() enforces is
exactly what the prompt says.
"""
from __future__ import annotations

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import craft_rules as C
import generate as G


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _live_prompt():
    return G.build_prompt("EXPLAIN", "explain a thing", "none", fact=None, cta_style="COMMENT")


def test_prompt_names_every_banned_item():
    block = C.prompt_block()
    live = _live_prompt()
    check(block in live, "the live build_prompt() contains the craft block verbatim")
    for word, _ in C.PURPLE_WORDS:
        check(word in block, f"prompt block names purple word {word!r}")
    for phrase, _ in C.CRUTCH_PHRASES:
        check(phrase in block, f"prompt block names crutch phrase {phrase!r}")


def test_every_listed_item_is_caught():
    for word, _ in C.PURPLE_WORDS:
        check(C.find_purple(f"The tide {word} slowly.") is not None, f"purple {word!r} is caught")
    for phrase, _ in C.CRUTCH_PHRASES:
        check(C.find_crutch(f"Okay. {phrase}.") is not None, f"crutch {phrase!r} is caught")
    # the exact examples from the user's complaint list
    for t in ("The petals unfurl at dawn.", "an undisputed champion", "a vast network",
              "an endless predator"):
        check(C.find_purple(t) is not None, f"user example caught: {t!r}")
    check(C.find_crutch("But that’s not even the strangest part.") is not None,
          "curly apostrophe does not defeat the crutch check")
    check(C.find_crutch("Most people still think it is a plant.") is not None,
          "'most people still think' caught")
    # plain wording is NOT flagged (no false positive on near-misses)
    check(C.find_purple("It grows in the advantage of shade.") is None, "'advantage' is not 'vast'")
    check(C.find_crutch("Nobody thinks it is a plant.") is None, "'nobody thinks' is fine")
    check(C.find_purple("The fungus spreads under three square miles.") is None, "plain line passes")


def test_payoff_must_add_an_idea():
    hook = "A single fungus in Oregon is the biggest living thing on Earth."
    restating = "So you were standing on the biggest living thing on Earth."
    new_idea = "Scientists still argue whether that counts as one animal or a million."
    check(C.payoff_restates_hook(hook, restating), "a payoff that repeats the hook is flagged")
    check(not C.payoff_restates_hook(hook, new_idea), "a payoff that adds a new idea passes")
    check(not C.payoff_restates_hook(hook, "Wow."), "a too-short line is not judged on overlap")
    # numbers pinned so the prompt's '60%' cannot drift from the enforced one
    check(f"{int(C.PAYOFF_MAX_HOOK_OVERLAP * 100)}%" in C.prompt_block(),
          "the prompt states the SAME overlap limit validate() enforces")


def test_rehook_windows():
    check(C.rehook_windows([13] * 8) == [[2, 3], [5, 6]], "a ~42s script has a 15s and a 30s window")
    w = C.rehook_windows([8] * 8)
    check(len(w) == 1 and w[0], "a ~26s short only needs the 15s re-hook")
    check(C.rehook_windows([5] * 5) == [], "a very short script has no re-hook window")
    check(all(0 not in grp for grp in C.rehook_windows([13] * 8)), "scene 0 (the hook) never counts")


def _flat(n=8):
    hook = "Your thumbnail is older than any mountain range you can name."
    vos = [hook] + [f"Plain sentence number {i} about rocks and time and nothing else." for i in range(1, n)]
    return hook, vos


def test_check_script_enforces_each_rule():
    hook, vos = _flat()
    err = C.check_script(hook, vos)
    check(err and "re-hook" in err, f"no question near 15s/30s is rejected ({err})")

    # a script with questions in the windows and a fresh payoff passes
    good = list(vos)
    good[2] = "So why does it keep growing? Nobody checked until recently."
    good[6] = "And what happens when it stops? The rock record has the answer."
    good[7] = "Scientists still argue whether time or pressure did the real work."
    check(C.check_script(hook, good) is None, "re-hooked, fresh-payoff script passes")

    bad = list(good); bad[3] = "The petals unfurl across the stone."
    check("purple" in (C.check_script(hook, bad) or ""), "purple word in a scene is rejected")
    bad = list(good); bad[4] = "That's not even the strangest part."
    check("crutch" in (C.check_script(hook, bad) or ""), "crutch phrase in a scene is rejected")
    check("purple" in (C.check_script("An endless thumbnail outlives mountains.", good) or ""),
          "purple word in the HOOK is rejected")
    bad = list(good); bad[7] = "Your thumbnail is older than any mountain range you can name."
    check("restates" in (C.check_script(hook, bad) or ""), "payoff restating the hook is rejected")


def test_validate_runs_the_craft_layer():
    """The checker is wired into validate() itself, not just importable."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import test_pipeline as TP
    m = copy.deepcopy(TP.FIX_ASTRO)
    check(G.validate(copy.deepcopy(m), "EXPLAIN") is None, "baseline fixture passes validate()")
    m["scenes"][4]["voiceover"] = "Stranger still, it spins backwards and its sky unfurls in orange."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    err = G.validate(m, "EXPLAIN")
    check(err is not None and "purple" in err, f"validate() rejects a purple word ({err})")


RUN455_HOOK = "Right now, atmospheric pressure is keeping the water inside your body from boiling."
RUN455 = [
    RUN455_HOOK,
    "If an airlock blew open, would your body pop like a balloon?",
    "Your tough collagen skin actually stretches instead of bursting.",
    "So why do you still pass out in only 15 seconds?",
    "In a vacuum, your lungs violently reverse, stripping oxygen backward out of your blood.",
    "Can a human survive ebullism when fluids boil at normal body temperature?",
    "In 1965, an exposed NASA technician felt his saliva boil and made a full recovery.",
    "Since animals survive two minutes flatlined,",
    "should vacuum decompression be treated as a rescue window or certain death?",
]


def _vacuum():
    import json
    bank = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "topic_bank.json")))
    return {f["id"]: f for f in bank["facts"]}["human_vacuum"]


def test_run455_script_is_rejected_for_the_right_reasons():
    f = _vacuum()
    check(C.check_script(RUN455_HOOK, RUN455, f) is not None, "the real run-455 script no longer passes")
    clean = [RUN455_HOOK] + [f"Plain line {i}." for i in range(1, 8)]
    check("contradicts" in (C.check_script(RUN455_HOOK, clean, f) or ""),
          "the mechanism-first hook is rejected even when the rest of the script is clean")
    check("collagen" in C.check_script(RUN455_HOOK, RUN455, f), "and the full script trips the first banned word it reaches (collagen)")
    ok_hook = "Your body would not explode in space."
    for bad, why in (("ebullism", "jargon"), ("collagen", "jargon"), ("decompression", "jargon"),
                     ("violently", "purple")):
        vos = [ok_hook] + [f"Plain line {i}." for i in range(1, 8)]
        vos[2] = f"It is the {bad} that matters."
        err = C.check_script(ok_hook, vos, f)
        check(err and bad in err, f"{bad!r} ({why}) is rejected")


def test_bank_no_longer_forces_jargon():
    f = _vacuum()
    check("ebullism" not in [k.lower() for k in f["key_terms"]] and "ebullism" in f.get("optional_terms", []),
          "human_vacuum no longer MANDATES the word 'ebullism'")
    check(len(f["key_terms"]) >= 2, "it still has enough plain key terms to satisfy validate()")
    check(f.get("misconception") and f.get("open_question") is None, "misconception set; no invented open question")


def test_hook_first_and_ending_rules_follow_the_fact():
    f = _vacuum()
    hook = "Your body would not explode in space."
    vos = [hook, "You would stay conscious for about 15 seconds.", "Your skin is tough enough to hold you together.",
           "So why do you black out so fast?", "The air in your lungs rushes out and drags the oxygen from your blood.",
           "That air is gone in a couple of seconds, and the blood keeps flowing to your brain without it.",
           "What did a NASA technician feel in 1965 when his suit lost pressure? His saliva began to boil.",
           "He passed out in about 14 seconds and recovered once the chamber was repressurised.",
           "So the real danger of a vacuum is how little time you have, not an explosion."]
    check(C.check_script(hook, vos, f) is None, f"a hook-first, statement-ending script passes ({C.check_script(hook, vos, f)})")
    q_end = vos[:-1] + ["So is the real danger the time you have, or the explosion?"]
    check("no genuinely open" in (C.check_script(hook, q_end, f) or ""), "a question ending is rejected when the fact has no open question")
    oq = dict(f, open_question="Is a vacuum survivable if help arrives within seconds?")
    check("open question" in (C.check_script(hook, vos, oq) or ""), "when the fact HAS an open question the ending must pose it")
    ok_end = vos[:-1] + ["Is a vacuum survivable if help arrives within seconds?"]
    check(C.check_script(hook, ok_end, oq) is None, "posing it passes")
    many = list(vos); many[1] = "Would you really stay awake?"; many[2] = "Would your skin hold?"
    check("questions in the narration" in (C.check_script(hook, many, f) or ""), "more than 3 questions is rejected")


def test_cta_remap_and_prompt_follow_the_fact():
    f = _vacuum()
    check(C.effective_cta_style("COMMENT", f) == "SAVE_WORTHY", "COMMENT becomes a payoff when there is no open question")
    check(C.effective_cta_style("COMMENT", dict(f, open_question="Why?")) == "COMMENT", "COMMENT stays when there is one")
    check(C.effective_cta_style("LOOP", f) == "LOOP", "other styles are untouched")
    block = C.prompt_block(f)
    check("MISCONCEPTION FIRST" in block and f["misconception"] in block, "the hook-first rule names this fact's misconception")
    check(C.ENDING_STATEMENT_RULE in block, "no open question -> the prompt says end on a statement")
    oq_block = C.prompt_block(dict(f, open_question="Is it survivable?"))
    check("Is it survivable?" in oq_block and C.ENDING_STATEMENT_RULE not in oq_block, "an open question is handed to the writer verbatim")
    check("MISCONCEPTION FIRST" not in C.prompt_block({}), "a fact without a misconception gets no hook-first rule")
    for w, _ in C.EXTRA_JARGON:
        check(w in block, f"prompt names jargon word {w!r}")
    check("MISCONCEPTION FIRST" in G.build_prompt("EXPLAIN", "explain a thing", "none", fact=f, cta_style="COMMENT"),
          "build_prompt() carries the fact-specific rules")
    check("COMMENT" not in G.CTA_ENDING_RULES.get("NONE", ""), "sanity")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ALL PASS")
