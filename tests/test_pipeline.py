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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M
import generate as G

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

    # scene count out of range (too few)
    m = copy.deepcopy(FIX_GEO); m["scenes"] = m["scenes"][:4]
    m["script"] = " ".join(s["voiceover"] for s in m["scenes"])
    check(G.validate(m, "EXPLAIN") is not None, "scene count below 6 rejected")

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
    actual_durs = [3.05, 2.95, 3.0, 3.1, 2.9, 3.0, 3.0]
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


def main():
    print("LOCAL PIPELINE TESTS (zero quota, no network, no ffmpeg)")
    test_validate_clean()
    test_validate_rejections()
    test_content_alignment()
    test_diversify_queries()
    test_footage_intent_anchors_on_subject()
    test_keywords_from_text()
    test_prefix_starts_and_chars()
    test_build_ass_fallback_monotonic()
    test_generate_helpers()
    test_fast_fail_when_throttled()
    print(f"\n{'='*60}\nRESULT: {_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
