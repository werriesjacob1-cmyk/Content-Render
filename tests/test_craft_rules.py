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


def test_ending_rule_is_in_every_style():
    block = C.prompt_block()
    check(C.DEBATE_ENDING_RULE in block, "debate-ending rule is in the live prompt for every style")
    check("defensible BOTH ways" in G.CTA_ENDING_RULES["COMMENT"],
          "COMMENT style asks for a genuinely either-way question")
    check("never invent controversy" in G.CTA_ENDING_RULES["COMMENT"],
          "COMMENT style forbids manufactured controversy")
    check("recasts the hook" not in G.CTA_ENDING_RULES["SAVE_WORTHY"],
          "SAVE_WORTHY no longer invites the hook to be restated")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ALL PASS")
