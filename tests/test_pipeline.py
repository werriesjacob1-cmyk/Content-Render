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

    # command ending: "send this to a friend" (the render-67 Krakatoa flaw). The
    # rubric bans command endings; SHARE is out of the rotation and the guard now
    # rejects the phrasing outright.
    m = copy.deepcopy(FIX_PHYS)
    m["scenes"][-1]["voiceover"] = "Send this to the friend who thinks they have heard it all."
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "'send this to a friend' command ending rejected")
    check("SHARE" not in G.CTA_STYLES, "SHARE command-ending style removed from rotation")

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
        M._final_qa_check("/nonexistent/video.mp4", {"scenes": [{"voiceover": "x"}]})
        rep = _json.load(open(os.path.join(M.OUT, "qa_report.json")))
        check(rep == {"ran": False}, "no GEMINI_API_KEY -> qa_report.json written as a clean no-op")
    finally:
        M.OUT = _out_bak
        if _key_bak is not None:
            os.environ["GEMINI_API_KEY"] = _key_bak


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
def test_domain_family():
    section("generate._domain_family: earth-science domains share one family")
    check(G._domain_family("geology") == G._domain_family("earth") == G._domain_family("weather"),
          "geology/earth/weather map to the same family (no back-to-back deep-earth videos)")
    check(G._domain_family("space") != G._domain_family("earth"), "space stays distinct from earth")
    check(G._domain_family("animals") == "animals", "unlisted domain is its own family")


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


# --------------------------------------------------------------------------
# 6. fast-fail when all providers throttled (wall-clock budget work)
# --------------------------------------------------------------------------
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
    # JSON array extraction tolerates surrounding prose
    arr = E._extract_json_array('Sure! Here you go:\n[{"a":1}]\nHope that helps')
    check(_json.loads(arr) == [{"a":1}], "_extract_json_array pulls the array out of prose")


def test_topic_bank_integrity():
    section("topic_bank.json: every fact is schema-complete (regression guard)")
    bank = _json.load(open(os.path.join(os.path.dirname(M.__file__), "topic_bank.json")))
    facts = bank["facts"]
    check(len(facts) >= 115, f"bank has grown ({len(facts)} facts)")
    ids = [f.get("id") for f in facts]
    check(len(ids) == len(set(ids)), "no duplicate fact ids")
    req = {"id","domain","fact","angle","key_terms","whatif","wow","queries"}
    bad = [f.get("id") for f in facts if not req <= set(f)]
    check(not bad, f"all facts have the full schema (missing: {bad[:3]})")
    listy = [f.get("id") for f in facts if not (isinstance(f.get("key_terms"),list) and isinstance(f.get("queries"),list))]
    check(not listy, f"key_terms + queries are lists everywhere (bad: {listy[:3]})")


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
    # ungradable-but-clean (overall/quality None) -> NOT weak: leave it be, no spend
    check(G.draft_is_weak(None, None) is False, "unscored clean script -> not weak (no rescue)")
    check(G.draft_is_weak(8.0, None) is False, "quality None -> not weak")
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
    # cost gate: the ONLY thing that lets fal spend. No key => never spends (free
    # tier byte-for-byte unchanged); at the per-video cap => stops.
    _k, _n, _cap = M.FAL_KEY, M.FAL_VIDEO_SCENES, M.FAL_MAX_CLIPS
    try:
        M.FAL_KEY, M.FAL_VIDEO_SCENES, M.FAL_MAX_CLIPS = "", 0, 2
        check(M._fal_can_spend() is False, "no FAL_KEY -> never spends (feature is a no-op)")
        M.FAL_KEY = "x"
        check(M._fal_can_spend() is True, "key present and under cap -> may spend")
        M.FAL_VIDEO_SCENES = 2
        check(M._fal_can_spend() is False, "at the per-video cap -> stops spending")
    finally:
        M.FAL_KEY, M.FAL_VIDEO_SCENES, M.FAL_MAX_CLIPS = _k, _n, _cap


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
        check((clip_s, subclips) == (1.9, 6), "unknown vibe -> 'awe' entry, all deltas zero, no change")

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


def main():
    print("LOCAL PIPELINE TESTS (zero quota, no network, no ffmpeg)")
    test_validate_clean()
    test_validate_rejections()
    test_content_alignment()
    test_diversify_queries()
    test_footage_intent_anchors_on_subject()
    test_local_footage_relevance()
    test_final_qa()
    test_vibe_and_hybrid_footage_mode()
    test_keywords_from_text()
    test_prefix_starts_and_chars()
    test_build_ass_fallback_monotonic()
    test_domain_family()
    test_generate_helpers()
    test_caption_function_word_grouping()
    test_script_buffer_queue()
    test_xfade_offsets_monotonic()
    test_critique_script_merges_gain_and_score()
    test_shadow_lift_filter()
    test_vision_call_budget()
    test_hook_headline_event()
    test_caption_autoshrink()
    test_caption_pop_animation()
    test_bank_expander()
    test_topic_bank_integrity()
    test_draft_is_weak()
    test_quality_floors_restored()
    test_cover_headline()
    test_variant_queries()
    test_perf_saves_comments()
    test_length_ab_mode()
    test_fal_gap_fill_gating()
    test_apply_vibe()
    test_vibe_matched_captions()
    test_vibe_music_filter()
    test_subclip_plan()
    test_429_wait_and_retry_helpers()
    test_fast_fail_when_throttled()
    test_near_miss_repair_revalidates()
    print(f"\n{'='*60}\nRESULT: {_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
