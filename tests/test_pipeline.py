#!/usr/bin/env python3
"""
Local, ZERO-QUOTA pipeline regression tests.

Runs the render pipeline's trickiest PURE logic — the exact code paths that
produced the footage/caption/timing bugs in the review log — against several
DIFFERENT-topic script fixtures, with no ffmpeg, no network, and no LLM calls.
Catches regressions before they ever reach a real Actions render (which is
quota-gated and slow to iterate on).

What it exercises:
  main.py
    - _align_words_by_content : caption content-alignment (the "subtitles
      drift after one segmentation diff" / "42 twice" family of bugs)
    - _diversify_scene_queries : footage variety (run-53 "lingered 20s on the
      same water-droplet clip")
    - _keywords_from_text, _prefix_starts, _chars_to_words
    - build_ass (fallback timing path) : captions monotonic and inside their
      scene's spoken span across a whole multi-scene video
  generate.py
    - validate() : script quality gates, across 5 clean multi-topic scripts
      (must PASS) and a battery of intentionally-broken ones (must be REJECTED)
    - _slugify, _hits_banned_concept, _metaphor_too_similar, overused_hook_openers
    - fast-fail-when-throttled: circuit-open generate_candidate returns instantly
      (the wall-clock-budget work), GEN_WALL_BUDGET_S sane + env-overridable

Run:  GROQ_API_KEY=x python tests/test_pipeline.py
Exit code is non-zero if any assertion fails.
"""
import os, sys, re, time, tempfile

os.environ.setdefault("GROQ_API_KEY", "x")          # let generate.py import
# Pin the A/B video length to LONG so validate() uses the 85-115 word window the
# ~104-word fixtures below were written for — otherwise 'auto' mode reads the repo's
# memory history (its parity flips the window) and the fixtures fail nondeterministically.
os.environ.setdefault("LENGTH_MODE", "long")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M
import generate as G
import expand_bank as E
import funnel as F
import repackage as R
import writer_v2 as W2
import json as _json

# --------------------------------------------------------------------------
# tiny test harness
# --------------------------------------------------------------------------
_PASS = 0
_FAIL = 0

def check(cond, label):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {label}")
    else:
        _FAIL += 1
        print(f"  FAIL  {label}")

def section(title):
    print(f"\n=== {title} ===")


def scenes(*triples):
    """(voiceover, on_screen_text, search_query) -> scene dicts."""
    out = []
    for i, (vo, ost, q) in enumerate(triples, 1):
        out.append({"id": i, "voiceover": vo, "on_screen_text": ost,
                    "search_query": q, "duration": 4, "motion": "zoom_in"})
    return out


def manifest(title, hook, sc):
    return {
        "title": title,
        "hook": hook,
        # realistic default cover-thumbnail headline (2026-08-03: now a
        # required field) -- derived from title, not hook, so it never
        # collides with the new hook/headline near-duplicate check
        "hook_headline": title.upper()[:40],
        "script": " ".join(s["voiceover"] for s in sc),
        "scenes": sc,
        "captions": [title],
        "hashtags": ["#science"],
    }


# --------------------------------------------------------------------------
# 5 clean, DIFFERENT-topic scripts that must all pass validate()
# (astronomy, biology, geology, physics, chemistry). These double as the
# "different topics" the reviewer wants pipeline coverage across.
# --------------------------------------------------------------------------
FIX_ASTRO = manifest(
    "A Day Longer Than a Year",
    "One planet's day lasts longer than its entire year.",
    scenes(
        ("On Venus a single day is longer than its whole year.", "VENUS DAY", "venus planet space"),
        ("The planet turns so slowly that one spin takes 243 Earth days.", "243 DAYS", "planet rotation animation"),
        ("But it circles the Sun in only 225 Earth days.", "225 DAYS", "orbit around sun"),
        ("So the sunrise comes around just twice in one Venus year.", "TWO SUNRISES", "sunrise horizon planet"),
        ("Stranger still, it spins backwards compared with almost every other planet.", "SPINS BACKWARD", "spinning globe reverse"),
        ("Stand there and the Sun would rise in the west and set in the east.", "WEST TO EAST", "desert sun west"),
        ("A clock on Venus would make almost no sense to us at all.", "NO NORMAL CLOCK", "old clock face"),
        ("Even the thick sky there glows a dull orange beneath its heavy clouds.", "ORANGE SKY", "orange cloudy sky"),
    ),
)

FIX_BIO = manifest(
    "The Animal That Survives Space",
    "A creature smaller than a grain of sand survived open space.",
    scenes(
        ("A tiny animal called a tardigrade can survive the vacuum of space.", "TARDIGRADE", "water bear tardigrade"),
        ("It is under a millimetre long and lives in moss and puddles.", "UNDER 1 MM", "green moss macro"),
        ("When conditions turn deadly it curls up and dries out completely.", "DRIES OUT", "dry cracked ground"),
        ("In this state it can shrug off temperatures near minus 272 degrees.", "NEAR MINUS 272", "ice frozen crystals"),
        ("It can also take radiation that would kill a human many times over.", "HUGE RADIATION", "radiation warning glow"),
        ("Scientists once sent some into orbit and exposed them to raw space.", "SENT TO ORBIT", "satellite earth orbit"),
        ("They manage this by replacing the water in their cells with a glassy sugar that shields every part.", "GLASS TRICK", "glass crystal macro"),
        ("Back on the ground, many woke up and had healthy babies.", "WOKE UP FINE", "baby animals nature"),
    ),
)

FIX_GEO = manifest(
    "There Is a Metal Ball Inside Earth",
    "Deep under your feet sits a ball of metal as hot as the Sun's surface.",
    scenes(
        ("Right under your feet is a solid ball of iron the size of the Moon.", "IRON BALL", "molten metal glow"),
        ("It sits about 5000 kilometres down at the centre of the planet.", "5000 KM DOWN", "earth cross section"),
        ("Its surface is roughly as hot as the surface of the Sun.", "SUN-HOT", "sun surface texture"),
        ("Yet crushing pressure keeps that iron solid instead of molten.", "STAYS SOLID", "deep pressure rock"),
        ("Around it a churning liquid outer core keeps everything moving.", "LIQUID SHELL", "swirling lava flow"),
        ("That motion generates the magnetic field that guides every compass.", "MAKES MAGNETISM", "compass needle north"),
        ("Strangely, that inner ball is thought to spin a little faster than the rest of the planet does.", "SPINS FASTER", "spinning core animation"),
        ("Without it, the solar wind would slowly strip our air away.", "SHIELDS THE AIR", "aurora night sky"),
    ),
)

FIX_PHYS = manifest(
    "Hot Water Can Freeze First",
    "Under the right conditions hot water freezes faster than cold water.",
    scenes(
        ("Sometimes hot water freezes faster than cold water in the same freezer.", "HOT WINS", "ice cubes freezer"),
        ("People noticed it for centuries before anyone took it seriously.", "OLD PUZZLE", "old handwriting notes"),
        ("A schoolboy named Mpemba pushed scientists to study it properly.", "MPEMBA EFFECT", "student classroom"),
        ("Warm water near 90 degrees loses mass to evaporation, so less has to freeze.", "LESS TO FREEZE", "steam rising water"),
        ("Dissolved gases and currents inside the warm cup also play a part.", "GAS AND FLOW", "bubbles in water"),
        ("The effect is fussy and does not happen every single time.", "NOT ALWAYS", "frost forming glass"),
        ("Cold water can also supercool below freezing and stubbornly refuse to turn to ice for a while.", "SUPERCOOL", "supercooled water ice"),
        ("It is a reminder that even boiling a kettle still hides mysteries.", "EVERYDAY MYSTERY", "kettle steam kitchen"),
    ),
)

FIX_CHEM = manifest(
    "The Metal You Can Melt in Your Hand",
    "One metal turns to liquid from nothing but the warmth of your palm.",
    scenes(
        ("There is a metal that melts from the warmth of your own hand.", "MELTS IN HAND", "shiny liquid metal"),
        ("It is called gallium and it looks just like solid silver.", "GALLIUM", "silver metal chunk"),
        ("Its melting point is only about 30 degrees Celsius.", "MELTS AT 30 C", "thermometer warm"),
        ("Hold a piece and it slowly slumps into a mirror-bright puddle.", "TURNS TO PUDDLE", "mercury like droplet"),
        ("Unlike mercury it is barely toxic, so labs handle it freely.", "LOW TOXICITY", "lab gloves beaker"),
        ("People use it for a prank spoon that vanishes into hot tea.", "VANISHING SPOON", "spoon in teacup"),
        ("Cool it back down and it hardens into silver once again.", "HARDENS AGAIN", "cooling metal solid"),
        ("Yet a solid bar of it holds its shape just fine on a cold winter day.", "SOLID WHEN COLD", "silver bar macro"),
    ),
)

CLEAN_FIXTURES = [("astronomy", FIX_ASTRO), ("biology", FIX_BIO),
                  ("geology", FIX_GEO), ("physics", FIX_PHYS),
                  ("chemistry", FIX_CHEM)]


# --------------------------------------------------------------------------
# 1. validate(): clean multi-topic scripts pass; broken scripts rejected
# --------------------------------------------------------------------------
def test_validate_clean():
    section("validate(): 5 clean different-topic scripts must PASS")
    for name, fix in CLEAN_FIXTURES:
        import copy
        err = G.validate(copy.deepcopy(fix), "EXPLAIN", fact=None)
        check(err is None, f"{name}: validate() -> {err!r}")


def test_validate_rejections():
    section("validate(): broken scripts must be REJECTED")
    import copy

    # repeated core number as the crux of 3+ scenes (the "42 twice", run-54 bug)
    m = copy.deepcopy(FIX_ASTRO)
    for i in (1, 2, 3):
        m["scenes"][i]["voiceover"] = "The spin takes 243 Earth days to finish once."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "repeated 243-days crux across scenes rejected")

    # near-identical adjacent scenes (pairwise similarity > 0.62)
    m = copy.deepcopy(FIX_BIO)
    m["scenes"][2]["voiceover"] = m["scenes"][1]["voiceover"]
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "duplicated adjacent scene voiceover rejected")

    # scene count out of range (too few) — floor is now 7 (was 6) to cut linger
    m = copy.deepcopy(FIX_GEO); m["scenes"] = m["scenes"][:4]
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "scene count 4 rejected")
    # boundary: 6 scenes now rejected, 7 accepted (given FIX_GEO has >=7)
    if len(FIX_GEO["scenes"]) >= 7:
        m6 = copy.deepcopy(FIX_GEO); m6["scenes"] = m6["scenes"][:6]
        m6["script"] = " ".join(s["voiceover"] for s in m6["scenes"])
        check(G.validate(m6, "EXPLAIN") is not None, "scene count 6 now rejected (floor raised to 7)")

    # a single run-on scene over the 22-word cap
    m = copy.deepcopy(FIX_PHYS)
    m["scenes"][3]["voiceover"] = ("warm water loses mass to evaporation and dissolved gases "
                                   "and convection currents and supercooling all interact in ways "
                                   "that make the whole thing genuinely hard to predict every time")
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "over-long run-on scene rejected")

    # banned generic save-command ending
    m = copy.deepcopy(FIX_CHEM)
    m["scenes"][-1]["voiceover"] = "Save this so you remember it later."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "generic 'save this' command rejected")

    # shipped Sep-1 failure: COMMENT mode encouraged a generic pseudo-payoff
    # ("everything you know about weather is wrong") instead of landing a real
    # scientific implication. This must be mechanically rejected.
    m = copy.deepcopy(FIX_ASTRO)
    m["scenes"][-1]["voiceover"] = "And that means everything you know about weather is wrong."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    err = G.validate(m, "EXPLAIN")
    check(err is not None and "generic pseudo-payoff" in err,
          f"generic 'everything you know is wrong' ending rejected ({err})")

    # shipped Sep-1 hook shape: a hypothetical catastrophe stated as though it
    # literally just happened to the viewer. Conditional stakes remain allowed.
    m = copy.deepcopy(FIX_ASTRO)
    m["hook"] = "Your phone just got hit by a bolt from the sky."
    err = G.validate(m, "EXPLAIN")
    check(err is not None and "hypothetical stakes" in err,
          f"fabricated present-tense stakes hook rejected ({err})")
    m = copy.deepcopy(FIX_ASTRO)
    m["hook"] = "If lightning hits your phone, the damage starts before you react."
    err = G.validate(m, "EXPLAIN")
    check(err is None, f"explicitly conditional high-stakes hook remains allowed ({err})")

    # abstract perception-vs-reality hook
    m = copy.deepcopy(FIX_ASTRO)
    m["hook"] = "You are seeing it as it was, not as it is."
    check(G.validate(m, "EXPLAIN") is not None, "abstract 'as it was not as it is' hook rejected")

    # DANGLING comparative hook (render-173: "T. rex is closer to you" — closer
    # than WHAT? — self-scored coherence missed it; this is the mechanical backstop)
    m = copy.deepcopy(FIX_ASTRO)
    m["hook"] = "Tyrannosaurus rex is closer to you than you think it should be."
    check(G.validate(m, "EXPLAIN") is None, "comparative WITH a 'than' completion is fine")
    m = copy.deepcopy(FIX_ASTRO)
    m["hook"] = "Tyrannosaurus rex is somehow closer to you."
    check(G.validate(m, "EXPLAIN") is not None, "dangling comparative with no 'than ___' rejected")

    # HOOK MUST NOT BE A QUESTION (render-215: "Why Ocean Currents Shape Our World"
    # shipped with hook "How do ocean currents keep London mild while Calgary at
    # the same latitude freezes?" -- an entire wind-up QUESTION as the very first
    # line, directly against the prompt's own "never as the very first line" rule,
    # which until now was prose-only and never actually enforced)
    m = copy.deepcopy(FIX_ASTRO)
    m["hook"] = "How do ocean currents keep London mild while Calgary at the same latitude freezes?"
    err = G.validate(m, "EXPLAIN")
    check(err is not None and "QUESTION" in err, f"a wind-up question as the entire hook is rejected ({err})")
    m = copy.deepcopy(FIX_ASTRO)
    m["hook"] = "One planet's day lasts longer than its entire year."
    check(G.validate(m, "EXPLAIN") is None, "a concrete statement hook (no '?') is fine")

    # BANNED WIND-UP OPENERS (2026-08-03, real TikTok analytics finding): the
    # prompt banned "Did you know"/etc as hook openers from early on, but it
    # was PROSE ONLY, never mechanically checked -- for the hook OR the
    # caption. The actual flopped "Your Brain Heals Itself" video (137 views,
    # 7.7s avg watch on a 38.6s video, 6.51% completion, 0 follows) shipped a
    # TikTok caption opening "Did you know your mind can act like a
    # pharmacy?" -- the literal banned pattern.
    m = copy.deepcopy(FIX_ASTRO)
    m["hook"] = "Did you know Venus spins backwards compared to every other planet."
    err = G.validate(m, "EXPLAIN")
    check(err is not None and "Did you know" in err, f"a 'Did you know' hook opener is rejected ({err})")
    for opener in ("Have you ever wondered why the sky turns orange at sunset.",
                   "Imagine standing on a planet where the sun rises in the west.",
                   "Here's why Venus spins backwards compared to every other planet."):
        m2 = copy.deepcopy(FIX_ASTRO)
        m2["hook"] = opener
        err2 = G.validate(m2, "EXPLAIN")
        check(err2 is not None and "banned wind-up phrase" in err2,
              f"banned opener {opener[:20]!r}... is rejected ({err2})")
    # the documented exception: "Ever wonder..." does NOT match "have you ever"
    m3 = copy.deepcopy(FIX_ASTRO)
    m3["hook"] = "Ever wonder why Venus spins backwards compared to every other planet."
    check(G.validate(m3, "EXPLAIN") is None, "'Ever wonder...' stays the documented allowed exception")
    # the SAME rule applies to captions[0] -- the actual TikTok post caption
    # (repackage.py's base_cap), not just the spoken hook
    m4 = copy.deepcopy(FIX_ASTRO)
    m4["captions"] = ["Did you know your mind can act like a pharmacy?", "science fact", "wow"]
    err4 = G.validate(m4, "EXPLAIN")
    check(err4 is not None and "TikTok post caption" in err4,
          f"a 'Did you know' CAPTION opener (not just hook) is rejected ({err4})")
    m5 = copy.deepcopy(FIX_ASTRO)
    m5["captions"] = ["Venus spins backwards compared to every other planet.", "science fact", "wow"]
    check(G.validate(m5, "EXPLAIN") is None, "a clean caption opener passes")

    # HOOK_HEADLINE (2026-08-03): the burned-on cover-thumbnail text -- what a
    # scrolling viewer sees BEFORE hearing a word. Required to exist (a missing
    # one reproduces the old "black tile in the grid" problem) and must not be
    # a near-duplicate of the spoken hook (the prompt explicitly wants it
    # different wording, not a restatement).
    m6 = copy.deepcopy(FIX_ASTRO)
    m6["hook_headline"] = ""
    err6 = G.validate(m6, "EXPLAIN")
    check(err6 is not None and "missing hook_headline" in err6, f"an empty hook_headline is rejected ({err6})")
    m7 = copy.deepcopy(FIX_ASTRO)
    del m7["hook_headline"]
    err7 = G.validate(m7, "EXPLAIN")
    check(err7 is not None and "missing hook_headline" in err7, f"an absent hook_headline field is rejected ({err7})")
    m8 = copy.deepcopy(FIX_ASTRO)
    m8["hook_headline"] = m8["hook"].upper()  # identical wording, just upper-cased
    err8 = G.validate(m8, "EXPLAIN")
    check(err8 is not None and "nearly identical to the spoken hook" in err8,
          f"a hook_headline that just restates the hook is rejected ({err8})")
    m9 = copy.deepcopy(FIX_ASTRO)
    m9["hook_headline"] = "A DAY LONGER THAN A YEAR"
    check(G.validate(m9, "EXPLAIN") is None, "a distinct, punchy hook_headline passes")

    # TOO-FORMAL / "sounds like a textbook" (render-177 'Continents in Motion':
    # "But is the distance between New York and London fixed?" then a flat "No.")
    m = copy.deepcopy(FIX_PHYS)
    m["scenes"][2]["voiceover"] = "But is the distance between the two cities fixed?"
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "stiff inverted textbook question rejected")

    m = copy.deepcopy(FIX_PHYS)
    m["scenes"][2]["voiceover"] = "No."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "lone 'No.' as an entire scene rejected")

    m = copy.deepcopy(FIX_PHYS)
    m["scenes"][2]["voiceover"] = "However, the water still freezes eventually."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "formal connector word ('however') rejected")

    # render 181/182 named jargon outright with no plain-language explanation
    # ("mycorrhizal networks", "hemocyanin") despite the prompt already banning it --
    # self-scored clarity missed both, so this is now a mechanical reject.
    m = copy.deepcopy(FIX_PHYS)
    m["scenes"][2]["voiceover"] = "An underground network of mycorrhizal fungi links the trees."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "named jargon ('mycorrhizal') rejected")

    m = copy.deepcopy(FIX_PHYS)
    m["scenes"][2]["voiceover"] = "Its blue blood, rich in hemocyanin, thrives in the cold."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "named jargon ('hemocyanin') rejected")

    # comma-stacked numeric + comparative clause (user feedback, petrichor video:
    # "at five parts per trillion, hundreds of times more sensitive than a shark
    # tracking blood" -- "not spoken in a methodic way or rhythm")
    m = copy.deepcopy(FIX_PHYS)
    m["scenes"][2]["voiceover"] = ("You detect geosmin at five parts per trillion, hundreds of "
                                    "times more sensitive than a shark tracking blood.")
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    err = G.validate(m, "EXPLAIN")
    check(err is not None and "rhythm" in err, f"comma-stacked numeric+comparative rejected ({err})")
    # the fixed, split version (two beats) must be ALLOWED
    m = copy.deepcopy(FIX_PHYS)
    m["scenes"][2]["voiceover"] = "You detect geosmin at five parts per trillion."
    m["scenes"][3]["voiceover"] = "That is hundreds of times more sensitive than a shark tracking blood."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is None, "split into two sentences (one beat each) is allowed")
    # an ordinary comma with no comparative clause on the other side must NOT fire
    check(G._comma_stacked_comparative("It weighs 200 kilograms, roughly the size of a small car.") is None,
          "an ordinary appositive comma (number, but no times/than comparative) does not fire")
    # a comparative with no number clause on the other side must NOT fire either
    check(G._comma_stacked_comparative("It is fast, and it is also very strong.") is None,
          "a comma with neither side being a numeric+comparative pair does not fire")

    # command ending: "send this to a friend" (the render-67 Krakatoa flaw). The
    # rubric bans command endings; SHARE is out of the rotation and the guard now
    # rejects the phrasing outright.
    m = copy.deepcopy(FIX_PHYS)
    m["scenes"][-1]["voiceover"] = "Send this to the friend who thinks they have heard it all."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "'send this to a friend' command ending rejected")
    check("SHARE" not in G.CTA_STYLES, "SHARE command-ending style removed from rotation")

    # The reference-worthy regex was intended only for scripts WITHOUT a bank
    # fact, but the implementation accidentally applied it to every script,
    # pressuring verified science videos to jam in a number/comparison. Prove
    # the scope: with the regex forced to match nothing, a non-bank script fails
    # that gate while a bank-backed script is allowed to rely on verified fact
    # and key-term machinery instead.
    _rw_orig = G.REFERENCE_WORTHY_RE
    try:
        G.REFERENCE_WORTHY_RE = re.compile(r"(?!x)x")
        no_fact = G.validate(copy.deepcopy(FIX_BIO), "EXPLAIN", fact=None)
        with_fact = G.validate(copy.deepcopy(FIX_BIO), "EXPLAIN", fact={"domain": "biology"})
        check(no_fact is not None and "reference-worthy" in no_fact,
              f"non-bank script still requires a reference-worthy detail ({no_fact})")
        check(with_fact is None,
              f"bank-backed script is not forced to add an arbitrary number/comparison ({with_fact})")
    finally:
        G.REFERENCE_WORTHY_RE = _rw_orig

    # contradictory COUNT of a discrete named thing (7 moons vs 12 moons) is a
    # real fabrication and must still be rejected by the contradiction guard.
    m = copy.deepcopy(FIX_ASTRO)
    m["scenes"][1]["voiceover"] = "This planet is circled by 7 moons in all."
    m["scenes"][4]["voiceover"] = "Astronomers have counted 12 moons around it so far."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    err = G.validate(m, "EXPLAIN")
    check(err is not None and "moons" in err, f"contradictory count '7 vs 12 moons' rejected ({err})")

    # un-filmable / stock-junk query
    m = copy.deepcopy(FIX_BIO)
    m["scenes"][0]["search_query"] = "human stomach anatomy diagram"
    check(G.validate(m, "EXPLAIN") is not None, "un-filmable anatomy query rejected")

    # NAMED LANDMARK comparison must be reflected in the query (render-215: "a
    # waterfall three times taller than Angel Falls" shipped with the generic
    # query "oceanography deep water ocean", never naming Angel Falls itself)
    m = copy.deepcopy(FIX_GEO)
    m["scenes"][2]["voiceover"] = "This massive plunge creates a waterfall three times taller than Angel Falls."
    m["scenes"][2]["search_query"] = "oceanography deep water ocean"
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    err = G.validate(m, "EXPLAIN")
    check(err is not None and "Angel Falls" in err, f"named-landmark comparison not reflected in the query is rejected ({err})")
    # naming the landmark in the query fixes it
    m2 = copy.deepcopy(m)
    m2["scenes"][2]["search_query"] = "Angel Falls waterfall Venezuela"
    check(G.validate(m2, "EXPLAIN") is None, "query that actually names the compared landmark is fine")
    # an ordinary (non-proper-noun) comparison must NOT fire
    m3 = copy.deepcopy(FIX_GEO)
    m3["scenes"][2]["voiceover"] = "It weighs far more than most people would ever guess."
    m3["script"] = " ".join(s["voiceover"] for s in m3["scenes"])
    check(G.validate(m3, "EXPLAIN") is None, "an ordinary comparison ('than most people') does not fire")

    # KEYWORD must appear in the script (2026-08-03): main.py pops the
    # manifest's 'keyword' words in the page's accent colour wherever they're
    # spoken -- a keyword that's a paraphrase of the script rather than the
    # SAME words means that on-screen highlight silently never fires.
    m4kw = copy.deepcopy(FIX_ASTRO)
    m4kw["keyword"] = "spinning backward slowly"
    check(G.validate(m4kw, "EXPLAIN") is None,
          "keyword whose words DO appear in the script (scene 5 says 'spins backwards') passes")
    m5kw = copy.deepcopy(FIX_ASTRO)
    m5kw["keyword"] = "underwater volcano eruption"
    err = G.validate(m5kw, "EXPLAIN")
    check(err is not None and "keyword-pop" in err,
          f"keyword whose words never appear anywhere in the script is rejected ({err})")
    m6kw = copy.deepcopy(FIX_ASTRO)
    check("keyword" not in m6kw, "sanity: fixture has no keyword field at all")
    check(G.validate(m6kw, "EXPLAIN") is None,
          "no keyword field at all -> not newly rejected (backward compatible)")

    # STACKED CONTRAST CLAUSE (render-215, second complaint on the same video:
    # "the timing just sounds like jumbled SHIT ... there is no flow" -- "How do
    # ocean currents keep London mild while Calgary at the same latitude
    # freezes?" smuggles a SECOND named place into a while-clause on top of the
    # sentence's own subject)
    m4 = copy.deepcopy(FIX_GEO)
    m4["scenes"][2]["voiceover"] = "Ocean currents keep London mild while Calgary at the same latitude freezes."
    m4["script"] = " ".join(s["voiceover"] for s in m4["scenes"])
    err = G.validate(m4, "EXPLAIN")
    check(err is not None and "London" in err, f"a while-clause stacking a second named place is rejected ({err})")
    # a clean single-entity comparison (the subordinate clause's subject is the
    # ONLY named entity -- the main clause's subject doesn't count) must NOT fire
    m5 = copy.deepcopy(FIX_GEO)
    m5["scenes"][2]["voiceover"] = "Mercury has no atmosphere while Venus is crushed by its own."
    m5["script"] = " ".join(s["voiceover"] for s in m5["scenes"])
    check(G.validate(m5, "EXPLAIN") is None, "a clean single-entity while-comparison does not fire")
    # "although" is covered the same way
    m6 = copy.deepcopy(FIX_GEO)
    m6["scenes"][2]["voiceover"] = "This keeps Denmark mild although Norway freezes every winter."
    m6["script"] = " ".join(s["voiceover"] for s in m6["scenes"])
    err6 = G.validate(m6, "EXPLAIN")
    check(err6 is not None and "Denmark" in err6, f"'although' stacking a second named place is also rejected ({err6})")

    # PLURAL bypass (render 181 bug): "system"/"organ"/"diagram" were banned but their
    # plain -s plurals slipped straight through the old \bsystem\b-style regex --
    # "resilient communication systems" (trees video, scene 6) shipped as the query
    # and rendered as a lingering generic abstract network-graphic ending scene.
    m = copy.deepcopy(FIX_BIO)
    m["scenes"][0]["search_query"] = "resilient communication systems"
    check(G.validate(m, "EXPLAIN") is not None, "plural 'systems' un-filmable query now rejected")
    m = copy.deepcopy(FIX_BIO)
    m["scenes"][0]["search_query"] = "human organs regrowing"
    check(G.validate(m, "EXPLAIN") is not None, "plural 'organs' un-filmable query now rejected")

    # render-209: cosmic/space-imagery search_query defaulted onto a scene whose
    # own voiceover has nothing to do with space, on a non-space-domain fact
    # ("night sky stars" on a human-ancestry payoff line). Only fires when a
    # `fact` with a domain is actually passed AND the scene's own voiceover is
    # silent on anything space-related -- both conditions must hold.
    bio_fact = {"domain": "biology"}
    m = copy.deepcopy(FIX_BIO)
    m["scenes"][-1]["search_query"] = "night sky stars"
    err = G.validate(m, "EXPLAIN", fact=bio_fact)
    check(err is not None and "cosmic" in err, f"cosmic-filler query on a non-space fact rejected ({err})")
    # no `fact` passed (fact=None, e.g. HOW_TO jobs) -> can't know the domain, so it
    # must NOT fire -- fails open rather than guessing
    check(G.validate(m, "EXPLAIN", fact=None) is None or "cosmic" not in (G.validate(m, "EXPLAIN", fact=None) or ""),
          "cosmic-filler check does not fire when no fact/domain is available")
    # the scene's OWN voiceover mentions something space-related -- deliberate,
    # not filler -- so it must NOT be rejected
    m2 = copy.deepcopy(FIX_BIO)
    m2["scenes"][-1]["voiceover"] = "Even a tardigrade sent under open sky and stars can survive it."
    m2["scenes"][-1]["search_query"] = "night sky stars"
    m2["script"] = " ".join(s["voiceover"] for s in m2["scenes"])
    check(G.validate(m2, "EXPLAIN", fact=bio_fact) is None,
          "cosmic query allowed when the scene's own voiceover is actually about the sky/stars")
    # an actual space/astronomy fact is exempt -- cosmic imagery is exactly right there
    space_fact = {"domain": "astronomy"}
    check(G.validate(m, "EXPLAIN", fact=space_fact) is None,
          "cosmic-filler query allowed outright on an astronomy-domain fact")

    # missing required field
    m = copy.deepcopy(FIX_PHYS); del m["hashtags"]
    check(G.validate(m, "EXPLAIN") is not None, "missing hashtags rejected")

    # REGRESSION: two DIFFERENT measurements sharing a unit are NOT a
    # contradiction and must be ALLOWED — "243 Earth days" (spin) vs "225 Earth
    # days" (orbit), "4.6 billion years" vs "5 billion years". Before the fix
    # these aborted good astronomy scripts before they could render.
    m = copy.deepcopy(FIX_ASTRO)
    m["scenes"][2]["voiceover"] = "The Sun will burn for about 5 billion years, then swell after 4 billion years."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    err = G.validate(m, "EXPLAIN")
    check(err is None or "contradictory" not in err,
          f"same-unit measurements (Earth days / billion years) not flagged as contradiction ({err})")


# --------------------------------------------------------------------------
# 2. _align_words_by_content: caption content alignment
# --------------------------------------------------------------------------
def test_content_alignment():
    section("main._align_words_by_content: caption sync stays anchored")

    # perfect 1:1 alignment -> each script word gets its heard time
    sw = "the core is solid iron".split()
    heard = [(w, float(i), float(i) + 0.5) for i, w in enumerate(sw)]
    out = M._align_words_by_content(sw, heard)
    check(len(out) == len(sw), "perfect match returns all words")
    check(all(out[i][1] == float(i) for i in range(len(sw))), "perfect match keeps true times")

    # the core bug: whisper SPLITS one script token ("243") into two heard
    # tokens ("two", "forty-three") mid-script. Index alignment would shift
    # every later caption; content alignment must keep the LAST word anchored
    # to its real spoken time.
    sw = "a spin takes 243 days here".split()
    heard = [("a", 0.0, 0.4), ("spin", 0.4, 0.8), ("takes", 0.8, 1.2),
             ("two", 1.2, 1.5), ("hundred", 1.5, 1.8), ("forty", 1.8, 2.1),
             ("three", 2.1, 2.4), ("days", 2.4, 2.9), ("here", 2.9, 3.3)]
    out = M._align_words_by_content(sw, heard)
    check(len(out) == len(sw), "split-token: one caption per script word")
    # "days" and "here" must land at their REAL times (2.4 and 2.9), not be
    # dragged early by the extra heard tokens.
    times = {w: st for (w, st, en) in out}
    check(abs(times["days"] - 2.4) < 0.01, f"'days' anchored to real time ({times.get('days')})")
    check(abs(times["here"] - 2.9) < 0.01, f"'here' anchored to real time ({times.get('here')})")

    # whisper DROPS a filler word -> that word's time is interpolated between
    # neighbours, and the sequence stays monotonic (no backwards captions).
    sw = "iron is really very hot inside".split()
    heard = [("iron", 0.0, 0.5), ("is", 0.5, 0.8), ("very", 1.4, 1.7),
             ("hot", 1.7, 2.1), ("inside", 2.1, 2.6)]   # "really" dropped
    out = M._align_words_by_content(sw, heard)
    starts = [st for _, st, _ in out]
    check(len(out) == len(sw), "dropped word: still one caption per script word")
    check(all(starts[i] <= starts[i + 1] + 1e-9 for i in range(len(starts) - 1)),
          "dropped word: caption starts stay monotonic")

    # degenerate inputs never crash
    check(M._align_words_by_content([], []) == [], "empty inputs -> []")
    check(M._align_words_by_content("a b".split(), []) == [], "no heard words -> []")


# --------------------------------------------------------------------------
# 3. _diversify_scene_queries: footage variety
# --------------------------------------------------------------------------
def test_diversify_queries():
    section("main._diversify_scene_queries: no scene lingers on a repeat clip")

    # run-53 case: scenes 2 and 6 share the identical query
    sc = FIX_ASTRO["scenes"]
    import copy
    sc = copy.deepcopy(sc)
    sc[1]["search_query"] = "planet space"
    sc[5]["search_query"] = "planet space"          # duplicate of scene 2
    M._diversify_scene_queries(sc)
    qs = [s["search_query"].lower() for s in sc]
    check(len(qs) == len(set(qs)), f"all queries distinct after diversify: {qs}")
    check(sc[5]["search_query"].lower() != "planet space", "duplicate query was rewritten")

    # already-distinct queries are left untouched
    sc2 = copy.deepcopy(FIX_BIO["scenes"])
    before = [s["search_query"] for s in sc2]
    M._diversify_scene_queries(sc2)
    after = [s["search_query"] for s in sc2]
    check(before == after, "distinct queries left unchanged")

    # empty query gets filled from the scene's own content
    sc3 = copy.deepcopy(FIX_GEO["scenes"])
    sc3[3]["search_query"] = ""
    M._diversify_scene_queries(sc3)
    check(sc3[3]["search_query"].strip() != "", "empty query gets populated")


# --------------------------------------------------------------------------
# 3b. _diversify_scene_motions: no video is zoom-only for its whole runtime
# --------------------------------------------------------------------------
def test_diversify_motions():
    section("main._diversify_scene_motions: a zoom-only video gets at least one pan")
    import copy

    # FIX_ASTRO's scenes() helper defaults every scene to zoom_in -- the exact
    # render-215-audit shape (a real manifest cycled only zoom_in/zoom_out for
    # all 7 scenes, never once picking 'pan')
    sc = copy.deepcopy(FIX_ASTRO["scenes"])
    check(all(s["motion"] == "zoom_in" for s in sc), "sanity: fixture is zoom-only")
    M._diversify_scene_motions(sc)
    check(any(s["motion"] == "pan" for s in sc), "a 'pan' was introduced somewhere")
    check(sc[0]["motion"] != "pan", "the hook (scene 1) is never touched")
    check(sc[-1]["motion"] != "pan", "the payoff (last scene) is never touched")

    # a script that already varies motion is left untouched
    sc2 = copy.deepcopy(FIX_ASTRO["scenes"])
    sc2[3]["motion"] = "pan"
    before = [s["motion"] for s in sc2]
    M._diversify_scene_motions(sc2)
    after = [s["motion"] for s in sc2]
    check(before == after, "a video that already uses 'pan' is left unchanged")

    # short videos (<5 scenes) are left alone -- not enough runtime for a
    # forced pan to read as anything but arbitrary
    sc3 = copy.deepcopy(FIX_ASTRO["scenes"])[:4]
    before3 = [s["motion"] for s in sc3]
    M._diversify_scene_motions(sc3)
    check([s["motion"] for s in sc3] == before3, "under-5-scene videos are untouched")


def test_footage_intent_anchors_on_subject():
    section("main._footage_intent: footage anchors on the literal subject, not the metaphor")
    # the run-66 hook: metaphorical voiceover, concrete forest search_query. The
    # footage intent must LEAD with the subject so the judge/requery stay on forest.
    sc = {"search_query": "forest sunlight trees",
          "voiceover": "Your walk through the woods is actually a trip through a city."}
    intent = M._footage_intent(sc)
    check(intent.startswith("forest sunlight trees"), f"intent leads with the subject ({intent!r})")
    check("city" in intent, "voiceover nuance still present for the judge")
    # degenerate inputs never crash
    check(M._footage_intent({"search_query": "coral reef", "voiceover": ""}) == "coral reef",
          "subject-only intent when no voiceover")
    check(M._footage_intent({"search_query": "", "voiceover": "just this"}) == "just this",
          "voiceover-only intent when no subject")


def test_local_footage_relevance():
    section("main._best_keyword_match: zero-LLM footage relevance short-circuit")
    # a specific query returning an on-subject clip is accepted without the LLM
    cands = [{"desc": "dubai skyline city night", "id": 1},
             {"desc": "ocean waves drone aerial", "id": 2}]
    check(M._best_keyword_match("ocean surface waves", cands) == 1,
          "clear keyword match accepted without LLM (picks the ocean clip)")
    # an off-topic pool (the metaphor-bug case) shares no words -> None -> LLM judge
    cands2 = [{"desc": "dubai skyline city night", "id": 1},
              {"desc": "busy highway traffic", "id": 2}]
    check(M._best_keyword_match("forest sunlight trees", cands2) is None,
          "off-topic candidates fall through to the LLM judge (metaphor bug stays caught)")
    # too few content words to decide locally -> None
    check(M._best_keyword_match("the it a", cands) is None, "too-short query defers to LLM")
    check(M._relevance_words("The Ocean's Waves") == {"ocean", "waves"}, "content words extracted")

    section("main._subject_word / SUBJECT-REQUIRED footage matching (render-182 octopus/turtle bug)")
    # render 182 shipped a SEA TURTLE as an octopus video's hook clip: the old
    # keyword check accepted it because it shared "swimming"+"ocean" (frac 0.67,
    # shared 2) with query "octopus swimming ocean" -- the subject noun itself
    # was never required to appear. Same render also cut in an orange being
    # sliced ("octopus close up" shared only "close") and a lipstick tube
    # ("octopus blood vessels" shared only "blood").
    check(M._subject_word("octopus swimming ocean") == "octopus", "subject = first content word")
    check(M._subject_word("tree communication") == "tree", "subject word on a 2-word query")
    check(M._subject_word("the of a") == "", "no content words -> empty subject")
    turtle_cands = [{"desc": "sea turtle swimming in green ocean water", "id": 1},
                    {"desc": "octopus swimming through open ocean", "id": 2}]
    check(M._best_keyword_match("octopus swimming ocean", turtle_cands) == 1,
          "turtle sharing 'swimming'+'ocean' is REJECTED; the real octopus clip wins")
    orange_only = [{"desc": "close up of hand slicing a fresh orange", "id": 1}]
    check(M._best_keyword_match("octopus close up", orange_only) is None,
          "orange clip sharing only 'close' does not win -- falls to the LLM judge, not shipped blind")
    lipstick_only = [{"desc": "woman applying blood red lipstick tube closeup", "id": 1}]
    check(M._best_keyword_match("octopus blood vessels", lipstick_only) is None,
          "lipstick clip sharing only 'blood' does not win -- falls to the LLM judge, not shipped blind")


def test_final_qa():
    section("main._qa_frame_timestamps / _final_qa_check: post-render holistic QA")
    # pure math: n evenly-spaced timestamps, inset 3% from each end
    ts = M._qa_frame_timestamps(40.0, 8)
    check(len(ts) == 8, "8 requested -> 8 timestamps")
    check(ts[0] > 0 and ts[-1] < 40.0, "first/last timestamp inset from the hard edges (no fade black frames)")
    check(all(ts[i] < ts[i + 1] for i in range(len(ts) - 1)), "timestamps strictly increasing")
    check(abs((ts[-1] - ts[0]) - (ts[1] - ts[0]) * 7) < 1e-6, "evenly spaced")
    check(M._qa_frame_timestamps(40.0, 1) == [20.0], "n=1 -> the midpoint")
    check(M._qa_frame_timestamps(0, 8) == [], "zero duration -> no timestamps (fail-safe, no crash)")
    check(M._qa_frame_timestamps(40.0, 0) == [], "n=0 -> no timestamps")
    check(M._qa_frame_timestamps(-5, 8) == [], "negative duration -> no timestamps")

    # _final_qa_check must be a total no-op (report ran:false, no exception, no
    # network) when GEMINI_API_KEY isn't set -- same fail-safe contract as every
    # other best-effort AI feature in this file (fal video, AI image, vision judge)
    import tempfile, json as _json
    _out_bak = M.OUT
    _key_bak = os.environ.pop("GEMINI_API_KEY", None)
    try:
        M.OUT = tempfile.mkdtemp()
        rep = M._final_qa_check("/nonexistent/video.mp4", {"scenes": [{"voiceover": "x"}]})
        on_disk = _json.load(open(os.path.join(M.OUT, "qa_report.json")))
        check(rep == {"ran": False}, "no GEMINI_API_KEY -> _final_qa_check returns the no-op report")
        check(on_disk == {"ran": False}, "no GEMINI_API_KEY -> qa_report.json written as a clean no-op")
    finally:
        M.OUT = _out_bak
        if _key_bak is not None:
            os.environ["GEMINI_API_KEY"] = _key_bak

    # publish gate: a blatant mismatch OR missing artifact-level evidence aborts.
    # FINAL_QA=0 is the only explicit operator opt-out.
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": 1}) is True,
          "confident, blatantly low score (1/10) -> abort")
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": M.FINAL_QA_ABORT_FLOOR - 1}) is True,
          "score just under the floor -> abort")
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": M.FINAL_QA_ABORT_FLOOR}) is False,
          "score AT the floor -> does not abort (only strictly below)")
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": 8}) is False,
          "healthy score -> no abort")
    _fq = M.FINAL_QA
    try:
        M.FINAL_QA = False
        check(M._qa_should_abort({"ran": False}) is False,
              "explicit FINAL_QA=0 operator opt-out -> unavailable judge does not abort")
    finally:
        M.FINAL_QA = _fq
    check(M._qa_should_abort({"ran": False, "footage_matches_narration": 0}) is True,
          "judge did not run (ran:false, e.g. quota/key outage) -> fail CLOSED, aborts")
    # pinned regression: two REAL renders shipped uncaught at exactly
    # footage_match=5/10 with a named defect each time (the render-209 "night
    # sky/night traffic... off-topic for human ancestry" case, and "The Real
    # Life Zombie Fungus" showing generic mushrooms instead of cordyceps-on-
    # an-ant) -- the floor must be high enough that 5 itself aborts, not just
    # scores below it (the exact off-by-one this session shipped once already).
    check(M.FINAL_QA_ABORT_FLOOR >= 6, "the floor is high enough that a 5/10 score actually aborts")
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": 5}) is True,
          "a real-world bad score (5/10) aborts, not just scores strictly below it")
    check(M._qa_should_abort({"ran": True, "error": "no JSON in reply"}) is True,
          "ran but no numeric footage score parsed -> fail CLOSED")
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": "n/a"}) is True,
          "non-numeric footage score -> fail CLOSED")

    # 2026-08-03: narration_flow -- the judge now LISTENS to the actual voice
    # audio, not just text, so a script that reads fine on paper but sounds
    # clumsy/jumbled out loud can be caught automatically, the same class of
    # defect the user has repeatedly caught by ear (mechanical validate()
    # checks only ever guard the specific phrasing shape they were written
    # for; this is a holistic backstop, not another narrow pattern match).
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": 9,
                              "narration_flow": 2}) is True,
          "great footage but bad-SOUNDING narration still aborts")
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": 9,
                              "narration_flow": M.FINAL_QA_FLOW_FLOOR - 1}) is True,
          "narration_flow just under its own floor -> abort")
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": 9,
                              "narration_flow": M.FINAL_QA_FLOW_FLOOR}) is False,
          "narration_flow AT the floor -> does not abort (only strictly below)")
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": 9,
                              "narration_flow": 8}) is False,
          "good footage AND good narration flow -> no abort")
    check(M._qa_should_abort({"ran": True, "footage_matches_narration": 9}) is False,
          "no audio judged this run (narration_flow absent) -> only footage gates, fails open on flow")


def test_persist_qa_to_memory():
    section("main._persist_qa_to_memory: final-QA verdict written back into memory_<page>.json")
    # Previously the final-QA verdict (footage_matches_narration, narration_flow,
    # etc.) only ever reached the ephemeral out/qa_report.json release asset --
    # generate.py's memory_<page>.json history (which DOES keep the script-level
    # `quality` rubric per video) never saw it, so a repeatedly-weak fact/domain
    # left no trace for future runs to learn from.
    import tempfile, json as _json
    _mem_bak = M.MEMORY_PATH
    tmpdir = tempfile.mkdtemp()
    M.MEMORY_PATH = os.path.join(tmpdir, "memory_test.json")
    try:
        history = [
            {"video_id": "science_2026-01-01_older-video", "title": "Older Video"},
            {"video_id": "science_2026-01-02_target-video", "title": "Target Video", "quality": {"overall": 7.4}},
        ]
        with open(M.MEMORY_PATH, "w") as f:
            _json.dump({"history": history}, f)

        qa = {"ran": True, "footage_matches_narration": 4, "visual_variety": 7,
              "caption_legible": 7, "narration_flow": 7, "audio_judged": True,
              "biggest_issue": "Final frame shows an unrelated aerial shot."}
        M._persist_qa_to_memory("science_2026-01-02_target-video", qa)
        saved = _json.load(open(M.MEMORY_PATH))["history"]
        target = next(h for h in saved if h["video_id"] == "science_2026-01-02_target-video")
        check("final_qa" in target, "matching history entry gains a final_qa sub-dict")
        check(target["final_qa"]["footage_matches_narration"] == 4,
              "footage_matches_narration carried through verbatim")
        check(target["final_qa"]["aborted"] is True,
              "a score that would abort the run is flagged aborted:true in memory too")
        check(target["quality"]["overall"] == 7.4,
              "the pre-existing script-level quality rubric is untouched, not overwritten")
        older = next(h for h in saved if h["video_id"] == "science_2026-01-01_older-video")
        check("final_qa" not in older, "only the matching video_id's entry is touched")

        # a healthy score is persisted too (not just abort cases), with aborted:false
        M._persist_qa_to_memory("science_2026-01-01_older-video",
                                 {"ran": True, "footage_matches_narration": 9})
        saved2 = _json.load(open(M.MEMORY_PATH))["history"]
        older2 = next(h for h in saved2 if h["video_id"] == "science_2026-01-01_older-video")
        check(older2["final_qa"]["aborted"] is False, "healthy score persists with aborted:false")

        # no-op cases must never raise or corrupt the file
        before = _json.load(open(M.MEMORY_PATH))
        M._persist_qa_to_memory("", qa)
        M._persist_qa_to_memory("science_2026-01-02_target-video", {"ran": False})
        M._persist_qa_to_memory("no_such_video_id", qa)
        after = _json.load(open(M.MEMORY_PATH))
        check(before == after, "empty video_id / ran:false / unmatched video_id are silent no-ops")

        # missing memory file entirely -> must not raise
        M.MEMORY_PATH = os.path.join(tmpdir, "does_not_exist.json")
        M._persist_qa_to_memory("science_2026-01-02_target-video", qa)
        check(not os.path.exists(M.MEMORY_PATH), "missing memory file -> silent no-op, never created from scratch")
    finally:
        M.MEMORY_PATH = _mem_bak


def test_vibe_and_hybrid_footage_mode():
    section("generate.py: _normalize_vibe / _assign_footage_mode (mood-matched pacing + hero AI shots)")
    m = {"vibe": "chaotic"}
    check(G._normalize_vibe(m)["vibe"] == "chaotic", "valid vibe passes through unchanged")
    m = {"vibe": "CHAOTIC"}
    check(G._normalize_vibe(m)["vibe"] == "chaotic", "vibe case-normalized")
    m = {"vibe": "  peaceful  "}
    check(G._normalize_vibe(m)["vibe"] == "peaceful", "vibe whitespace-stripped")
    m = {"vibe": "spooky-fun-times"}
    check(G._normalize_vibe(m)["vibe"] == "awe", "invented/invalid vibe -> safe 'awe' default, not rejected")
    m = {}
    check(G._normalize_vibe(m)["vibe"] == "awe", "missing vibe -> safe 'awe' default")
    check(set(G.VIBES) == {"chaotic", "peaceful", "eerie", "awe", "visceral", "tense"},
          "VIBES vocabulary is exactly the 6 documented options")

    scenes = [{"id": i, "search_query": f"query {i}"} for i in range(1, 7)]
    G._assign_footage_mode(scenes)
    check(scenes[0]["footage_mode"] == "ai", "hook (scene 1) tagged for AI generation")
    check(scenes[-1]["footage_mode"] == "ai", "payoff (last scene) tagged for AI generation")
    check(all(s["footage_mode"] == "real" for s in scenes[1:-1]),
          "every middle scene stays 'real' (stock) -- matches FAL_MAX_CLIPS default of 2/video")
    check(sum(1 for s in scenes if s["footage_mode"] == "ai") == 2,
          "exactly 2 scenes tagged ai regardless of video length")

    one = [{"id": 1, "search_query": "q"}]
    G._assign_footage_mode(one)
    check(one[0]["footage_mode"] == "ai", "single-scene edge case tags the only scene")
    check(G._assign_footage_mode([]) == [], "empty scene list -> no crash, returns empty")


def test_keywords_from_text():
    section("main._keywords_from_text: salient nouns, stopwords dropped")
    kw = M._keywords_from_text("The churning liquid outer core generates a magnetic field")
    toks = kw.split()
    check("the" not in toks and "a" not in toks, f"stopwords excluded: {kw!r}")
    check(all(len(t) > 3 for t in toks), f"only salient (>3 char) words: {kw!r}")
    check(len(toks) <= 3, f"caps at k=3 words: {kw!r}")


# --------------------------------------------------------------------------
# 4. timing helpers + build_ass fallback: captions monotonic across a video
# --------------------------------------------------------------------------
def test_prefix_starts_and_chars():
    section("main._prefix_starts / _chars_to_words: timing math")
    check(M._prefix_starts([2.0, 3.0, 1.5]) == [0.0, 2.0, 5.0], "prefix starts cumulative")
    check(M._prefix_starts([]) == [], "prefix starts empty")
    chars = list("hi  yo")
    starts = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    ends = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    words = M._chars_to_words(chars, starts, ends)
    check([w[0] for w in words] == ["hi", "yo"], f"chars grouped into words: {words}")
    check(words[0][1] == 0.0 and words[1][1] == 0.4, "word start times correct")


def test_build_ass_fallback_monotonic():
    section("main.build_ass (fallback): captions monotonic + inside spans across a whole video")
    sc = FIX_CHEM["scenes"]
    seg_durs = [3.0] * len(sc)
    segments = [(f"/tmp/seg{i}.mp3", d) for i, d in enumerate(seg_durs)]
    actual_durs = [3.05, 2.95, 3.0, 3.1, 2.9, 3.0, 3.0, 3.0][:len(sc)]
    old_wt = M.WORD_TIMINGS
    M.WORD_TIMINGS = []                      # force the estimate/fallback path
    try:
        with tempfile.NamedTemporaryFile("w+", suffix=".ass", delete=False) as f:
            path = f.name
        M.build_ass(sc, segments, actual_durs, path)
        body = open(path).read()
    finally:
        M.WORD_TIMINGS = old_wt
        try: os.unlink(path)
        except OSError: pass
    # parse Dialogue start times (ASS h:mm:ss.cs)
    def _to_s(ts):
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    starts = []
    for line in body.splitlines():
        if line.startswith("Dialogue:"):
            parts = line.split(",")
            starts.append(_to_s(parts[1]))
    check(len(starts) > 0, f"produced caption events ({len(starts)})")
    check(all(starts[i] <= starts[i + 1] + 1e-6 for i in range(len(starts) - 1)),
          "all caption starts monotonic across the video")
    total = sum(actual_durs)
    check(all(0.0 <= s <= total + 0.5 for s in starts),
          "all caption starts within the assembled timeline")


# --------------------------------------------------------------------------
# 5. generate.py misc pure helpers
# --------------------------------------------------------------------------
def test_funnel_affiliate_coverage():
    section("funnel.affiliate_for: every real bank-domain family has a topic-matched affiliate, not the generic fallback")
    # a real audit found only 8/20 domain families mapped -- everything else
    # silently fell to AFFILIATE_DEFAULT in the newsletter's actual monetization
    # pitch. Assert against the REAL bank data so a newly-added domain that
    # forgets a mapping fails this test instead of shipping silently generic.
    bank = _json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "topic_bank.json")))
    families = {G._domain_family(f.get("domain")) for f in bank["facts"]}
    uncovered = [fam for fam in sorted(families) if fam not in F.AFFILIATE_BY_DOMAIN]
    check(not uncovered, f"every domain family in topic_bank.json has an explicit affiliate mapping (uncovered: {uncovered})")
    check(F.affiliate_for("fungi")["search"] != F.AFFILIATE_DEFAULT["search"],
          "a newly-covered domain (fungi) resolves to its own book, not the generic default")
    check(F.affiliate_for("totally_unknown_domain_xyz") == {**F.AFFILIATE_DEFAULT, "domain": "totally_unknown_domain_xyz"},
          "a genuinely unmapped domain still falls open to the generic default (never crashes)")


def test_square_crop_top():
    section("repackage._square_crop_top: the square/X/IG-feed crop must never cut the caption band out of frame")
    import profiles as P
    _bak = dict(R.PROFILE)
    try:
        # science (the currently-shipping profile): default 520 must be UNCHANGED
        R.PROFILE.clear(); R.PROFILE.update(P.PROFILES["science"])
        top = R._square_crop_top()
        check(top == 520, f"science profile keeps the exact reviewed default (got {top}, not 520)")
        band_top, band_bottom = R._caption_band()
        check(band_top >= top and band_bottom <= top + 1080, "science's caption band fits inside its crop")

        # every OTHER defined profile: the band must fit inside whatever crop is chosen,
        # even the ones the flat 520 default does NOT cover (history_pov, dark_mystery)
        for name, prof in P.PROFILES.items():
            R.PROFILE.clear(); R.PROFILE.update(prof)
            top = R._square_crop_top()
            band_top, band_bottom = R._caption_band()
            check(0 <= top <= R.H - 1080, f"{name}: crop top {top} stays within the frame bounds")
            check(band_top >= top and band_bottom <= top + 1080,
                  f"{name}: caption band [{band_top:.0f},{band_bottom:.0f}] fits inside crop "
                  f"[{top},{top + 1080}] (real bug: history_pov/dark_mystery didn't fit the old flat 520)")
    finally:
        R.PROFILE.clear(); R.PROFILE.update(_bak)


def test_domain_family():
    section("generate._domain_family: earth-science domains share one family")
    check(G._domain_family("geology") == G._domain_family("earth") == G._domain_family("weather"),
          "geology/earth/weather map to the same family (no back-to-back deep-earth videos)")
    check(G._domain_family("space") != G._domain_family("earth"), "space stays distinct from earth")
    check(G._domain_family("animals") == "animals", "unlisted domain is its own family")
    # a real bank-domain audit (2026-08-03) found the same split-domain issue in
    # several other pairs that were never folded into a family
    check(G._domain_family("atmosphere") == G._domain_family("weather"),
          "atmosphere joins the earth/weather family")
    check(G._domain_family("ocean") == G._domain_family("oceanography") == G._domain_family("marine"),
          "ocean/oceanography/marine map to the same family")
    check(G._domain_family("fungi") == G._domain_family("mycology"),
          "fungi/mycology map to the same family")
    check(G._domain_family("plants") == G._domain_family("botany"),
          "plants/botany map to the same family")
    check(G._domain_family("space") == G._domain_family("astronomy"),
          "space/astronomy map to the same family")
    check(G._domain_family("ocean") != G._domain_family("earth"),
          "the new ocean family stays distinct from the earth family")


def test_series_and_callback():
    section("generate._pick_series / _find_callback: binge architecture (PLATFORM.md idea 2)")
    # no history at all -> never continues (nothing to continue), MAY start
    # fresh depending on the random draw -- pin random for a deterministic check
    G.random.seed(1)
    name, part = G._pick_series([], "body")
    check(part in (None, 1), f"first-ever video either starts a series at part 1 or skips ({name!r}, {part})")

    # an in-progress, still-eligible series ALWAYS continues (never re-rolls
    # to start something new instead) -- this is the actual "binge" mechanic
    hist_mid_series = [{"domain": "body", "series": {"name": "Things Happening In Your Body Right Now", "part": 2}}]
    name2, part2 = G._pick_series(hist_mid_series, "senses")  # senses is in the SAME theme's domain set
    check((name2, part2) == ("Things Happening In Your Body Right Now", 3),
          f"a compatible in-progress series continues to the next part deterministically ({name2}, {part2})")

    # a domain that no longer fits the active series' theme does NOT force a
    # continuation -- falls through to the normal start-or-skip logic instead
    name3, part3 = G._pick_series(hist_mid_series, "space")
    check(name3 != "Things Happening In Your Body Right Now",
          f"an incompatible domain does not continue the wrong series ({name3})")

    # a series at the cap retires -- no more forced continuation even if the
    # domain would otherwise fit
    hist_capped = [{"domain": "body", "series": {"name": "Things Happening In Your Body Right Now",
                                                  "part": G.SERIES_MAX_PARTS}}]
    name4, part4 = G._pick_series(hist_capped, "body")
    check(name4 != "Things Happening In Your Body Right Now" or part4 != G.SERIES_MAX_PARTS + 1,
          f"a series AT its max part count does not force yet another continuation ({name4}, {part4})")

    # a domain matching no theme at all never starts or continues anything
    name5, part5 = G._pick_series([], "totally_unmapped_domain_xyz")
    check((name5, part5) == (None, None), "a domain with no matching theme never starts a series")

    # _find_callback: most recent same-domain title wins, exclude_ids honored
    hist_cb = [
        {"video_id": "a", "domain": "ocean", "title": "The Trench Nobody Has Touched"},
        {"video_id": "b", "domain": "space", "title": "A Day Longer Than a Year"},
        {"video_id": "c", "domain": "ocean", "title": "Bioluminescent Blooms"},
    ]
    check(G._find_callback(hist_cb, "ocean") == "Bioluminescent Blooms",
          "callback picks the MOST RECENT same-domain video")
    check(G._find_callback(hist_cb, "ocean", exclude_ids={"c"}) == "The Trench Nobody Has Touched",
          "excluded video_id is skipped, falls back to the next same-domain match")
    check(G._find_callback(hist_cb, "geology") is None, "no matching domain -> no callback")
    check(G._find_callback([], "ocean") is None, "empty history -> no callback, no crash")


def test_generate_helpers():
    section("generate.py pure helpers")
    check(re.match(r"^[a-z0-9-]+$", G._slugify("A Day Longer Than a Year!")) is not None,
          "slugify -> url-safe")
    check(G._hits_banned_concept("a starling murmuration", "The Flock") is True,
          "banned concept (murmuration) detected")
    check(G._hits_banned_concept("gallium melts in your hand", "Liquid Metal") is False,
          "unrelated topic not falsely banned")
    hist = [{"metaphor": "hot water freezes faster than cold"}]
    check(G._metaphor_too_similar("hot water can freeze before cold water", hist) is True,
          "near-duplicate metaphor flagged")
    check(G._metaphor_too_similar("a metal that melts in your hand", hist) is False,
          "distinct metaphor allowed")
    frames = dict(G.HOOK_FRAMES)
    dq = frames["DIRECT_QUESTION"]
    check("DO NOT put a question mark" in dq and "scene 2" in dq,
          "DIRECT_QUESTION legacy frame now creates a question-gap without violating the no-question hook gate")
    p = G.build_prompt("REFRAME", "test", "none")
    check("CREATE A QUESTION GAP WITHOUT OPENING ON A QUESTION" in p,
          "main writer prompt agrees with validate(): first beat is a statement, literal question comes later")
    check("the strongest hooks are a concrete question" not in p,
          "old contradictory question-hook instruction is gone")
    check("quietly eerie documentary narrator" not in G.PAGE_IDENTITY,
          "channel identity no longer hard-biases every topic toward eerie")
    check("Eerie is one valid mood, NOT the channel default" in G.PAGE_IDENTITY,
          "identity explicitly preserves emotional range instead of one monotone")


# --------------------------------------------------------------------------
# 6. fast-fail when all providers throttled (wall-clock budget work)
# --------------------------------------------------------------------------
def test_research_dossier_requires_grounding():
    section("generate.research_dossier: extra science fails CLOSED when grounding is unavailable")
    fact = {"id": "ground-test",
            "fact": "GPS satellites require relativistic clock corrections.",
            "angle": "relativity",
            "key_terms": ["GPS", "relativity"]}
    grounded_facts = [
        "Grounded fact one has a concrete mechanism and enough detail.",
        "Grounded fact two has a concrete mechanism and enough detail.",
        "Grounded fact three has a concrete mechanism and enough detail.",
        "Grounded fact four has a concrete mechanism and enough detail.",
        "Grounded fact five has a concrete mechanism and enough detail.",
    ]

    old_cache = G.DOSSIER_CACHE
    old_key = G.GEMINI_KEY
    old_models = G._GEMINI_MODELS_CACHE
    old_gem = G._call_gemini
    old_llm = G.call_groq
    old_env = os.environ.get("GROUND_DOSSIER")
    try:
        with tempfile.TemporaryDirectory() as td:
            G.DOSSIER_CACHE = os.path.join(td, "dossier.json")
            G.GEMINI_KEY = "fake-key"
            G._GEMINI_MODELS_CACHE = ["gemini-test"]
            os.environ["GROUND_DOSSIER"] = "1"
            ungrounded_calls = {"n": 0}

            def _ungrounded(_prompt):
                ungrounded_calls["n"] += 1
                return _json.dumps({"facts": grounded_facts})

            G.call_groq = _ungrounded
            G._call_gemini = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("grounding down"))
            got = G.research_dossier(fact)
            check(got == [], "grounding outage -> [] / base fact only")
            check(ungrounded_calls["n"] == 0,
                  "grounding outage NEVER silently falls back to ordinary model memory")

            # A successful grounded response is accepted and cached with explicit
            # provenance, then reusable at zero quota.
            G._call_gemini = lambda *a, **k: _json.dumps({"facts": grounded_facts})
            got2 = G.research_dossier(fact)
            check(got2 == grounded_facts, "grounded dossier accepted")
            cache = _json.load(open(G.DOSSIER_CACHE))
            key = G._dossier_key(fact)
            check(isinstance(cache.get(key), dict) and cache[key].get("grounded") is True,
                  "new dossier cache records grounded provenance")

            G._call_gemini = lambda *a, **k: (_ for _ in ()).throw(AssertionError("cache hit must not call Gemini"))
            got3 = G.research_dossier(fact)
            check(got3 == grounded_facts, "grounded cache hit reuses facts with zero network calls")

            # Legacy bare-list cache has unknown provenance; production grounding
            # mode must not trust it.
            with open(G.DOSSIER_CACHE, "w") as fh:
                _json.dump({key: grounded_facts}, fh)
            G._call_gemini = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("grounding down"))
            got4 = G.research_dossier(fact)
            check(got4 == [], "legacy unknown-provenance dossier cache is ignored by default")

            # Explicit operator opt-out remains possible for experiments, but it
            # must be a conscious env choice, never an outage fallback. Clear the
            # cache first -- the legacy bare-list entry written just above would
            # otherwise be a legitimate ungrounded-mode cache HIT (by design, see
            # the "reuse an ungrounded cache entry" comment on ground_required
            # above) and this sub-test would never actually exercise the live
            # ungrounded call it's named for.
            with open(G.DOSSIER_CACHE, "w") as fh:
                _json.dump({}, fh)
            os.environ["GROUND_DOSSIER"] = "0"
            ungrounded_calls["n"] = 0
            got5 = G.research_dossier(fact)
            check(got5 == grounded_facts and ungrounded_calls["n"] == 1,
                  "GROUND_DOSSIER=0 explicitly enables ungrounded research")
    finally:
        G.DOSSIER_CACHE = old_cache
        G.GEMINI_KEY = old_key
        G._GEMINI_MODELS_CACHE = old_models
        G._call_gemini = old_gem
        G.call_groq = old_llm
        if old_env is None:
            os.environ.pop("GROUND_DOSSIER", None)
        else:
            os.environ["GROUND_DOSSIER"] = old_env


def test_fast_fail_when_throttled():
    section("generate.py: throttled run fails fast (wall-clock budget + circuit skip)")
    # GEN_WALL_BUDGET_S sane
    check(isinstance(G.GEN_WALL_BUDGET_S, int) and 60 <= G.GEN_WALL_BUDGET_S <= 3600,
          f"GEN_WALL_BUDGET_S sane (={G.GEN_WALL_BUDGET_S})")

    # circuit OPEN -> generate_candidate returns instantly, no provider calls
    calls = {"n": 0}
    orig_call = G.call_groq
    orig_circuit = G._CIRCUIT_OPEN
    def boom(_prompt):
        calls["n"] += 1
        raise RuntimeError("simulated exhaustion")
    G.call_groq = boom
    G._CIRCUIT_OPEN = True
    try:
        t0 = time.time()
        res = G.generate_candidate("EXPLAIN", "explain a thing", "none",
                                    {"id": "x", "queries": ["ocean"]}, history=[],
                                    dossier="(dossier)")
        dt = time.time() - t0
    finally:
        G.call_groq = orig_call
        G._CIRCUIT_OPEN = orig_circuit
    check(res is None, "circuit-open candidate is None (aborts)")
    check(dt < 2.0, f"circuit-open path near-instant ({dt:.2f}s, was ~80s of backoff)")
    check(calls["n"] == 0, f"no provider hammered when circuit open ({calls['n']} calls)")


def test_call_groq_empty_response_falls_through():
    section("generate.call_groq: an EMPTY provider response falls through, never gets cached (render-217)")
    # 2026-08-03: the actual render-217 root cause, found by reading a live log
    # where generation ground through 3 full attempts and aborted despite
    # Gemini being available and healthy. call_groq's internal _walk() used to
    # accept ANY non-exception response as success -- including an EMPTY body,
    # OpenRouter's own documented intermittent hiccup (see the caller's
    # empty-retry comment a few lines below in generate.py). Once that empty
    # response was accepted, _accept() cached it as _WORKING_MODEL, and every
    # later call_groq() in the same render re-tried THAT SAME broken provider
    # first -- Gemini, sitting right behind it in the chain, was never reached
    # even once, for the rest of the entire render.
    _or_key, _gem_key = G.OPENROUTER_KEY, G.GEMINI_KEY
    _or_models, _gem_cache = G.OPENROUTER_MODELS, G._GEMINI_MODELS_CACHE
    _working, _consec, _circuit = G._WORKING_MODEL, G._CONSEC_EXHAUSTIONS, G._CIRCUIT_OPEN
    _orig_or, _orig_gem = G._call_openrouter, G._call_gemini
    try:
        G.OPENROUTER_KEY = "fake-key"
        G.GEMINI_KEY = "fake-key"
        G.OPENROUTER_MODELS = ["meta-llama/llama-3.3-70b-instruct"]
        G._GEMINI_MODELS_CACHE = ["gemini-flash-latest"]
        G._WORKING_MODEL = None
        G._CONSEC_EXHAUSTIONS = 0
        G._CIRCUIT_OPEN = False
        good = _json.dumps({"ok": True})
        or_calls = {"n": 0}
        def _empty_openrouter(model, prompt):
            or_calls["n"] += 1
            return ""   # the exact flakiness: HTTP 200, empty body, no exception
        G._call_openrouter = _empty_openrouter
        G._call_gemini = lambda model, prompt: good

        out = G.call_groq("prompt")
        check(out == good, f"an empty openrouter response is NOT accepted as-is; falls through to gemini ({out!r})")
        check(G._WORKING_MODEL == ("gemini", "gemini-flash-latest"),
              f"the empty-returning provider is never cached as _WORKING_MODEL ({G._WORKING_MODEL})")

        # a SECOND call in the same process (simulating the next generation
        # attempt/scene/critique call within one render) must go straight to
        # the now-cached WORKING gemini model, not get stuck retrying openrouter.
        or_calls["n"] = 0
        out2 = G.call_groq("prompt 2")
        check(out2 == good, "a second call in the same process also succeeds via the cached gemini model")
        check(or_calls["n"] == 0,
              f"the known-empty openrouter provider is not even retried once the working model is gemini ({or_calls['n']} calls)")
    finally:
        G.OPENROUTER_KEY, G.GEMINI_KEY = _or_key, _gem_key
        G.OPENROUTER_MODELS, G._GEMINI_MODELS_CACHE = _or_models, _gem_cache
        G._WORKING_MODEL, G._CONSEC_EXHAUSTIONS, G._CIRCUIT_OPEN = _working, _consec, _circuit
        G._call_openrouter, G._call_gemini = _orig_or, _orig_gem


def test_near_miss_repair_revalidates():
    section("generate.py: near-miss repair re-validates before shipping (render-186 bug)")
    # Render 186 shipped "the antisolar point" verbatim even though validate()
    # correctly rejected it as banned jargon on EVERY attempt -- because the
    # near-miss repair path only fixes PACING (scene/word count), never re-runs
    # validate() against the ORIGINAL rejection reason before shipping. Every
    # attempt here returns a manifest that's structurally fine (so it's kept as
    # a near_miss backup) but fails validate() on the jargon check, and stays
    # broken after repair since repair never touches voiceover wording.
    import copy as _copy, json as _json
    bad = _copy.deepcopy(FIX_PHYS)
    bad["scenes"][2]["voiceover"] = ("The phenomenon forms at 42 degrees from the antisolar "
                                      "point, directly opposite the sun.")
    bad["script"] = " ".join(s["voiceover"] for s in bad["scenes"])
    raw = _json.dumps(bad)
    orig_call, orig_circuit = G.call_groq, G._CIRCUIT_OPEN
    G.call_groq = lambda _p: raw
    G._CIRCUIT_OPEN = False
    try:
        res = G.generate_candidate(
            "EXPLAIN", "explain a thing", "none",
            {"id": "x", "fact": "Rainbows form opposite the sun.", "angle": "hidden circle",
             "key_terms": ["rainbow"], "whatif": "", "wow": "", "queries": ["ocean"]},
            history=[], dossier="(dossier)")
    finally:
        G.call_groq = orig_call
        G._CIRCUIT_OPEN = orig_circuit
    check(res is None, "near-miss still containing banned jargon after pacing-only repair -> "
                        "abandoned (consistency over cadence), not shipped with the jargon intact")


def test_near_miss_injects_missing_curiosity_gap():
    section("generate.py: near-miss mechanically injects the missing whatif question (renders 196/197)")
    # FIX_ASTRO has zero '?' anywhere (hook or scenes) -- every attempt hits
    # the SAME validate() failure ("whatif curiosity gap never opened"), so
    # it becomes the near-miss. The fix text is the fact's own "whatif" field
    # (no LLM call needed): near-miss repair should inject it into scene 2
    # and SHIP the result, rather than abandoning an otherwise-clean script.
    import copy as _copy, json as _json
    bad = _copy.deepcopy(FIX_ASTRO)
    check("?" not in (bad["hook"] + " ".join(s["voiceover"] for s in bad["scenes"])),
          "sanity: the fixture has no question mark anywhere")
    raw = _json.dumps(bad)
    orig_call, orig_circuit = G.call_groq, G._CIRCUIT_OPEN
    G.call_groq = lambda _p: raw
    G._CIRCUIT_OPEN = False
    fact = {"id": "x", "fact": "Venus's day is longer than its year.", "angle": "backwards planet",
            "key_terms": ["243 Earth days", "225 Earth days"],
            "whatif": "Could a planet's day really last longer than its whole year",
            "wow": "", "queries": ["venus planet"]}
    try:
        res = G.generate_candidate("EXPLAIN", "explain a thing", "none", fact,
                                    history=[], dossier="(dossier)")
    finally:
        G.call_groq = orig_call
        G._CIRCUIT_OPEN = orig_circuit
    check(res is not None, "the whatif-only violation is mechanically repaired and SHIPPED, "
                            "not abandoned")
    if res is not None:
        early = res["hook"] + " " + " ".join(s["voiceover"] for s in res["scenes"][:4])
        check("?" in early, "the repaired script now opens a curiosity gap in the first few lines")
        check("last longer than its whole year" in res["scenes"][1]["voiceover"].lower(),
              "the fact's own whatif TEXT was injected verbatim into scene 2")


def test_caption_function_word_grouping():
    section("main._group_function_words: no lone 'OF'/'THE' frame, and NO word dropped")
    # "capable of stopping the plane" -> 'of' rides with 'stopping', 'the' with 'plane'
    wt = [("capable", 0.0, 0.4), ("of", 0.4, 0.5), ("stopping", 0.5, 1.0),
          ("the", 1.0, 1.1), ("plane", 1.1, 1.6)]
    grouped = M._group_function_words(wt)
    texts = [g[0] for g in grouped]
    # every original word still present somewhere (word-for-word coverage kept)
    joined = " ".join(texts).split()
    for w in ("capable", "of", "stopping", "the", "plane"):
        check(w in joined, f"'{w}' still shown after grouping ({texts})")
    check(not any(t.lower() in M._CAPTION_FUNCTION_WORDS for t in texts),
          f"no lone function-word frame remains ({texts})")
    # merged frames span both words' windows and stay monotonic
    check(all(a[2] <= b[2] for a, b in zip(grouped, grouped[1:])),
          "grouped end-times stay monotonic")
    # a merge that would overflow the no-wrap width is left alone (both kept apart)
    wt2 = [("of", 0.0, 0.2), ("extraordinarily", 0.2, 1.0)]
    g2 = M._group_function_words(wt2, max_chars=10)
    check(len(g2) == 2, "over-wide merge skipped (kept as separate frames, still no drop)")
    # a single word is returned unchanged
    check(M._group_function_words([("hello", 0.0, 0.5)]) == [("hello", 0.0, 0.5)],
          "single word unchanged")


def test_script_buffer_queue():
    section("generate.py buffer: enqueue/dequeue is FIFO, empty=3, malformed-safe")
    import json as _json
    q_prev, dest = G.QUEUE_DIR, tempfile.mktemp(suffix=".json")
    G.QUEUE_DIR = tempfile.mkdtemp()
    try:
        check(G.dequeue_to(dest) == 3, "empty buffer -> exit 3 (fall back to live gen)")
        G.enqueue_manifest({"title": "First", "scenes": [{"id": 1}]}, "science_2026-07-17_first")
        time.sleep(0.01)
        G.enqueue_manifest({"title": "Second", "scenes": [{"id": 1}]}, "science_2026-07-17_second")
        check(len(G._queue_files()) == 2, "two manifests buffered")
        check(G.dequeue_to(dest) == 0 and _json.load(open(dest))["title"] == "First",
              "dequeue pops oldest first (FIFO)")
        check(G.dequeue_to(dest) == 0 and _json.load(open(dest))["title"] == "Second",
              "second dequeue pops the next one")
        check(G.dequeue_to(dest) == 3, "drained buffer -> exit 3 again")
        # a corrupt queued file must be skipped, not wedge the buffer
        open(os.path.join(G.QUEUE_DIR, "0000000000001_bad.json"), "w").write("{ not json")
        open(os.path.join(G.QUEUE_DIR, "0000000000002_ok.json"), "w").write(
            _json.dumps({"title": "Good", "scenes": [{"id": 1}]}))
        check(G.dequeue_to(dest) == 0 and _json.load(open(dest))["title"] == "Good",
              "malformed queued file skipped; next valid one served")
        check(len(G._queue_files()) == 0, "malformed file is also removed (buffer not wedged)")
    finally:
        import shutil as _sh
        _sh.rmtree(G.QUEUE_DIR, ignore_errors=True)
        try:
            os.remove(dest)
        except OSError:
            pass
        G.QUEUE_DIR = q_prev


def test_xfade_offsets_monotonic():
    section("main._xfade_offsets: chained-dissolve offsets are positive + increasing")
    durs = [3.0, 2.0, 4.0, 2.5]
    xf = 0.2
    offs = M._xfade_offsets(durs, xf)
    check(len(offs) == len(durs) - 1, f"one offset per cut ({offs})")
    check(all(o > 0 for o in offs), f"all offsets positive ({offs})")
    check(all(b > a for a, b in zip(offs, offs[1:])), f"offsets strictly increasing ({offs})")
    # first cut blends starting at (first clip - xf)
    check(abs(offs[0] - (durs[0] - xf)) < 1e-6, f"first offset = dur0 - xf ({offs[0]})")
    # fewer than two clips -> nothing to blend
    check(M._xfade_offsets([4.0], xf) == [], "single clip -> no offsets")
    check(M._xfade_offsets([], xf) == [], "empty -> no offsets")


def test_critique_script_merges_gain_and_score():
    section("generate.critique_script: one call returns BOTH redundancy + rubric score")
    import json as _json
    m = {"title": "T", "hook": "h",
         "scenes": [{"id": i, "voiceover": f"scene {i} says a distinct thing"} for i in range(1, 8)]}
    fact = {"fact": "X is genuinely true", "whatif": "what if X"}
    _orig = G.call_groq
    try:
        # both halves present: redundant ids (incl. a numeric string) + full scores
        G.call_groq = lambda p: _json.dumps({"no_new_info_scene_ids": [3, "5"],
                                             "hook": 7, "surprise": 8, "escalation": 7,
                                             "payoff": 9, "rewatch": 6, "clarity": 9})
        err, sc = G.critique_script(m, fact, "COMMENT")
        check(err is not None and "3" in err and "5" in err, f"redundant ids surfaced ({err})")
        check(sc is not None and sc["overall"] == round((7 + 8 + 7 + 9 + 6 + 9) / 6, 2),
              f"rubric overall computed from the same call ({sc and sc.get('overall')})")

        # clean script: no redundancy, still fully scored
        G.call_groq = lambda p: _json.dumps({"no_new_info_scene_ids": [],
                                             "hook": 8, "surprise": 8, "escalation": 8,
                                             "payoff": 8, "rewatch": 8, "clarity": 8})
        err, sc = G.critique_script(m, fact, "COMMENT")
        check(err is None, "clean script -> no redundancy error")
        check(sc is not None and sc["overall"] == 8.0, "clean script still scored 8.0")

        # scores as strings + a missing minority still coerce to a usable score
        G.call_groq = lambda p: _json.dumps({"no_new_info_scene_ids": [],
                                             "hook": "7", "surprise": "8",
                                             "escalation": "7", "payoff": "9"})
        err, sc = G.critique_script(m, fact, "COMMENT")
        check(sc is not None and "overall" in sc, "string+partial scores coerced, not failed open")

        # unparseable model output fails OPEN on both halves (never bricks a run)
        G.call_groq = lambda p: "not json"
        err, sc = G.critique_script(m, fact, "COMMENT")
        check(err is None and sc is None, "bad JSON -> (None, None), fails open")

        # fewer than 2 scenes short-circuits without a call
        _boom = lambda p: (_ for _ in ()).throw(AssertionError("must not call LLM"))
        G.call_groq = _boom
        err, sc = G.critique_script({"scenes": [{"id": 1, "voiceover": "x"}]}, fact)
        check(err is None and sc is None, "<2 scenes short-circuits with no LLM call")
    finally:
        G.call_groq = _orig


def test_shadow_lift_filter():
    section("main._shadow_lift_filter: dim clips lifted, bright/unknown untouched")
    # already-bright or unknown -> no lift, no filter appended
    check(M._shadow_lift_filter(None) == "", "unknown luma -> no lift")
    check(M._shadow_lift_filter(80.0) == "", "bright clip -> no lift")
    check(M._shadow_lift_filter(58.0) == "", "at target -> no lift")
    # a dim clip gets an eq snippet that raises gamma above 1 (opens shadows)
    dim = M._shadow_lift_filter(20.0)
    # CRITICAL comma placement: inserted after _motion_filter (trailing comma)
    # and before the grade (no leading comma). A leading comma would double up
    # (",,") and make ffmpeg fail the scene, so assert exactly the right shape.
    check(not dim.startswith(","), f"no leading comma (would double up) ({dim})")
    check(dim.endswith(","), f"has trailing comma to join the grade ({dim})")
    check("eq=gamma=" in dim, f"dim clip -> eq gamma snippet ({dim})")
    import re as _re
    gamma = float(_re.search(r"gamma=([0-9.]+)", dim).group(1))
    bright = float(_re.search(r"brightness=([0-9.\-]+)", dim).group(1))
    check(1.0 < gamma <= 1.55, f"gamma opens shadows but is capped ({gamma})")
    check(0.0 < bright <= 0.10, f"brightness nudge is capped ({bright})")
    # darker clip -> stronger (or equal, at the cap) lift than a less-dark clip
    g_dark = float(_re.search(r"gamma=([0-9.]+)", M._shadow_lift_filter(10.0)).group(1))
    g_mild = float(_re.search(r"gamma=([0-9.]+)", M._shadow_lift_filter(45.0)).group(1))
    check(g_dark >= g_mild, f"darker clip lifted at least as hard ({g_dark} >= {g_mild})")


def test_vision_call_budget():
    section("main._gemini_vision_pick: paid-vision call budget caps spend")
    prev_key = os.environ.get("GEMINI_API_KEY")
    prev_calls = M._VISION_CALLS
    try:
        os.environ["GEMINI_API_KEY"] = "x"      # make the key check pass
        cands = [{"image": "http://x/1.jpg"}, {"image": "http://x/2.jpg"}]
        # at/over budget -> None, short-circuited BEFORE any network attempt
        M._VISION_CALLS = M.VISION_CALL_BUDGET
        check(M._gemini_vision_pick("intent", cands) is None, "over budget -> None (no paid call)")
        check(M._VISION_CALLS == M.VISION_CALL_BUDGET, "budget guard does not increment the counter")
        check(M.VISION_CALL_BUDGET > 0, f"a sane default budget is set ({M.VISION_CALL_BUDGET})")
    finally:
        M._VISION_CALLS = prev_calls
        if prev_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = prev_key


def test_fal_clip_verdict_rejects_garbled_text_independent_of_score():
    section("main._fal_clip_verdict: garbled-text rejection is INDEPENDENT of relevance score (render-2026-08-05)")
    # Real render: a fal hero shot for 'ice floating water' was accepted --
    # right subject, would have scored well on relevance alone -- but had
    # garbled pseudo-Cyrillic text baked into the frame, unrelated to the
    # subject-match check entirely. The two checks must be independent: a
    # perfect-subject clip with garbled text must still be rejected.
    accept, reason = M._fal_clip_verdict({"score": 9, "garbled_text": True})
    check(accept is False, "high relevance score (9/10) does NOT save a clip with garbled text")
    check("garbled" in reason.lower(), f"rejection reason names garbled text ({reason!r})")

    accept, reason = M._fal_clip_verdict({"score": 10, "garbled_text": True})
    check(accept is False, "even a perfect 10/10 relevance score is rejected if garbled_text is true")

    # a low score still rejects on its own, same as before this change
    accept, reason = M._fal_clip_verdict({"score": M.FAL_RELEVANCE_FLOOR - 1, "garbled_text": False})
    check(accept is False, "low relevance score alone still rejects (unchanged behavior)")
    check("garbled" not in reason.lower(), "low-score rejection reason does not mention garbled text")

    # the clean-pass case: good score, no garbled text
    accept, reason = M._fal_clip_verdict({"score": 9, "garbled_text": False})
    check(accept is True and reason == "", "good score + no garbled text -> accepted, empty reason")

    # missing keys must fail safe (never crash, never silently reject)
    accept, reason = M._fal_clip_verdict({})
    check(accept is True, "missing 'score' defaults to 10 (accept), missing 'garbled_text' defaults to False")
    accept, reason = M._fal_clip_verdict({"score": 9})
    check(accept is True, "garbled_text absent (not just false) -> treated as no garbled text")


def test_fal_clip_relevant():
    section("main._fal_clip_relevant: unverified synthetic clips fail CLOSED to real-media fallbacks")
    # Render 205 proved API success is not content success: fal returned a boat /
    # human silhouette for "naked mole rat". A later real render proved a second,
    # independent failure mode: garbled baked-in text. If the independent vision
    # safety check cannot run, the optional synthetic clip must NOT be trusted.
    # Rejecting the clip does not abort the video; build_scene falls through to
    # stock / archival / still / card.
    prev_key = os.environ.get("GEMINI_API_KEY")
    prev_vj = M.VISION_JUDGE
    prev_safety = M._FAL_SAFETY_UNAVAILABLE
    try:
        M._FAL_SAFETY_UNAVAILABLE = False
        os.environ.pop("GEMINI_API_KEY", None)
        M.VISION_JUDGE = True
        check(M._fal_clip_relevant({"search_query": "naked mole rat"}, "/nonexistent/clip.mp4") is False,
              "no GEMINI_API_KEY -> reject unverified fal clip")
        check(M._FAL_SAFETY_UNAVAILABLE is True,
              "missing safety judge opens the render-local fal safety circuit")

        M._FAL_SAFETY_UNAVAILABLE = False
        os.environ["GEMINI_API_KEY"] = "x"
        M.VISION_JUDGE = False
        check(M._fal_clip_relevant({"search_query": "naked mole rat"}, "/nonexistent/clip.mp4") is False,
              "VISION_JUDGE off -> reject unverified fal clip")

        # A broken/missing clip path means we could not inspect the generated
        # content. Reject that optional clip instead of silently accepting it.
        M._FAL_SAFETY_UNAVAILABLE = False
        M.VISION_JUDGE = True
        check(M._fal_clip_relevant({"search_query": "naked mole rat"}, "/nonexistent/clip.mp4") is False,
              "frame extraction failure -> reject unverified fal clip")
        check(M._FAL_SAFETY_UNAVAILABLE is True,
              "runtime safety failure disables further fal spend this render")
    finally:
        M.VISION_JUDGE = prev_vj
        M._FAL_SAFETY_UNAVAILABLE = prev_safety
        if prev_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = prev_key


def test_hook_headline_event():
    section("main._headline_event: top-anchored hook headline, auto-fit, optional")
    check(M._headline_event("") is None, "empty headline -> no event drawn")
    check(M._headline_event(None) is None, "None headline -> no event drawn")
    ev = M._headline_event("This animal can't die")
    check(ev is not None and "THIS ANIMAL CAN'T DIE" in ev, "headline text upper-cased into the event")
    check("\\an8" in ev, "headline anchored to the TOP of the frame (\\an8)")
    import re as _re
    long_ev = M._headline_event("WHAT HAPPENS IF YOU ARE THROWN INTO SPACE")
    m = _re.search(r"\\fs(\d+)", long_ev)
    check(bool(m) and int(m.group(1)) >= 50, "long headline auto-shrinks but stays >= readable floor")


def test_caption_autoshrink():
    section("main._event: over-wide words auto-shrink, normal words keep full size")
    import re as _re
    # NB: match \fs followed by a DIGIT (the fontsize override) — not \fscx/\fscy,
    # the pop-scale tags, which also start with "\fs".
    normal = M._event(1.0, 2.0, "aging")
    check(not _re.search(r"\\fs\d", normal), "short word has NO \\fs override (keeps style size)")
    long_ev = M._event(1.0, 2.0, "transdifferentiation")
    check(bool(_re.search(r"\\fs\d", long_ev)), "over-wide word gets a \\fs shrink so it fits the frame")
    m = _re.search(r"\\fs(\d+)", long_ev)
    fs = int(m.group(1)) if m else 0
    check(0 < fs < int(M.PROFILE.get("cap_size", 120)), f"shrunk size {fs} < base {M.PROFILE.get('cap_size')}")
    check(fs >= 58, f"shrunk size {fs} respects the readable floor (>=58)")


def test_bank_expander():
    section("expand_bank: strict WTF gate + dedup (scaling the bank to ~500)")
    have_ids = {"turtle_breathing"}
    have_norms = [E._norm("some turtles breathe through their rear ends underwater")]
    good = {"id":"New-Fact!","domain":"animals","fact":"A mushroom in Oregon is one single organism spread across four square miles.",
            "angle":"x","key_terms":["mushroom","Oregon"],"whatif":"What if the biggest living thing were a fungus?",
            "wow":"it is mostly underground","queries":["forest","mushroom","oregon woods"]}
    ok = E.accept_fact(good, have_ids, have_norms)
    check(ok is not None, "a strong novel fact is accepted")
    check(ok and ok["id"] == "new_fact", "id is sanitized to snake_case")
    # Generic application-fantasy WHATIFs caused bank drift toward "harness this
    # to build technology" instead of curiosity about the science itself.
    app = {**good, "id":"app1",
           "whatif":"What if we could harness fungal networks to create new communication technologies?"}
    check(E.accept_fact(app, have_ids, have_norms) is None,
          "generic 'What if we could harness/create technology' entry rejected")

    # Broad overview statements are topic descriptions, not scroll-stopping facts.
    vague = {**good, "id":"vague1",
             "fact":"Forests are complex ecosystems that rely on a delicate balance of relationships.",
             "whatif":"What happens underground when two trees compete for the same nutrients?"}
    check(E.accept_fact(vague, have_ids, have_norms) is None,
          "vague broad-overview fact with no concrete mechanism/specificity rejected")

    # Curiosity questions about the actual phenomenon remain allowed.
    curious = {**good, "id":"curious1",
               "whatif":"What happens when one part of a giant fungus is damaged miles from another part?"}
    check(E.accept_fact(curious, have_ids, have_norms) is not None,
          "science-centered curiosity whatif remains allowed")
    # magnitude/scale facts are rejected
    mag = {**good, "id":"m1", "fact":"There are 10 times more bacteria than human cells in your body."}
    check(E.accept_fact(mag, have_ids, have_norms) is None, "'N times more' magnitude fact rejected")
    mag2 = {**good, "id":"m2", "fact":"A shuffled deck has more combinations than atoms on Earth."}
    check(E.accept_fact(mag2, have_ids, have_norms) is None, "combinations/atoms magnitude fact rejected")
    # dup id + near-duplicate text rejected
    check(E.accept_fact({**good, "id":"turtle_breathing"}, have_ids, have_norms) is None, "duplicate id rejected")
    dupish = {**good, "id":"d1", "fact":"Some turtles breathe through their rear ends underwater."}
    check(E.accept_fact(dupish, have_ids, have_norms) is None, "near-duplicate fact text rejected")
    # missing keys / empty lists rejected
    check(E.accept_fact({"id":"x","domain":"y","fact":"a long enough claim about the world here"}, set(), []) is None,
          "schema-incomplete fact rejected")
    # domain CANONICALIZATION to the family name -- a real bank audit found
    # astronomy/mycology/botany/marine/oceanography each fragmenting an
    # already-well-stocked family (space/fungi/plants/ocean) under a
    # different domain string. New facts must heal that, not add to it.
    astro = {**good, "id": "astro1", "domain": "astronomy",
             "fact": "A planet in our solar system rains glass sideways in hundred-mile-an-hour winds."}
    ok2 = E.accept_fact(astro, set(), [])
    check(ok2 is not None and ok2["domain"] == "space",
          "a fact submitted under 'astronomy' is canonicalized to the 'space' family")
    marine = {**good, "id": "marine1", "domain": "marine",
              "fact": "A deep-sea fish generates its own light through a chemical reaction in its skin."}
    ok3 = E.accept_fact(marine, set(), [])
    check(ok3 is not None and ok3["domain"] == "ocean",
          "a fact submitted under 'marine' is canonicalized to the 'ocean' family")
    # _domain_counts groups by FAMILY, so a split-domain string doesn't read as
    # "thin" when its family is already well-stocked (the bug that would have
    # kept asking the LLM for more 'astronomy' facts forever)
    mixed_bank = ([{"id": f"s{i}", "domain": "space"} for i in range(17)]
                  + [{"id": f"a{i}", "domain": "astronomy"} for i in range(2)])
    counts = E._domain_counts(mixed_bank)
    check(counts.get("space") == 19 and "astronomy" not in counts,
          "space+astronomy count together as one 'space' family (19), not two thin domains")
    # JSON array extraction tolerates surrounding prose
    arr = E._extract_json_array('Sure! Here you go:\n[{"a":1}]\nHope that helps')
    check(_json.loads(arr) == [{"a":1}], "_extract_json_array pulls the array out of prose")


def test_topic_bank_integrity():
    section("topic_bank.json: every fact is schema-complete (regression guard)")
    bank = _json.load(open(os.path.join(os.path.dirname(M.__file__), "topic_bank.json")))
    facts = bank["facts"]
    check(len(facts) >= 180, f"bank hasn't lost facts unexpectedly ({len(facts)} facts)")
    ids = [f.get("id") for f in facts]
    check(len(ids) == len(set(ids)), "no duplicate fact ids")
    req = {"id","domain","fact","angle","key_terms","whatif","wow","queries"}
    bad = [f.get("id") for f in facts if not req <= set(f)]
    check(not bad, f"all facts have the full schema (missing: {bad[:3]})")
    listy = [f.get("id") for f in facts if not (isinstance(f.get("key_terms"),list) and isinstance(f.get("queries"),list))]
    check(not listy, f"key_terms + queries are lists everywhere (bad: {listy[:3]})")
    for f in facts:
        check(len(f.get("key_terms") or []) >= 2,
              f"{f.get('id')}: at least 2 key_terms (validate() requires 2+ named)")
        check("?" in (f.get("whatif") or ""), f"{f.get('id')}: whatif opens a real question")

    # near-duplicate FACT TEXT across different ids -- a real audit found two live
    # pairs that slipped past the id-uniqueness check above: cleopatra_pyramid_moon/
    # cleopatra_timeline (0.96 similarity, functionally the same fact) and
    # microbial_masters/microbe_intelligence (the latter already published as
    # "science_2026-08-02_microbes-are-thinking" -- the former was still sitting in
    # the bank ready to ship a near-identical video later under a different id).
    # Reuses expand_bank._too_similar's own threshold so "new fact rejected as a
    # dupe of the bank" and "the bank has no internal dupes" are the same bar.
    import difflib as _difflib
    norms = [(f["id"], E._norm(f["fact"])) for f in facts]
    dupes = []
    for i in range(len(norms)):
        for j in range(i + 1, len(norms)):
            if _difflib.SequenceMatcher(None, norms[i][1], norms[j][1]).ratio() > 0.62:
                dupes.append((norms[i][0], norms[j][0]))
    check(not dupes, f"no two different fact ids are near-duplicate text (found: {dupes[:5]})")


def test_runtime_topic_quarantine():
    section("generate: weak current topic seeds are quarantined without deleting them")
    bank = G.load_bank()
    q = G.load_topic_quarantine()
    bank_ids = {f.get("id") for f in bank}

    check(len(q) >= 50, f"quarantine is materially populated ({len(q)} ids)")
    check(q <= bank_ids, f"every quarantined id still exists in topic_bank.json ({len(q - bank_ids)} missing)")
    check("starling_murmurations" in q, "unsupported starling gravity/stars seed is quarantined")
    check("frozen_carbonite" in q, "science-fiction frozen-carbonite seed is quarantined")
    check("magnetic_moon" in q, "overstated lunar-magnetism seed is quarantined")
    check("memory_transplant" in q, "overstated sea-slug memory-transfer seed is quarantined")

    selected = G.selectable_bank(bank, q)
    selected_ids = {f.get("id") for f in selected}
    check(not (selected_ids & q), "normal selector excludes every quarantined fact")
    check(len(selected) < len(bank), f"selector shrinks the pool ({len(bank)} -> {len(selected)})")
    check(len(selected) >= 180, f"still leaves a large diverse production pool ({len(selected)} facts)")

    # Safety: quarantine corruption or an over-broad future list must never make
    # generation impossible. If every fact is excluded, preserve old behavior.
    all_ids = {f.get("id") for f in bank if f.get("id")}
    fail_open = G.selectable_bank(bank, all_ids)
    check(len(fail_open) == len(bank), "all-quarantined edge case fails open to the original bank")


def test_caption_pop_animation():
    section("main._event: kinetic pop-in (overshoot bounce) + bigger keyword pop")
    saved = set(M._KEYWORD_TOKENS)
    try:
        M._KEYWORD_TOKENS = {"VENOM"}
        normal = M._event(1.0, 2.0, "aging")
        # a normal word snaps on with an overshoot bounce back to 100%
        check("\\t(0,90,\\fscx110\\fscy110)" in normal and "\\t(90,160,\\fscx100\\fscy100)" in normal,
              "normal word: overshoot bounce (110% -> 100%)")
        check("\\fad(30,0)" in normal, "quick fade-in on every word")
        # a KEYWORD word pops BIGGER, settles slightly large, AND gets the accent colour
        kw = M._event(1.0, 2.0, "venom")
        check("\\fscx120\\fscy120" in kw, "keyword word bounces bigger (120%)")
        check("\\fscx104\\fscy104" in kw, "keyword word settles slightly large (104%) for emphasis")
        if M.PROFILE.get("cap_accent"):
            check(f"\\c{M.PROFILE['cap_accent']}" in kw, "keyword word rendered in the accent colour")
        # an over-wide (auto-shrunk) word uses a GENTLE grow, never a big overshoot
        wide = M._event(1.0, 2.0, "transdifferentiation")
        check("\\fscx120" not in wide and "\\fscx110" not in wide,
              "over-wide word avoids the big overshoot (can't shove off the no-wrap frame)")
    finally:
        M._KEYWORD_TOKENS = saved


def test_quality_floors_restored():
    section("generate: quality floors RE-RAISED after render-173 (dangling-comparative bug)")
    # 2026-07-29 loosened these floors believing GPT-4o's 6.1-6.9 drafts were being
    # unfairly rejected; render 173 then shipped a real coherence break ("T. rex is
    # closer to you" — closer than WHAT?) from a script that had cleared the OLD,
    # STRICTER floors, proving self-scored 6-7s aren't trustworthy enough to loosen
    # for. Locking the restored values in so they can't silently drift back down.
    check(G.QUALITY_HARD_FLOOR == 6.8, "hard floor restored to 6.8")
    check(G.QUALITY_CRITERION_FLOORS["hook"] == 6, "hook floor restored to 6")
    check(G.QUALITY_CRITERION_FLOORS["escalation"] == 6, "escalation floor restored to 6")
    check(G.QUALITY_CRITERION_FLOORS["payoff"] == 6, "payoff floor restored to 6")
    check(G.QUALITY_CRITERION_FLOORS["coherence"] == 7, "coherence floor RAISED to 7 (was 6)")


def test_draft_is_weak():
    section("generate.draft_is_weak: frugal Gemini-rescue trigger")
    thr = G.QUALITY_THRESHOLD
    floors = G.QUALITY_CRITERION_FLOORS
    # a clean, well-above-threshold script with all floors intact -> NOT weak
    strong = {k: 9 for k in G.QUALITY_RUBRIC_CRITERIA}
    check(G.draft_is_weak(thr + 0.5, strong) is False, "strong clean draft -> not weak (no rescue)")
    check(G.draft_is_weak(thr, strong) is False, "exactly at threshold, floors ok -> not weak")
    # below the clean threshold -> weak (the render-130 case: 6.83 < 7.5)
    check(G.draft_is_weak(6.83, {**strong, "overall": 6.83}) is True,
          "below clean threshold (6.83) -> weak (rescue)")
    # AT/above threshold overall but a broken per-criterion floor -> still weak
    fk = next(iter(floors))
    broken = {**strong, fk: floors[fk] - 1}
    check(G.draft_is_weak(thr + 1.0, broken) is True,
          f"high overall but {fk} below floor -> weak (rescue)")
    # Missing creative-quality evidence is itself weak: structural validity is
    # not permission to buffer/render an unscored script (Sep-1 regression).
    check(G.draft_is_weak(None, None) is True, "unscored clean script -> weak / fail closed")
    check(G.draft_is_weak(8.0, None) is True, "quality None -> weak / fail closed")
    # the force flag exists and defaults off so normal runs stay free-first
    check(G._FORCE_GEMINI_GEN is False, "_FORCE_GEMINI_GEN defaults off (free-first preserved)")
    # COHERENCE is a hard floor now (render-160 fix): a script that scores high on
    # everything but is INCOHERENT must be flagged weak (and, in main(), aborted) —
    # a confusing script can no longer hide behind a high overall.
    check("coherence" in floors, "coherence is a per-criterion floor")
    incoherent = {**strong, "coherence": floors["coherence"] - 1}
    check(G.draft_is_weak(thr + 1.0, incoherent) is True,
          "high overall but coherence below floor -> weak (the 9.33-on-nonsense bug)")


def test_cover_headline():
    section("main._cover_headline: cover thumbnail hook text")
    # uses the manifest's short hook_headline when present, uppercased
    check(M._cover_headline({"hook_headline": "Breathes How?!", "title": "X"}) == "BREATHES HOW?!",
          "hook_headline wins, uppercased")
    # falls back to the title when no hook_headline
    check(M._cover_headline({"title": "The Immortal Jellyfish"}) == "THE IMMORTAL JELLYFISH",
          "title fallback when no hook_headline")
    check(M._cover_headline({"hook_headline": "  ", "title": "Turtles"}) == "TURTLES",
          "blank hook_headline falls back to title")
    # never crashes on an empty manifest; long text is capped
    check(M._cover_headline({}) == "SCIENCE", "empty manifest -> safe default")
    check(len(M._cover_headline({"title": "z" * 200})) <= 60, "headline capped at 60 chars")


def test_variant_queries():
    section("main._variant_queries: widen the free footage pool (more video/scene)")
    v = M._variant_queries("pond turtle swimming")
    check(v[0] == "pond turtle swimming", "full phrase comes first")
    check("turtle" in v or "swimming" in v or "pond" in v, "broader single words included")
    check(len(v) == len(set(x.lower() for x in v)), "no duplicate variants")
    check(len(v) <= 4, "capped at 4 variants (bounded network work)")
    check(M._variant_queries("") == [], "empty query -> no variants")
    check(M._variant_queries("the a of") == ["the a of"], "all-stopword query -> just the phrase")


def test_perf_saves_comments():
    section("generate._perf_score: saves + comments are now weighted engagement signals")
    base = {"views": 1000, "watch_through_pct": 0.2, "follows": 2}
    s_base = G._perf_score(base)
    # a save (the jellyfish signal) lifts the score above an otherwise-identical video
    s_saves = G._perf_score({**base, "saves": 60})
    check(s_saves > s_base, "adding saves raises the perf score")
    # comments (the turtle signal) also lift it
    s_comments = G._perf_score({**base, "comments": 30})
    check(s_comments > s_base, "adding comments raises the perf score")
    # watch is still the dominant term: a big watch gain beats a big save gain
    hi_watch = G._perf_score({**base, "watch_through_pct": 0.6})
    check(hi_watch > s_saves, "watch_through_pct remains the primary signal")
    # backward-compatible: old entries with no saves/comments never crash and stay 0-safe
    check(G._perf_score({"views": 100, "watch_through_pct": 0.5}) > 0, "legacy entry still scores")
    check(G._perf_score({}) == 0.0, "empty entry -> 0.0 (safe)")
    check(G._perf_score("not a dict") == 0.0, "non-dict entry -> 0.0 (safe)")
    # the --record CLI aliases map save/comment tokens to the canonical keys
    check(G.__dict__.get("record_perf") is not None, "record_perf exists")


def test_length_ab_mode():
    section("generate: A/B video length — short vs long word window (analytics-driven)")
    # forced modes resolve to the intended windows (SHORT is tighter for completion%)
    check(G._resolve_length_mode.__call__() in ("short", "long"), "auto resolves to a valid mode")
    _saved = os.environ.get("LENGTH_MODE")
    try:
        os.environ["LENGTH_MODE"] = "short"
        check(G._resolve_length_mode() == "short", "LENGTH_MODE=short forces short")
        os.environ["LENGTH_MODE"] = "long"
        check(G._resolve_length_mode() == "long", "LENGTH_MODE=long forces long")
    finally:
        if _saved is None:
            os.environ.pop("LENGTH_MODE", None)
        else:
            os.environ["LENGTH_MODE"] = _saved
    # the window this test run pinned (long) must be the proven 85-115 completion band
    check((G.WORD_HARD_LO, G.WORD_HARD_HI) == (85, 115), "long hard window is 85-115")
    check(G.WORD_LO < G.WORD_HI <= G.WORD_HARD_HI and G.WORD_HARD_LO <= G.WORD_LO,
          "word bounds are ordered (hard_lo <= target_lo < target_hi <= hard_hi)")
    # SHORT's window must reflect what writer models ACTUALLY produce, not an
    # aspirational number nobody hits -- renders 187-191 (5 straight aborts, two
    # different writer models) wrote 83-111 words against the old 55-74/45-82
    # window, forcing a scene-dropping near-miss repair on every attempt that then
    # broke a SECOND mechanical gate (missing key term / whatif / redundancy).
    # Widened the same way the LONG-mode 85-115 fix was: match observed output.
    # Read straight from source (not a live reload -- WORD_LO etc. are resolved
    # ONCE at import off LENGTH_MODE, which this test process may have already
    # locked to "long") so this is a real, side-effect-free regression guard.
    import re as _re
    _src = open(G.__file__).read()
    _m = _re.search(
        r'if LENGTH_MODE == "short":.*?WORD_LO, WORD_HI, WORD_HARD_LO, WORD_HARD_HI = '
        r'(\d+), (\d+), (\d+), (\d+)', _src, _re.S)
    check(_m is not None, "SHORT word-window assignment found in source")
    _lo, _hi, _hlo, _hhi = (int(x) for x in _m.groups())
    check((_hlo, _hhi) != (45, 82),
          "SHORT hard window moved off the too-tight 45-82 that caused renders 187-191")
    check(_hhi - _hlo >= 30, "SHORT hard window has enough slack (>=30 words) for writer variance")
    check(_hhi >= 108, "SHORT hard ceiling comfortably covers the observed 83-111 word failure range")
    check(_hlo <= _lo < _hi <= _hhi, "SHORT word bounds are internally ordered")
    # a SHORT-length script (~63 words) must PASS a short-window validate and be
    # REJECTED by the long window — proving the A/B actually changes the gate.
    short_scenes = [{"id": i, "voiceover": "Here is one genuinely surprising true fact about it."}
                    for i in range(1, 8)]  # 7 scenes x 9 words = 63 words
    _bak = (G.WORD_LO, G.WORD_HI, G.WORD_HARD_LO, G.WORD_HARD_HI)
    try:
        G.WORD_LO, G.WORD_HI, G.WORD_HARD_LO, G.WORD_HARD_HI = 58, 74, 50, 80
        wc = sum(len(s["voiceover"].split()) for s in short_scenes)
        check(G.WORD_HARD_LO <= wc <= G.WORD_HARD_HI, f"a ~{wc}-word script fits the SHORT window")
        G.WORD_LO, G.WORD_HI, G.WORD_HARD_LO, G.WORD_HARD_HI = 95, 110, 85, 115
        check(not (G.WORD_HARD_LO <= wc <= G.WORD_HARD_HI), f"the same ~{wc}-word script is too short for LONG")
    finally:
        G.WORD_LO, G.WORD_HI, G.WORD_HARD_LO, G.WORD_HARD_HI = _bak


def test_fal_gap_fill_gating():
    section("main: fal AI-video gap-fill — subject-anchored prompt + cost gating (no network)")
    # prompt anchors on the literal SUBJECT (search_query), never the metaphor, and
    # guards against burned-in text/watermark — the render-160 relevance fix.
    sc = {"search_query": "pluto dwarf planet space",
          "voiceover": "Your great-grandparents saw its journey begin."}
    p = M._fal_prompt(sc)
    check(p.startswith("pluto dwarf planet space"), f"fal prompt leads with the subject ({p[:40]!r})")
    check("no text" in p and "no watermark" in p, "fal prompt guards against burned-in text/watermark")
    check(M._fal_prompt({"search_query": "", "voiceover": "just this"}).startswith("just this"),
          "falls back to the voiceover when there is no subject")
    # cost + safety gate: paid fal may spend only when an independent vision
    # safety check is configured and healthy. Otherwise stock/still/card wins.
    _k, _n, _cap = M.FAL_KEY, M.FAL_VIDEO_SCENES, M.FAL_MAX_CLIPS
    _vj, _safe = M.VISION_JUDGE, M._FAL_SAFETY_UNAVAILABLE
    _gem = os.environ.get("GEMINI_API_KEY")
    try:
        M.FAL_KEY, M.FAL_VIDEO_SCENES, M.FAL_MAX_CLIPS = "", 0, 2
        M.VISION_JUDGE, M._FAL_SAFETY_UNAVAILABLE = True, False
        os.environ["GEMINI_API_KEY"] = "x"
        check(M._fal_can_spend() is False, "no FAL_KEY -> never spends (feature is a no-op)")

        M.FAL_KEY = "x"
        os.environ.pop("GEMINI_API_KEY", None)
        check(M._fal_can_spend() is False,
              "fal key without independent Gemini safety judge -> do not spend")

        os.environ["GEMINI_API_KEY"] = "x"
        check(M._fal_can_spend() is True,
              "generation key + safety judge configured + under cap -> may spend")

        M._FAL_SAFETY_UNAVAILABLE = True
        check(M._fal_can_spend() is False,
              "after one safety outage, circuit stops further unreviewable fal spend")

        M._FAL_SAFETY_UNAVAILABLE = False
        M.FAL_VIDEO_SCENES = 2
        check(M._fal_can_spend() is False, "at the per-video cap -> stops spending")
    finally:
        M.FAL_KEY, M.FAL_VIDEO_SCENES, M.FAL_MAX_CLIPS = _k, _n, _cap
        M.VISION_JUDGE, M._FAL_SAFETY_UNAVAILABLE = _vj, _safe
        if _gem is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = _gem


def test_inaturalist_photo_license_safety():
    section("main._inaturalist_safe_photo_url: per-photo commercial-license gate + size upgrade")
    # 2026-08-03: live-tested iNaturalist before wiring it in -- most real
    # observations are cc-by-nc (non-commercial), so this check is NOT
    # theoretical; the query-level photo_license filter alone is not trusted.
    ok1 = M._inaturalist_safe_photo_url(
        {"url": "https://inaturalist-open-data.s3.amazonaws.com/photos/177220060/square.jpg",
         "license_code": "cc-by"})
    check(ok1 == "https://inaturalist-open-data.s3.amazonaws.com/photos/177220060/large.jpg",
          "cc-by photo accepted, square thumbnail upgraded to large")
    ok2 = M._inaturalist_safe_photo_url(
        {"url": "https://inaturalist-open-data.s3.amazonaws.com/photos/1/square.jpeg",
         "license_code": "cc0"})
    check(ok2 == "https://inaturalist-open-data.s3.amazonaws.com/photos/1/large.jpeg",
          "cc0 photo accepted, .jpeg extension handled too")
    check(M._inaturalist_safe_photo_url(
        {"url": "https://inaturalist-open-data.s3.amazonaws.com/photos/2/square.jpg",
         "license_code": "cc-by-nc"}) is None,
          "cc-by-nc (non-commercial) REJECTED even though the caller's query param already asked to exclude it")
    check(M._inaturalist_safe_photo_url(
        {"url": "https://inaturalist-open-data.s3.amazonaws.com/photos/3/square.jpg",
         "license_code": "cc-by-nc-nd"}) is None,
          "cc-by-nc-nd rejected")
    check(M._inaturalist_safe_photo_url(
        {"url": "https://inaturalist-open-data.s3.amazonaws.com/photos/4/square.jpg",
         "license_code": None}) is None,
          "missing license_code -> rejected (fail closed, never assume safe)")
    check(M._inaturalist_safe_photo_url({"license_code": "cc-by"}) is None,
          "missing url -> rejected, no crash")
    check(M._inaturalist_safe_photo_url({}) is None, "empty photo dict -> rejected, no crash")
    check(M._inaturalist_safe_photo_url(
        {"url": "https://inaturalist-open-data.s3.amazonaws.com/photos/5/square.jpg",
         "license_code": "CC-BY"}) is not None,
          "license check is case-insensitive")


def test_pollinations_free_illustration_gating():
    section("main: Pollinations.ai (free) AI-illustration — prompt sharing + cost gating + no-key no-op")
    # shared prompt helper: subject-anchored (search_query first), same rule as
    # the footage judge and _fal_prompt -- a metaphor line must not pull an
    # off-topic image. Both _pollinations_image and _gemini_image call this.
    sc = {"search_query": "pistol shrimp claw closeup", "voiceover": "a snap loud enough to boil water"}
    p = M._illustration_prompt(sc)
    check(p.startswith("Photorealistic cinematic vertical photograph"), "prompt opens with the fixed style prefix")
    check("pistol shrimp claw closeup" in p, "prompt is anchored on the literal subject, not the metaphor voiceover")
    check("no watermark" in p and "no text" in p, "prompt guards against burned-in text/watermark")
    check(M._illustration_prompt({"search_query": "", "voiceover": ""}) == "",
          "no subject and no voiceover -> empty prompt (caller must treat as failure)")

    # cost/key gate: the ONLY thing that lets Pollinations spend a call. No key
    # => never called (free tier byte-for-byte unchanged from before this
    # feature existed); at the per-video cap => stops, same shape as fal's gate.
    _k, _n, _cap = M.POLLINATIONS_KEY, M.POLLINATIONS_SCENES, M.MAX_POLLINATIONS_IMAGES
    try:
        M.POLLINATIONS_KEY, M.POLLINATIONS_SCENES, M.MAX_POLLINATIONS_IMAGES = "", 0, 6
        check(M._pollinations_can_spend() is False, "no POLLINATIONS_API_KEY -> never spends (feature is a no-op)")
        check(M._pollinations_image(sc, "/tmp/unused.png") is False,
              "no key -> _pollinations_image returns False with zero network attempt")
        M.POLLINATIONS_KEY = "x"
        check(M._pollinations_can_spend() is True, "key present and under cap -> may spend")
        M.POLLINATIONS_SCENES = 6
        check(M._pollinations_can_spend() is False, "at the per-video cap -> stops spending")
    finally:
        M.POLLINATIONS_KEY, M.POLLINATIONS_SCENES, M.MAX_POLLINATIONS_IMAGES = _k, _n, _cap


def test_apply_vibe():
    section("main._apply_vibe: mood-matched pacing/grade layered on the page profile")
    _profile_bak = dict(M.PROFILE)
    _clip_bak, _sub_bak = M.CLIP_SECONDS, M.MAX_SUBCLIPS
    try:
        check(set(M.VIBE_TWEAKS.keys()) == {"chaotic", "tense", "visceral", "eerie", "peaceful", "awe"},
              "VIBE_TWEAKS covers exactly the 6 vibes generate.py can emit")

        M.CLIP_SECONDS, M.MAX_SUBCLIPS = 1.9, 6
        base_grade = M.PROFILE["grade"]
        clip_s, subclips = M._apply_vibe("chaotic")
        check(clip_s < 1.9, f"chaotic -> SHORTER clips for faster cuts ({clip_s:.2f}s < 1.9s)")
        check(subclips > 6, f"chaotic -> MORE subclips allowed ({subclips} > 6)")
        check(M.PROFILE["grade"].startswith(base_grade) and M.PROFILE["grade"] != base_grade,
              "chaotic grade EXTENDS the base page grade (additive), doesn't replace it")

        M.PROFILE["grade"] = base_grade
        M.CLIP_SECONDS, M.MAX_SUBCLIPS = 1.9, 6
        clip_s, subclips = M._apply_vibe("peaceful")
        check(clip_s > 1.9, f"peaceful -> LONGER holds ({clip_s:.2f}s > 1.9s)")
        check(subclips < 6, f"peaceful -> FEWER subclips ({subclips} < 6)")

        M.PROFILE["grade"] = base_grade
        M.CLIP_SECONDS, M.MAX_SUBCLIPS = 1.9, 6
        clip_s, subclips = M._apply_vibe("some-invented-vibe")
        # 2026-08-03: "awe" (the fallback for an unknown/invalid vibe) used to be
        # all-zero deltas -- a true no-op that silently gave ~1/3 of real videos
        # (whichever landed on "awe") zero vibe variation at all. Gave it its own
        # mild "epic/sweeping" identity instead (see VIBE_TWEAKS), so even the
        # fallback case now nudges pacing/grade a little, just far less than the
        # more extreme vibes.
        check(1.9 < clip_s < 2.2, f"awe/unknown -> a MILD slow-down, not zero ({clip_s:.2f}s)")
        check(subclips == 6, f"awe/unknown -> subclip count unchanged ({subclips})")

        M.CLIP_SECONDS, M.MAX_SUBCLIPS = 0.95, 2
        M._apply_vibe("peaceful")
        check(M.CLIP_SECONDS >= 0.9, "clip seconds floor respected even after a slow-down multiplier")
        check(M.MAX_SUBCLIPS >= 2, "subclip count floor respected even after a negative bonus")

        # CURRENT_VIBE drives the AI hero-shot prompt style (_fal_prompt) --
        # this is where vibe should be MOST visible, since a hero shot is
        # bespoke already. Confirm the style descriptor actually changes.
        check(set(M.VIBE_PROMPT_STYLE.keys()) == set(M.VIBE_TWEAKS.keys()),
              "every vibe has a matching AI-prompt camera/lighting style")
        M._apply_vibe("chaotic")
        p_chaotic = M._fal_prompt({"search_query": "volcano eruption"})
        M._apply_vibe("peaceful")
        p_peaceful = M._fal_prompt({"search_query": "volcano eruption"})
        check("volcano eruption" in p_chaotic and "volcano eruption" in p_peaceful,
              "the literal subject is preserved regardless of vibe")
        check(p_chaotic != p_peaceful, "chaotic vs peaceful produce DIFFERENT AI-video prompts")
        check("erratic" in p_chaotic or "energy" in p_chaotic, "chaotic prompt reads energetic")
        check("gentle" in p_peaceful or "calm" in p_peaceful, "peaceful prompt reads calm")
        check("no watermark" in p_chaotic and "no watermark" in p_peaceful,
              "the no-text/watermark guard survives vibe styling on both")
    finally:
        M.PROFILE.clear()
        M.PROFILE.update(_profile_bak)
        M.CLIP_SECONDS, M.MAX_SUBCLIPS = _clip_bak, _sub_bak
        M.CURRENT_VIBE = "awe"


def test_vibe_matched_captions():
    section("main._event: caption pop intensity follows CURRENT_VIBE")
    _vibe_bak, _kw_bak = M.CURRENT_VIBE, set(M._KEYWORD_TOKENS)
    try:
        check(set(M.CAPTION_INTENSITY.keys()) == set(M.VIBE_TWEAKS.keys()),
              "every vibe has a caption-intensity entry")
        M._KEYWORD_TOKENS = {"MUON"}

        M.CURRENT_VIBE = "awe"
        awe_kw = M._event(0.0, 0.5, "muon")
        awe_plain = M._event(0.0, 0.5, "the")
        check("\\fscx120\\fscy120" in awe_kw and "\\fscx104\\fscy104" in awe_kw,
              "'awe' (intensity 1.0) reproduces the ORIGINAL hardcoded overshoot exactly -- no regression")
        check("\\fscx110\\fscy110" in awe_plain, "'awe' plain-word overshoot also unchanged")

        M.CURRENT_VIBE = "chaotic"
        chaotic_kw = M._event(0.0, 0.5, "muon")
        check(chaotic_kw != awe_kw, "chaotic produces a DIFFERENT (bigger) pop than awe")
        check("\\fscx128\\fscy128" in chaotic_kw, "chaotic keyword overshoot scaled up (120 * 1.4 = 128)")

        M.CURRENT_VIBE = "peaceful"
        peaceful_kw = M._event(0.0, 0.5, "muon")
        check(peaceful_kw != awe_kw, "peaceful produces a DIFFERENT (gentler) pop than awe")
        check("\\fscx113\\fscy113" in peaceful_kw, "peaceful keyword overshoot scaled down (100+20*0.65=113)")

        # the over-wide auto-shrink branch must NEVER overshoot past 100%,
        # regardless of vibe -- that safety cap predates vibe and must survive it
        M.CURRENT_VIBE = "chaotic"
        wide = M._event(0.0, 0.5, "transdifferentiations" * 2)
        check("\\t(0,110,\\fscx100\\fscy100)" in wide,
              "over-wide word's overshoot is LITERALLY unchanged by vibe -- caps at exactly 100%, "
              "chaotic can't reopen the no-wrap frame-overflow bug")
    finally:
        M.CURRENT_VIBE = _vibe_bak
        M._KEYWORD_TOKENS = _kw_bak


def test_vibe_music_filter():
    section("main._vibe_music_filter: music mix (volume/EQ) follows CURRENT_VIBE")
    _vibe_bak, _profile_bak = M.CURRENT_VIBE, dict(M.PROFILE)
    try:
        check(set(M.VIBE_MUSIC_FX.keys()) == set(M.VIBE_TWEAKS.keys()),
              "every vibe has a music-mix entry")
        M.PROFILE["music_vol"] = 0.14

        M.CURRENT_VIBE = "awe"
        awe_mix = M._vibe_music_filter()
        check(awe_mix == "volume=0.1400", "'awe' (vol_mult 1.0, no extra) is volume-only -- "
              "functionally identical to the pre-vibe hardcoded filter, no regression")

        M.CURRENT_VIBE = "chaotic"
        chaotic_mix = M._vibe_music_filter()
        check(chaotic_mix != awe_mix, "chaotic produces a DIFFERENT music mix than awe")
        check(chaotic_mix == "volume=0.1610,highpass=f=90",
              "chaotic sits louder (0.14*1.15=0.161) and brighter (highpass)")

        M.CURRENT_VIBE = "peaceful"
        peaceful_mix = M._vibe_music_filter()
        check(peaceful_mix != awe_mix, "peaceful produces a DIFFERENT music mix than awe")
        check(peaceful_mix == "volume=0.1190,lowpass=f=4200",
              "peaceful sits quieter (0.14*0.85=0.119) and warmer (lowpass)")

        # unknown/missing vibe must never crash the mix -- falls back to 'awe'
        M.CURRENT_VIBE = "not_a_real_vibe"
        check(M._vibe_music_filter() == awe_mix, "unknown CURRENT_VIBE falls back to 'awe' mix, no crash")
    finally:
        M.CURRENT_VIBE = _vibe_bak
        M.PROFILE.clear()
        M.PROFILE.update(_profile_bak)


def test_vibe_sting_freqs():
    section("main._vibe_sting_freqs: intro sting pitch/tone follows CURRENT_VIBE")
    # 2026-08-03 craft-audit finding: the intro sting was the ONE piece of
    # sound design that never varied with mood at all -- bit-for-bit
    # identical on every video regardless of vibe.
    _vibe_bak = M.CURRENT_VIBE
    try:
        check(set(M.VIBE_STING_FX.keys()) == set(M.VIBE_TWEAKS.keys()),
              "every vibe has a sting entry")

        M.CURRENT_VIBE = "awe"
        root, fifth, lp = M._vibe_sting_freqs()
        check((root, fifth, lp) == (98.0, 147.0, 1200),
              "'awe' reproduces the ORIGINAL hardcoded 98/147/1200 sting exactly -- no regression")

        M.CURRENT_VIBE = "chaotic"
        c_root, c_fifth, c_lp = M._vibe_sting_freqs()
        check(c_root > root, "chaotic pitches the sting HIGHER/brighter than awe")
        check(c_lp > lp, "chaotic opens the lowpass for more presence than awe")
        check(abs(c_fifth / c_root - 1.5) < 1e-9, "the fifth interval (x1.5) is preserved at any scale")

        M.CURRENT_VIBE = "eerie"
        e_root, e_fifth, e_lp = M._vibe_sting_freqs()
        check(e_root < root, "eerie pitches the sting LOWER/deeper than awe")
        check(e_lp < lp, "eerie closes the lowpass for a more muffled cue than awe")
        check(abs(e_fifth / e_root - 1.5) < 1e-9, "the fifth interval is preserved for eerie too")

        # unknown/missing vibe must never crash -- falls back to 'awe'
        M.CURRENT_VIBE = "not_a_real_vibe"
        check(M._vibe_sting_freqs() == (98.0, 147.0, 1200), "unknown CURRENT_VIBE falls back to 'awe', no crash")
    finally:
        M.CURRENT_VIBE = _vibe_bak


def test_trim_scene_to_cap():
    section("generate._trim_scene_to_cap: shorten (not drop) an over-cap near-miss scene")
    # already-short voiceover, unrelated to the cap directly (helper is only
    # ever called on over-cap scenes, but must be a safe no-op regardless)
    short = "A short punchy line."
    check(G._trim_scene_to_cap(short, 25) == short, "under-cap voiceover passes through untouched")
    # multi-sentence: keep only as many WHOLE leading sentences as fit --
    # never chop mid-sentence when a clean sentence boundary is available.
    # First sentence is 3 words (fits the cap=5 on its own); adding the
    # 10-word second sentence would push the total to 13, well over 5.
    two_sent = "This is short. This second sentence would push it well over the cap."
    out = G._trim_scene_to_cap(two_sent, 5)
    check(out == "This is short.",
          "trims at a sentence boundary, keeping only whole leading sentences")
    check(len(out.split()) <= 5, "sentence-boundary trim respects the cap")
    # single long run-on with no sentence punctuation at all -- must fall back
    # to a hard word truncation and re-terminate with a period, never crash
    run_on = "word " * 30
    out2 = G._trim_scene_to_cap(run_on.strip(), 10)
    check(len(out2.rstrip(".").split()) == 10, "no-punctuation run-on hard-truncates to exactly the cap")
    check(out2.endswith("."), "hard-truncated fallback is re-terminated with a period")
    # first sentence ALONE already exceeds the cap -- same hard-truncate
    # fallback (can't keep a whole sentence, but must still never exceed cap)
    one_long_sent = ("This single sentence just keeps going and going well past any "
                      "reasonable per-scene word budget for a short punchy video.")
    out3 = G._trim_scene_to_cap(one_long_sent, 12)
    check(len(out3.rstrip(".").split()) == 12, "an over-cap FIRST sentence alone also hard-truncates to the cap")


def test_reference_worthy_spelled_numbers():
    section("generate.REFERENCE_WORTHY_RE: catches spelled-out numbers, not just digits (render 194-200 bug)")
    # a script whose only "number" is spelled out in words must still pass --
    # renders 194/195/197/198/200 kept aborting exactly this once Gemini came
    # back online, because the old regex only matched digit characters
    check(G.REFERENCE_WORTHY_RE.search("It happens a dozen times a year."),
          "'a dozen' (spelled-out number) is reference-worthy")
    check(G.REFERENCE_WORTHY_RE.search("Three thousand years passed before anyone noticed."),
          "'three thousand' (spelled-out number) is reference-worthy")
    check(G.REFERENCE_WORTHY_RE.search("A hundred generations lived and died."),
          "'a hundred' (spelled-out number) is reference-worthy")
    # digits and the original phrase patterns must still match (no regression)
    check(G.REFERENCE_WORTHY_RE.search("It weighs 42 kilograms."), "a literal digit still matches")
    check(G.REFERENCE_WORTHY_RE.search("That's equivalent to a school bus."), "'equivalent to' still matches")
    # a script with genuinely nothing concrete (no number, spelled or digit,
    # and none of the comparison phrases) must still correctly fail the gate --
    # widening the regex must not turn it into a rubber stamp
    check(not G.REFERENCE_WORTHY_RE.search("Scientists find this genuinely fascinating and strange."),
          "a script with no concrete reference point still correctly fails")


def test_rubric_criterion_text_complete():
    section("generate.RUBRIC_CRITERION_TEXT: one source shared by score_script and revise_for_floors")
    # every scored criterion except 'rewatch' (dynamic, cta_style-dependent,
    # and carries no floor) must have a static rubric description
    for crit in G.QUALITY_RUBRIC_CRITERIA:
        if crit == "rewatch":
            continue
        check(crit in G.RUBRIC_CRITERION_TEXT and len(G.RUBRIC_CRITERION_TEXT[crit]) > 10,
              f"'{crit}' has a real rubric description")
    # every criterion that can actually trigger a targeted repair (i.e. has a
    # floor) MUST have text -- revise_for_floors would silently produce an
    # empty bullet for a floor violation otherwise
    for crit in G.QUALITY_CRITERION_FLOORS:
        check(crit in G.RUBRIC_CRITERION_TEXT, f"floored criterion '{crit}' has rubric text")


def test_apply_scene_rewrite():
    section("generate._apply_scene_rewrite: shared rewrite/validate/key-term guard (punch_up + revise_for_floors)")
    import copy as _copy
    base = _copy.deepcopy(FIX_ASTRO)
    # validate() requires >=2 of the fact's key_terms to be named (see
    # validate()'s "only N/M mandatory key terms" check), so a fact needs at
    # least 2 -- both already present in FIX_ASTRO's untouched scenes 2 and 3.
    fact = {"key_terms": ["243 Earth days", "225 Earth days"]}

    # success path: same scene ids, key term preserved, still validates clean
    # -> returns a trial with the new voiceovers AND a rebuilt "script" field
    good_scenes = {s["id"]: s["voiceover"] for s in base["scenes"]}
    good_scenes[2] = "The planet turns so slowly that one spin takes 243 Earth days to finish."
    trial = G._apply_scene_rewrite(base, fact, good_scenes, "test")
    check(trial is not None, "a clean, validate()-passing rewrite is accepted")
    check(trial["scenes"][1]["voiceover"] == good_scenes[2], "the rewritten scene's voiceover is applied")
    check(trial["script"] == " ".join(s["voiceover"] for s in trial["scenes"]),
          "the 'script' field is rebuilt from the new voiceovers")
    check(base["scenes"][1]["voiceover"] != good_scenes[2], "the ORIGINAL manifest is untouched (deepcopy)")

    # mismatched scene ids -> discarded
    missing_one = {s["id"]: s["voiceover"] for s in base["scenes"] if s["id"] != 1}
    check(G._apply_scene_rewrite(base, fact, missing_one, "test") is None,
          "a rewrite missing a scene id is discarded")

    # dropped mandatory key term -> discarded even though ids match
    dropped_term = {s["id"]: s["voiceover"] for s in base["scenes"]}
    dropped_term[2] = "The planet turns impossibly slowly on its axis."  # no longer says "243 Earth days"
    check(G._apply_scene_rewrite(base, fact, dropped_term, "test") is None,
          "a rewrite that drops a mandatory key term is discarded")

    # rewrite that fails validate() (introduces banned jargon) -> discarded.
    # No fact/key_terms here so the key-term guard can't mask WHICH check
    # actually caught it -- this isolates the validate() call itself.
    jargon = {s["id"]: s["voiceover"] for s in base["scenes"]}
    jargon[3] = "It forms at 42 degrees from the antisolar point, opposite the sun."
    check(G._apply_scene_rewrite(base, None, jargon, "test") is None,
          "a rewrite that fails validate() (banned jargon) is discarded")


def test_revise_for_floors():
    section("generate.revise_for_floors: targeted fix for named criteria (not a blind full regeneration)")
    import copy as _copy, json as _json
    base = _copy.deepcopy(FIX_ASTRO)
    # validate() requires >=2 of the fact's key_terms named, so 2 here --
    # both already present untouched in FIX_ASTRO's scenes 3.
    fact = {"fact": "Venus's day is longer than its year.",
            "key_terms": ["243 Earth days", "225 Earth days"]}
    violations = {"hook": 5.0, "escalation": 5.0}

    # a clean rewrite response -> accepted, script rebuilt, original untouched
    clean_scenes = [{"id": s["id"], "voiceover": s["voiceover"]} for s in base["scenes"]]
    clean_scenes[1]["voiceover"] = "The planet turns so slowly that one spin takes 243 Earth days to complete."
    orig_call = G.call_groq
    G.call_groq = lambda _p: _json.dumps({"scenes": clean_scenes})
    try:
        out = G.revise_for_floors(base, fact, violations)
        check(out is not None, "a clean targeted rewrite is accepted")
        check(out["scenes"][1]["voiceover"] == clean_scenes[1]["voiceover"],
              "the targeted rewrite's voiceover is applied")
        check(base["scenes"][1]["voiceover"] != clean_scenes[1]["voiceover"],
              "the original candidate manifest is not mutated")
    finally:
        G.call_groq = orig_call

    # a call_groq failure must not crash -- returns None so the caller falls
    # through to its existing (unchanged) full-regeneration path
    G.call_groq = lambda _p: (_ for _ in ()).throw(RuntimeError("rate limited"))
    try:
        check(G.revise_for_floors(base, fact, violations) is None,
              "a failed LLM call returns None, never raises")
    finally:
        G.call_groq = orig_call

    # a TRANSIENT failure (a 503, an empty body) shouldn't cost the whole
    # repair -- one immediate retry should recover it
    _calls = {"n": 0}
    def _flaky(_p):
        _calls["n"] += 1
        if _calls["n"] == 1:
            raise RuntimeError("503 Service Unavailable")
        return _json.dumps({"scenes": clean_scenes})
    G.call_groq = _flaky
    try:
        out = G.revise_for_floors(base, fact, violations)
        check(_calls["n"] == 2, "a transient failure triggers exactly one immediate retry")
        check(out is not None and out["scenes"][1]["voiceover"] == clean_scenes[1]["voiceover"],
              "the retry's successful response is used")
    finally:
        G.call_groq = orig_call

    # an empty-string response (the OpenRouter hiccup seen live) is treated the
    # same as an exception -- retried once, not accepted as-is
    _calls = {"n": 0}
    def _empty_then_ok(_p):
        _calls["n"] += 1
        return "" if _calls["n"] == 1 else _json.dumps({"scenes": clean_scenes})
    G.call_groq = _empty_then_ok
    try:
        out = G.revise_for_floors(base, fact, violations)
        check(_calls["n"] == 2, "an empty response also triggers exactly one retry")
        check(out is not None, "the retry recovers a usable rewrite")
    finally:
        G.call_groq = orig_call

    # CHAINED repair: the first rewrite fixes the violated criteria but
    # introduces a SEPARATE, different problem (drops a mandatory key term) --
    # a second informed pass should fix THAT too rather than discarding the
    # whole repair and falling back to blind full regeneration.
    first_pass_scenes = [{"id": s["id"], "voiceover": s["voiceover"]} for s in base["scenes"]]
    first_pass_scenes[1]["voiceover"] = "The planet turns impossibly slowly on its axis."  # drops "243 Earth days"
    second_pass_scenes = [dict(s) for s in first_pass_scenes]
    # kept comfortably below the anti-restatement similarity threshold (0.40)
    # against fact["fact"] -- unlike a close paraphrase of the original line,
    # this isolates the key-term-repair path from that unrelated guard.
    second_pass_scenes[1]["voiceover"] = "One full spin of the planet on its axis takes a lengthy 243 Earth days to happen."
    _calls = {"n": 0}
    _prompts = []
    def _two_stage(p):
        _calls["n"] += 1
        _prompts.append(p)
        scenes = first_pass_scenes if _calls["n"] == 1 else second_pass_scenes
        return _json.dumps({"scenes": scenes})
    G.call_groq = _two_stage
    try:
        out = G.revise_for_floors(base, fact, violations)
        check(_calls["n"] == 2, "a rewrite that introduces a NEW problem triggers exactly one chained repair call")
        check(out is not None, "the chained repair's fixed version is accepted")
        check(out is not None and "243 Earth days" in out["scenes"][1]["voiceover"],
              "the chained pass restored the key term the first pass dropped")
        check("key term" in _prompts[1].lower() or "243 Earth days" in _prompts[1],
              "the chain prompt names the SPECIFIC new problem the first pass introduced")
    finally:
        G.call_groq = orig_call

    # if the chained repair ALSO fails to fix the new problem, give up cleanly
    # (None), never ship the still-broken rewrite
    G.call_groq = lambda _p: _json.dumps({"scenes": first_pass_scenes})  # always drops the key term
    try:
        check(G.revise_for_floors(base, fact, violations) is None,
              "a chained repair that still fails validation returns None, not the broken rewrite")
    finally:
        G.call_groq = orig_call

    # the prompt actually NAMES the violated criteria and quotes their rubric
    # text -- this is the whole point (a targeted fix, not a guess)
    captured = {}
    def _capture(p):
        captured["prompt"] = p
        return _json.dumps({"scenes": clean_scenes})
    G.call_groq = _capture
    try:
        G.revise_for_floors(base, fact, violations)
        check("HOOK" in captured["prompt"] and "ESCALATION" in captured["prompt"],
              "the repair prompt names the specific failing criteria")
        check(G.RUBRIC_CRITERION_TEXT["hook"] in captured["prompt"],
              "the repair prompt quotes the EXACT hook rubric text (shared with score_script)")
        check("payoff" not in captured["prompt"].lower(),
              "a criterion that did NOT fail is not mentioned (truly targeted, not the whole rubric)")
    finally:
        G.call_groq = orig_call

    # "hook" scores m["hook"], a field this function otherwise never touches --
    # a hook-floor violation must actually rewrite it (see HOOK_REPAIR_GUIDANCE),
    # not just shuffle scene voiceovers around while the bad hook ships unchanged.
    captured = {}
    def _capture_hook(p):
        captured["prompt"] = p
        return _json.dumps({"scenes": clean_scenes, "hook": "Sharks are older than trees."})
    G.call_groq = _capture_hook
    try:
        out = G.revise_for_floors(base, fact, {"hook": 5.0})
        check("HOOK REWRITE RULES" in captured["prompt"],
              "hook violated -> the richer HOOK_REPAIR_GUIDANCE block is injected into the prompt")
        check(base["hook"] in captured["prompt"],
              "the prompt shows the model the CURRENT hook it needs to fix")
        check(out is not None and out["hook"] == "Sharks are older than trees.",
              "the model's rewritten hook is applied to the trial manifest")
    finally:
        G.call_groq = orig_call

    # hook NOT among the violated criteria -> no guidance injected, and even if
    # the (possibly hallucinating) model returns a "hook" key anyway, it must be
    # ignored -- only touch what's actually broken
    captured = {}
    def _capture_nohook(p):
        captured["prompt"] = p
        return _json.dumps({"scenes": clean_scenes, "hook": "Should be ignored entirely."})
    G.call_groq = _capture_nohook
    try:
        out = G.revise_for_floors(base, fact, {"escalation": 5.0})
        check("HOOK REWRITE RULES" not in captured["prompt"],
              "hook not violated -> HOOK_REPAIR_GUIDANCE is not injected")
        check(out is not None and out["hook"] == base["hook"],
              "hook not violated -> an unsolicited 'hook' in the reply is ignored, original kept")
    finally:
        G.call_groq = orig_call

    # a rewritten hook that itself fails validate() (e.g. reintroduces a
    # dangling comparative) must be discarded by the shared validate() guard --
    # the hook rewrite is not exempt from the checks any other hook must pass
    G.call_groq = lambda _p: _json.dumps(
        {"scenes": clean_scenes, "hook": "Venus is somehow closer to you."})
    try:
        check(G.revise_for_floors(base, fact, {"hook": 5.0}) is None,
              "a rewritten hook with a dangling comparative is rejected by validate(), discarded")
    finally:
        G.call_groq = orig_call


def test_inject_missing_key_terms():
    section("generate.inject_missing_key_terms: targeted fix for a missing mandatory term (renders 188/198/199/201)")
    import copy as _copy, json as _json
    base = _copy.deepcopy(FIX_ASTRO)
    # "225 Earth days" is already present verbatim (scene 3, untouched);
    # "backwards rotation" is genuinely absent -- so exactly one of the two
    # key_terms needs fixing, isolating the MISSING-term repair path.
    fact = {"key_terms": ["225 Earth days", "backwards rotation"]}
    check("backwards rotation" not in " ".join(s["voiceover"] for s in base["scenes"]).lower(),
          "sanity: 'backwards rotation' is genuinely absent from the fixture")

    # nothing missing -> no-op, no LLM call, returns None immediately
    check(G.inject_missing_key_terms(base, {"key_terms": ["225 Earth days"]}) is None,
          "no missing terms (only checking a present one) -> None, no-op")

    # a clean rewrite that works the missing term in -> accepted
    clean_scenes = [{"id": s["id"], "voiceover": s["voiceover"]} for s in base["scenes"]]
    clean_scenes[4]["voiceover"] = "Stranger still, it spins backwards rotation compared with almost every planet."
    orig_call = G.call_groq
    G.call_groq = lambda _p: _json.dumps({"scenes": clean_scenes})
    try:
        out = G.inject_missing_key_terms(base, fact)
        check(out is not None, "a rewrite that successfully works in the missing term is accepted")
        if out is not None:
            full = out["script"] + " " + " ".join(s["voiceover"] for s in out["scenes"])
            check("backwards rotation" in full.lower(), "the previously-missing term is now present")
    finally:
        G.call_groq = orig_call

    # a rewrite that STILL doesn't include the missing term must be discarded
    # -- self-verifying via _apply_scene_rewrite's validate() call, not just
    # trusting the model claims to have fixed it
    still_missing = [{"id": s["id"], "voiceover": s["voiceover"]} for s in base["scenes"]]
    G.call_groq = lambda _p: _json.dumps({"scenes": still_missing})
    try:
        check(G.inject_missing_key_terms(base, fact) is None,
              "a rewrite that still omits the missing term is discarded, not accepted on faith")
    finally:
        G.call_groq = orig_call

    # the prompt actually lists the missing term(s), not the whole key_terms set
    captured = {}
    def _capture(p):
        captured["prompt"] = p
        return _json.dumps({"scenes": clean_scenes})
    G.call_groq = _capture
    try:
        G.inject_missing_key_terms(base, fact)
        check("backwards rotation" in captured["prompt"], "the repair prompt names the missing term")
        check("225 Earth days" not in captured["prompt"].split("MUST explicitly say")[1].split("\n")[0],
              "a term that's already present is not listed as something to add")
    finally:
        G.call_groq = orig_call

    # LLM failure never crashes -- returns None so the caller's abandon path is unchanged
    G.call_groq = lambda _p: (_ for _ in ()).throw(RuntimeError("rate limited"))
    try:
        check(G.inject_missing_key_terms(base, fact) is None, "a failed LLM call returns None, never raises")
    finally:
        G.call_groq = orig_call


def test_near_miss_injects_missing_key_term():
    section("generate.py: near-miss mechanically repairs a missing key term end-to-end (renders 188/198/199/201)")
    # Every attempt names only 1 of 2 required key_terms (the model explains
    # the concept but never says "backwards rotation" verbatim) -- validate()
    # rejects on "only 1/2 mandatory key terms named" every time, and this
    # becomes the near-miss. inject_missing_key_terms should work the missing
    # term in and the run should SHIP rather than abandon.
    import copy as _copy, json as _json
    bad = _copy.deepcopy(FIX_ASTRO)
    raw = _json.dumps(bad)
    fixed_scenes = [{"id": s["id"], "voiceover": s["voiceover"]} for s in bad["scenes"]]
    fixed_scenes[4]["voiceover"] = "Stranger still, it spins backwards rotation compared with almost every planet."
    fixed_raw = _json.dumps({"scenes": fixed_scenes})
    # call_groq is used for BOTH the raw attempt generation (needs the full
    # manifest shape) and the later targeted-repair call (needs just
    # {"scenes": [...]});  key off which one is being asked for.
    def _router(p):
        return fixed_raw if "MUST explicitly say" in p else raw
    orig_call, orig_circuit = G.call_groq, G._CIRCUIT_OPEN
    G.call_groq = _router
    G._CIRCUIT_OPEN = False
    # deliberately NOT "Venus's day is longer than its year" -- that phrasing
    # incidentally scores >0.40 similarity (validate()'s restatement guard,
    # see check_information_gain) against TWO of FIX_ASTRO's own untouched
    # scenes, tripping an unrelated, correct rejection and masking the thing
    # this test actually checks. A lexically distant fact statement isolates
    # the key-term repair path.
    fact = {"id": "x", "fact": "A neighboring world does not turn the way most do.",
            "angle": "backwards planet",
            "key_terms": ["225 Earth days", "backwards rotation"], "whatif": "", "wow": "",
            "queries": ["venus planet"]}
    try:
        res = G.generate_candidate("EXPLAIN", "explain a thing", "none", fact,
                                    history=[], dossier="(dossier)")
    finally:
        G.call_groq = orig_call
        G._CIRCUIT_OPEN = orig_circuit
    check(res is not None, "the missing-key-term-only violation is mechanically repaired and SHIPPED")
    if res is not None:
        full = res["script"] + " " + " ".join(s["voiceover"] for s in res["scenes"])
        check("backwards rotation" in full.lower(), "the repaired script now names the missing term")


def test_subclip_plan():
    section("main._subclip_plan: multi-clip scene splitting (more clips / flashing)")
    # a short scene stays a single clip (no sub-cutting)
    check(M._subclip_plan(2.0, 2.4, 4) == [round(2.0, 3)], "short scene (2.0s) -> 1 clip")
    # a ~6s scene at 2.4s target -> round(6/2.4)=round(2.5)=2 (banker's rounding) or 3;
    # whichever, it must be >1 and sum exactly to seg_dur
    for seg in (5.0, 6.0, 7.2, 9.6):
        plan = M._subclip_plan(seg, 2.4, 4)
        check(len(plan) > 1, f"{seg}s scene -> multiple clips ({len(plan)})")
        check(abs(sum(plan) - seg) < 1e-6, f"{seg}s sub-durations sum to seg_dur exactly")
        check(len(plan) <= 4, f"{seg}s scene respects MAX_SUBCLIPS cap (<=4)")
    # the cap is honored even for a very long scene
    check(len(M._subclip_plan(30.0, 2.4, 4)) == 4, "30s scene capped at 4 clips")
    # fail-safe: bad inputs collapse to a single segment, never crash
    check(M._subclip_plan(0, 2.4, 4) == [0.0], "zero-duration -> single empty segment")
    check(M._subclip_plan(6.0, 0, 4) == [6.0], "zero target -> single full segment")
    check(M._subclip_plan(6.0, 2.4, 0) == [6.0], "max_subclips 0 -> single full segment")
    check(M._extra_scene_clips({}, 0, set(), "/tmp/x") == [], "need<=0 -> no extra clips (no network)")


def test_unstockable_query_exempts_physical_systems():
    section("generate.UNSTOCKABLE_Q: physical '___ system(s)' exempted, abstract ones still banned (render-2026-08-04)")
    # Two real renders rejected perfectly filmable queries as "un-filmable"
    # because the bare word "system(s)" was banned everywhere. 'solar system
    # planets' and 'tree root system soil' both name a literal, physical,
    # genuinely photographable thing -- stock libraries handle these fine.
    filmable = ["solar system planets", "tree root system soil", "river system delta",
                "weather system storm clouds", "mountain system range", "solar system"]
    for q in filmable:
        check(not G.UNSTOCKABLE_Q.search(q), f"{q!r} is filmable, must NOT be flagged un-filmable")
    # the actual failure mode this check exists for -- an ABSTRACT/FUNCTIONAL
    # system with nothing physical to point a camera at -- must still be
    # caught. render-181 regression: "resilient communication systems"
    # rendered as a lingering generic abstract network-graphic; this exact
    # case must stay banned, not just body/anatomy systems.
    unfilmable = ["resilient communication systems", "human nervous system",
                  "digestive system anatomy", "economic systems collapse"]
    for q in unfilmable:
        check(G.UNSTOCKABLE_Q.search(q) is not None, f"{q!r} (abstract system) must still be flagged un-filmable")
    # pre-existing jargon bans (fungal terms, organs, anatomy, quantum) untouched by this fix
    check(G.UNSTOCKABLE_Q.search("human organs regrowing") is not None, "organs still banned (unchanged)")
    check(G.UNSTOCKABLE_Q.search("fungal hyphae soil dirt") is not None, "hyphae still banned (unchanged)")
    check(G.UNSTOCKABLE_Q.search("fungus mycelium underground macro") is not None, "mycelium still banned (unchanged)")
    check(G.UNSTOCKABLE_Q.search("human stomach anatomy") is not None, "anatomy still banned (unchanged)")
    check(G.UNSTOCKABLE_Q.search("quantum entanglement lab") is not None, "quantum still banned (unchanged)")


def test_rank_gemini_models_prefers_full_over_lite():
    section("generate._rank_gemini_models: full-quality models rank ABOVE Lite variants (render-2026-08-04 bug)")
    # The exact real-world case that exposed the bug: the OLD ranking sorted
    # purely on whether a name contained "-latest", so the deliberately weaker/
    # cheaper 'lite' model ranked ABOVE a full, numbered model just because both
    # happened to carry a -latest-style tag. A real render's rescue attempt then
    # burned its one shot on the Lite model while the stronger one was never
    # tried in either generation cycle that run.
    ranked = G._rank_gemini_models(["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.6-flash"])
    check(ranked[0] == "gemini-flash-latest", "the -latest full-quality alias still leads")
    check(ranked.index("gemini-3.6-flash") < ranked.index("gemini-flash-lite-latest"),
          "a full, numbered model ranks ABOVE the Lite variant, regardless of -latest tagging")
    check("lite" not in ranked[0], "the very first pick is never a lite model when a full one exists")

    # a lite model is still USABLE (never dropped) -- it's a last resort, not banned
    check(set(ranked) == {"gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.6-flash"},
          "no model is dropped, only reordered")

    # preview/exp ids stay lowest priority even when also tagged -latest (the old
    # code's OWN documented intent -- 'stable over preview/exp' -- which it broke
    # for any preview/exp id that also happened to contain -latest)
    ranked2 = G._rank_gemini_models(["gemini-2.5-flash-preview-latest", "gemini-flash-latest", "gemini-3.6-flash"])
    check(ranked2[-1] == "gemini-2.5-flash-preview-latest",
          "a preview id ranks LAST even though it also contains -latest")

    # numbered-stable models, newest first, when there's no -latest alias at all
    ranked3 = G._rank_gemini_models(["gemini-2.0-flash", "gemini-3.6-flash", "gemini-2.5-flash"])
    check(ranked3[0] == "gemini-3.6-flash", "newest numbered id leads when nothing is tagged -latest")

    # a lite-only list still returns something usable (never empty)
    check(G._rank_gemini_models(["gemini-flash-lite-latest"]) == ["gemini-flash-lite-latest"],
          "lite-only input isn't discarded, just the only option")
    check(G._rank_gemini_models([]) == [], "empty input -> empty output, no crash")


def test_429_wait_and_retry_helpers():
    section("generate: strong-writer 429 wait-and-retry (always-a-video fix)")
    # _is_weak_model: only Groq-8B/instant and Cerebras are the weak backstops
    check(G._is_weak_model("groq", "llama-3.1-8b-instant") is True, "groq 8b-instant is weak")
    check(G._is_weak_model("cerebras", "gemma-4-31b") is True, "cerebras gemma is weak")
    check(G._is_weak_model("groq", "llama-3.3-70b-versatile") is False, "groq 70b is a primary writer")
    check(G._is_weak_model("gemini", "gemini-flash-latest") is False, "gemini is a primary writer")
    check(G._is_weak_model("openrouter", "meta-llama/llama-3.3-70b-instruct") is False,
          "openrouter 70b is a primary writer")
    # the discontinued free slug must NOT be the default any more (paid credits now)
    check(all(":free" not in m for m in G.OPENROUTER_MODELS),
          "openrouter default slug is the PAID llama-3.3-70b (no dead :free slug)")
    check(G._is_weak_model("github", "gpt-4o-mini") is False, "github gpt-4o-mini is a primary writer")
    # _parse_retry_secs: parse the per-minute wait hint each provider gives
    check(abs(G._parse_retry_secs("Please try again in 11.83s.") - 11.83) < 1e-6,
          "Groq 'try again in 11.83s' -> 11.83")
    check(G._parse_retry_secs("Please wait 55 seconds before retrying.") == 55.0,
          "GitHub 'wait 55 seconds' -> 55")
    check(G._parse_retry_secs('{"retryDelay": "6s"}') == 6.0, "Gemini retryDelay 6s -> 6")
    check(G._parse_retry_secs("try again in 2 minutes") == 120.0, "'2 minutes' -> 120s")
    # a hard/daily 429 with no wait hint must NOT be treated as retryable
    check(G._parse_retry_secs("This model is unavailable for free.") is None,
          "no wait hint -> None (falls to weak backstop, no infinite wait)")
    check(G._parse_retry_secs("") is None, "empty body -> None")


# --------------------------------------------------------------------------
# writer_v2.py -- the V2 writer experiment (WRITER_V2=1 mission, 2026-09-03)
# --------------------------------------------------------------------------
def test_writer_v2_treatments():
    section("writer_v2.TREATMENTS / select_treatment: structural diversity + deterministic zero-LLM selection")
    check(len(W2.TREATMENTS) == 8, f"exactly 8 treatments defined ({len(W2.TREATMENTS)})")
    for name, t in W2.TREATMENTS.items():
        check(5 <= len(t["beats"]) <= 7, f"{name}: 5-7 beats ({len(t['beats'])})")
        check(len(set(t["beats"])) == len(t["beats"]), f"{name}: no duplicate beat within itself")
        check(t.get("default_vibe") in ("chaotic", "peaceful", "eerie", "awe", "visceral", "tense"),
              f"{name}: default_vibe is a real vibe tag ({t.get('default_vibe')})")

    # structural diversity: no two treatments share an identical beat sequence
    # (the exact failure mode this replaces -- every story collapsing into the
    # same hook->question->fact-list->twist shape)
    seqs = [tuple(t["beats"]) for t in W2.TREATMENTS.values()]
    check(len(set(seqs)) == len(seqs), "no two treatments have an identical beat sequence")

    # deterministic + reproducible: same fact_id always -> same treatment
    a = W2.select_treatment("wood_frog_freeze")
    b = W2.select_treatment("wood_frog_freeze")
    check(a == b, "select_treatment is deterministic for the same fact_id")
    check(a in W2.TREATMENTS, "the selected treatment is a real treatment name")

    # spreads across the set for different facts (not always the same one)
    picks = {W2.select_treatment(f"fact_{i}") for i in range(40)}
    check(len(picks) >= 5, f"select_treatment spreads across the treatment set ({len(picks)} distinct of 8)")

    # avoids recently-used treatments
    all_names = sorted(W2.TREATMENTS.keys())
    avoid_all_but_one = all_names[1:]
    picked = W2.select_treatment("some_fact", recent_treatments=avoid_all_but_one)
    check(picked == all_names[0],
          "excluding every treatment but one leaves exactly that one selectable")

    # fail-open: if recent_treatments would exclude EVERY treatment, fall back
    # to the full set rather than returning None (mirrors generate.selectable_bank)
    picked_all_excluded = W2.select_treatment("some_fact", recent_treatments=all_names)
    check(picked_all_excluded in W2.TREATMENTS,
          "excluding every treatment fails OPEN to the full set, never returns nothing")


def test_writer_v2_story_packet():
    section("writer_v2.build_story_packet: compact, non-fabricated research summary")
    fact = {
        "id": "test_fact", "domain": "physics",
        "fact": "The central verified claim about this topic.",
        "angle": "a fallback mechanism description",
        "wow": "a further escalation detail as the wow field",
        "queries": ["subject one footage", "subject two footage"],
        "key_terms": ["potassium-40", "half-life"],
    }
    dossier = [
        "This works because of a specific physical mechanism causing the effect.",
        "A first supporting detail with its own concrete number.",
        "A second supporting detail, also concrete.",
        "This means the implication extends to everyday life as a result.",
        "A third supporting detail nobody usually mentions.",
    ]
    p = W2.build_story_packet(fact, dossier_facts=dossier, grounded=True)
    check(p["central_claim"] == fact["fact"], "central_claim anchors to the base fact, not model memory")
    check("mechanism" in p["mechanism"].lower(), "mechanism field picks the dossier item naming the mechanism")
    check(p["mechanism"] != p["surprising_implication"], "mechanism and implication are different picks")
    check(len(p["supporting_facts"]) <= 3, "supporting_facts capped at 3")
    check("implication" in p["surprising_implication"].lower() or p["surprising_implication"] == fact["wow"],
          "surprising_implication picks the dossier item naming an implication (or falls back to wow)")
    check(p["caveat"] == "", "grounded=True -> no caveat")
    check("Google Search" in p["source"], "grounded=True -> source says so")
    check(p["visual_opportunities"] == fact["queries"], "visual_opportunities carries the fact's own queries")
    check(p["key_terms"] == fact["key_terms"], "packet carries the fact's own key_terms verbatim")

    # every field must trace to an input -- never fabricate new prose
    inputs = set(dossier) | {fact["fact"], fact["angle"], fact["wow"]}
    check(p["central_claim"] in inputs and p["mechanism"] in inputs and p["surprising_implication"] in inputs,
          "every packet field is drawn verbatim from an input, nothing invented")

    # degraded path: no dossier at all (grounding unavailable) -> honest
    # ungrounded provenance, still built entirely from the curated base fact
    p2 = W2.build_story_packet(fact, dossier_facts=[], grounded=False)
    check(p2["central_claim"] == fact["fact"], "no-dossier path still anchors to the base fact")
    check(p2["mechanism"] == fact["angle"], "no-dossier path falls back to the fact's own angle for mechanism")
    check(p2["supporting_facts"] == [fact["wow"]], "no-dossier path falls back to the fact's own wow as support")
    check("not independently grounded" in p2["caveat"], "no-dossier path states its own degraded provenance honestly")
    check("ungrounded" in p2["source"], "no-dossier path's source string says ungrounded, not silently grounded")

    # totally empty fact -> no crash, no fabrication
    p3 = W2.build_story_packet({}, dossier_facts=[], grounded=False)
    check(p3["central_claim"] == "", "empty fact -> empty central_claim, not invented text")


def test_writer_v2_prompt_size():
    section("writer_v2.build_writer_prompt_v2 / estimate_tokens: the actual size-reduction claim")
    fact = G.load_bank()[10]
    dossier = ["A distinct verified facet of the topic with its own concrete detail."] * 7
    legacy_prompt = G.build_prompt("CURIOSITY_ITCH", G.VIEWER_JOBS[0][1], "t1, t2, t3", fact=fact,
                                   avoid_openers="Did you know, Have you ever", cta_style="SAVE_WORTHY",
                                   dossier=dossier, hook_frame=G.HOOK_FRAMES[0])
    packet = W2.build_story_packet(fact, dossier_facts=dossier, grounded=False)
    treatment = W2.select_treatment(fact["id"])
    v2_prompt = W2.build_writer_prompt_v2(treatment, packet, avoid_topics="t1, t2, t3",
                                          visual_evidence=fact.get("queries"))
    legacy_tok = G.estimate_tokens(legacy_prompt) if hasattr(G, "estimate_tokens") else len(legacy_prompt) // 4
    v2_tok = W2.estimate_tokens(v2_prompt)
    check(v2_tok < legacy_tok * 0.5, f"V2 prompt is under half the legacy size ({v2_tok} vs {legacy_tok} est. tokens)")
    # the actual mission target: comfortably below Groq's 8000 TPM cap, with
    # real headroom left for the completion budget (max_tokens=2000) too
    check(v2_tok + 2000 < 8000 * 0.7,
          f"V2 prompt + a 2000-token completion budget leaves >=30% headroom under Groq's 8000 TPM cap "
          f"(prompt {v2_tok} + completion 2000 = {v2_tok + 2000})")
    check(WRITER_V2_STATIC_IS_STABLE := (W2.build_writer_prompt_v2(treatment, packet).startswith(W2.WRITER_V2_STATIC)),
          "the stable creative-contract prefix is genuinely first in the prompt (prompt-caching precondition)")

    # both gaps the live script-only bakeoff actually caught (all 3 V2 drafts
    # rejected by validate() on the first pass: 2/3 for a banned formal
    # connector never named in the V2 prompt, 1/3 for never being told to use
    # >=2 of the fact's own key_terms) must be closed in the prompt text.
    for banned_word in ("however", "essentially", "furthermore", "nevertheless"):
        check(banned_word in W2.WRITER_V2_STATIC.lower(),
              f"WRITER_V2_STATIC explicitly bans the formal connector {banned_word!r} "
              f"(caught live in the script-only bakeoff)")
    fact_kt = {"key_terms": ["potassium-40", "half-life"]}
    packet_kt = W2.build_story_packet(fact_kt, dossier_facts=[], grounded=False)
    check(packet_kt["key_terms"] == ["potassium-40", "half-life"], "packet carries the fact's key_terms")
    prompt_kt = W2.build_writer_prompt_v2(treatment, packet_kt)
    check("potassium-40" in prompt_kt and "half-life" in prompt_kt,
          "the prompt explicitly surfaces the fact's own key_terms (caught live in the bakeoff: "
          "a draft used only 1/3 mandatory key terms)")
    check("at least 2" in prompt_kt.lower(), "the prompt explicitly requires naming at least 2 key_terms")
    check('"?"' in W2.WRITER_V2_STATIC and "first 3 beats" in W2.WRITER_V2_STATIC,
          "WRITER_V2_STATIC explicitly requires the hard curiosity-gap question mark "
          "(caught live in the bakeoff: all 3 drafts failed 'whatif curiosity gap never opened' "
          "once the connector/key_terms gaps were fixed)")


def test_writer_v2_schema():
    section("writer_v2.WRITER_V2_SCHEMA: shape sanity for structured-output calls")
    s = W2.WRITER_V2_SCHEMA
    check(s["type"] == "object", "schema root is an object")
    check(set(s["required"]) == {"title", "hook", "beats", "payoff"}, "schema requires exactly the 4 writer fields")
    check(s["additionalProperties"] is False, "schema rejects stray extra top-level fields (strict mode)")
    beats_schema = s["properties"]["beats"]
    check(beats_schema["minItems"] == 5 and beats_schema["maxItems"] == 7, "schema enforces 5-7 beats")
    item = beats_schema["items"]
    check(set(item["required"]) == {"voiceover", "visual_intent"}, "each beat requires voiceover + visual_intent")


def test_writer_v2_assemble_manifest():
    section("writer_v2.assemble_manifest_v2: downstream mechanical fields, and validate()-compatible shape")
    fact = {"id": "test_fact", "domain": "physics", "key_terms": ["potassium-40", "half-life"],
            "fact": "x", "wow": "y", "queries": ["subject footage"]}
    writer_out = {
        "title": "The Clock Inside Every Banana",
        "hook": "Your banana is faintly radioactive right now.",
        "beats": [
            {"voiceover": "Bananas contain potassium, and a tiny slice of it is radioactive.",
             "visual_intent": "close up of a banana being peeled"},
            {"voiceover": "That radioactive potassium is called potassium-40.",
             "visual_intent": "geiger counter clicking near fruit"},
            {"voiceover": "Your own body has the same potassium in it, all the time.",
             "visual_intent": "person eating a banana"},
            {"voiceover": "So you are, quietly, a little bit radioactive too.",
             "visual_intent": "silhouette of a person glowing faintly"},
            {"voiceover": "It is far too small an amount to ever matter to your health.",
             "visual_intent": "doctor reassuring gesture"},
        ],
        "payoff": "The radiation was never really about the banana. It was always about you.",
    }
    m = W2.assemble_manifest_v2(writer_out, fact, "HIDDEN_MECHANISM", banned_query_re=G.UNSTOCKABLE_Q)
    for key in ("title", "viewer_job", "keyword", "metaphor", "vibe", "hook", "hook_headline",
               "script", "scenes", "captions", "hashtags", "render", "treatment"):
        check(key in m, f"assembled manifest carries legacy-schema field '{key}'")
    check(len(m["scenes"]) == 5, "one scene per writer beat")
    check(all(s["search_query"] and not G.UNSTOCKABLE_Q.search(s["search_query"]) for s in m["scenes"]),
          "every derived search_query is non-empty and passes the SAME un-filmable-terms gate as production")
    check(m["treatment"] == "HIDDEN_MECHANISM", "the manifest records which treatment was used")
    check(m["vibe"] == W2.TREATMENTS["HIDDEN_MECHANISM"]["default_vibe"],
          "vibe defaults to the treatment's own default")
    check(len(m["hook_headline"]) <= 22, f"hook_headline fits the cover's character budget ({m['hook_headline']!r})")
    check(m["hook_headline"] == m["hook_headline"].upper(), "hook_headline is ALL CAPS")
    check([s["motion"] for s in m["scenes"]] == ["zoom_in", "zoom_out", "pan_left", "pan_right", "zoom_in"],
          "motion cycles deterministically across scenes")
    check(m["keyword"] == "potassium-40", "keyword derives from the fact's own key_terms")

    # feed straight into the REAL production validator -- must not crash on
    # this manifest shape, whatever the actual verdict is
    try:
        verdict = G.validate(m, "CURIOSITY_ITCH", fact=fact)
        check(True, f"assembled V2 manifest is structurally acceptable to validate() (verdict: {verdict!r})")
    except Exception as e:  # noqa: BLE001
        check(False, f"assembled V2 manifest crashed validate(): {type(e).__name__}: {e}")


def test_writer_v2_helpers():
    section("writer_v2 mechanical helpers: search query / hook headline / motion / vibe")
    check(W2.derive_search_query("a naked mole rat underground tunnel") == "naked mole rat underground tunnel",
          "derive_search_query strips stopwords, keeps the filmable noun phrase")
    check(W2.derive_search_query("") == "science footage", "empty visual_intent -> a safe non-empty fallback")
    banned = G.UNSTOCKABLE_Q
    q = W2.derive_search_query("the quantum molecular diagram of a cell", banned_re=banned)
    check(not banned.search(q), "a banned-term visual_intent still yields a query that passes the banned-term gate")

    check(W2.derive_hook_headline("Your stomach acid could dissolve a razor blade.") != "",
          "derive_hook_headline produces non-empty output")
    check(len(W2.derive_hook_headline("A" * 100)) <= 22, "derive_hook_headline respects max_chars even on long input")

    check(W2.derive_vibe("CASE_FILE") == "tense", "derive_vibe reads the treatment's own default_vibe")
    check(W2.derive_vibe("NOT_A_REAL_TREATMENT") == "awe", "unknown treatment -> safe default vibe, no crash")

    kw, meta = W2.derive_keyword_metaphor({"key_terms": ["axolotl"]}, "The Animal That Never Grows Up")
    check(kw == "axolotl", "keyword prefers the fact's first key_term")
    kw2, meta2 = W2.derive_keyword_metaphor({}, "A Title With No Fact Behind It")
    check(kw2 == "A Title With", "no key_terms -> keyword falls back to the title's first words")


def test_writer_v2_visual_scout():
    section("writer_v2.visual_scout_score / rank_topics_by_visual_score: visual-first topic selection")
    strong = {"domain": "ocean", "key_terms": ["bioluminescence", "deep sea"],
              "queries": ["glowing jellyfish deep ocean", "bioluminescent plankton waves",
                         "anglerfish deep sea light", "submarine deep ocean dive"]}
    weak = {"domain": "psychology", "key_terms": ["confirmation bias"],
            "queries": ["night sky stars"]}
    s_strong = W2.visual_scout_score(strong, banned_re=G.UNSTOCKABLE_Q)
    s_weak = W2.visual_scout_score(weak, banned_re=G.UNSTOCKABLE_Q)
    check(s_strong["score"] > s_weak["score"],
          f"a visually rich ocean topic scores above a visually thin abstract one "
          f"({s_strong['score']} vs {s_weak['score']})")
    check(s_strong["distinct_subjects"] >= 3, "4 distinct filmable queries -> distinct_subjects >= 3")
    check(s_weak["generic_filler_hits"] >= 1, "a bare 'night sky stars' query is counted as generic filler")
    check(0 <= s_strong["score"] <= 10 and 0 <= s_weak["score"] <= 10, "scores stay within the 0-10 band")
    check(s_strong["verdict"] != s_weak["verdict"], "strong and weak topics get different verdict text")

    # un-filmable (banned) queries must not count toward distinct_subjects
    banned_only = {"domain": "body", "key_terms": [],
                  "queries": ["cell diagram anatomy", "molecular structure abstract"]}
    s_banned = W2.visual_scout_score(banned_only, banned_re=G.UNSTOCKABLE_Q)
    check(s_banned["distinct_subjects"] == 0,
          "queries that are entirely banned/un-filmable terms count as zero distinct subjects")

    # empty fact -> no crash; the two query-driven sub-scores are both zero
    # (domain_coverage/mechanism_visual fall back to neutral defaults on no
    # data, so the overall score isn't necessarily 0, but nothing about
    # "having visuals" can be true of a fact with no queries at all)
    s_empty = W2.visual_scout_score({}, banned_re=G.UNSTOCKABLE_Q)
    check(s_empty["hook_visual"] == 0 and s_empty["distinct_subjects"] == 0,
          "a fact with no queries at all has zero hook_visual and zero distinct_subjects, not a crash")
    check(s_empty["score"] < s_strong["score"], "the empty fact still scores well below a genuinely strong topic")

    ranked = W2.rank_topics_by_visual_score([weak, strong], banned_re=G.UNSTOCKABLE_Q)
    check(ranked[0][0] is strong, "rank_topics_by_visual_score puts the visually stronger topic first")
    check(ranked[0][1]["score"] >= ranked[1][1]["score"], "ranking is actually sorted descending by score")


def main():
    print("LOCAL PIPELINE TESTS (zero quota, no network, no ffmpeg)")
    test_validate_clean()
    test_validate_rejections()
    test_content_alignment()
    test_diversify_queries()
    test_diversify_motions()
    test_footage_intent_anchors_on_subject()
    test_local_footage_relevance()
    test_final_qa()
    test_persist_qa_to_memory()
    test_vibe_and_hybrid_footage_mode()
    test_keywords_from_text()
    test_prefix_starts_and_chars()
    test_build_ass_fallback_monotonic()
    test_square_crop_top()
    test_domain_family()
    test_series_and_callback()
    test_funnel_affiliate_coverage()
    test_generate_helpers()
    test_research_dossier_requires_grounding()
    test_caption_function_word_grouping()
    test_script_buffer_queue()
    test_xfade_offsets_monotonic()
    test_critique_script_merges_gain_and_score()
    test_shadow_lift_filter()
    test_vision_call_budget()
    test_fal_clip_verdict_rejects_garbled_text_independent_of_score()
    test_fal_clip_relevant()
    test_hook_headline_event()
    test_caption_autoshrink()
    test_caption_pop_animation()
    test_bank_expander()
    test_topic_bank_integrity()
    test_runtime_topic_quarantine()
    test_draft_is_weak()
    test_quality_floors_restored()
    test_cover_headline()
    test_variant_queries()
    test_perf_saves_comments()
    test_length_ab_mode()
    test_fal_gap_fill_gating()
    test_inaturalist_photo_license_safety()
    test_pollinations_free_illustration_gating()
    test_apply_vibe()
    test_vibe_matched_captions()
    test_vibe_music_filter()
    test_vibe_sting_freqs()
    test_trim_scene_to_cap()
    test_reference_worthy_spelled_numbers()
    test_rubric_criterion_text_complete()
    test_apply_scene_rewrite()
    test_revise_for_floors()
    test_inject_missing_key_terms()
    test_near_miss_injects_missing_key_term()
    test_subclip_plan()
    test_unstockable_query_exempts_physical_systems()
    test_rank_gemini_models_prefers_full_over_lite()
    test_429_wait_and_retry_helpers()
    test_fast_fail_when_throttled()
    test_call_groq_empty_response_falls_through()
    test_near_miss_repair_revalidates()
    test_near_miss_injects_missing_curiosity_gap()
    test_writer_v2_treatments()
    test_writer_v2_story_packet()
    test_writer_v2_prompt_size()
    test_writer_v2_schema()
    test_writer_v2_assemble_manifest()
    test_writer_v2_helpers()
    test_writer_v2_visual_scout()
    print(f"\n{'='*60}\nRESULT: {_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
