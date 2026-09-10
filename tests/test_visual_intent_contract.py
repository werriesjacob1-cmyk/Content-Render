#!/usr/bin/env python3
"""The visual-intent contract, proven on a DIVERSE corpus of real manifests.

Twelve committed August manifests across ten domains (animals, biology, body,
chemistry, geology, light, materials, neurology, physics, space) are used as the
false-positive control: they are real, human-approved, post-worthy output, and
the repair must not touch a single one of their queries.

The failure classes use the ACTUAL query strings observed in live runs, not
invented ones:
  * chess_possible_games  -- 'deep space stars moving', 'galaxy stars space'
  * Anglo-Zanzibar        -- 'kingdom entire lunch'
  * banana radiation      -- the shipped control that passed QA

TWO MECHANISMS, DELIBERATELY SEPARATE. Prevention stops a bad query being built
(`_diversify_scene_queries` subject anchoring); repair rescues a candidate whose
query validate() rejects. They cover different defects and the tests say which
covers which, rather than implying one catches everything.

Zero network, zero providers, zero LLM.
"""
from __future__ import annotations

import copy
import glob
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import generate as G
import main as M
import visual_intent as V

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORPUS = sorted(glob.glob(str(ROOT / "tests" / "fixtures" / "legacy_controls" / "science_*.json")))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# 1 ----------------------------------------------------------------------------
def test_1_good_queries_are_never_gratuitously_rewritten():
    """The false-positive control, and the most important test here.

    These 12 manifests rendered and scored 7.0-8.29. If the repair rewrites their
    queries it is not a fix, it is a regression with extra steps."""
    check(len(CORPUS) == 12, f"12 real historical manifests present ({len(CORPUS)})")
    domains, total, repaired = set(), 0, 0
    for path in CORPUS:
        man = _load(path)
        domains.add(man["domain"])
        fam = G._domain_family(man["domain"])
        before = [s["search_query"] for s in man["scenes"]]
        changed = V.repair_scene_queries(man["scenes"], man.get("keyword", ""), fam)
        after = [s["search_query"] for s in man["scenes"]]
        total += len(before)
        repaired += len(changed)
        check(before == after, f"{man['domain']}: every query byte-identical after repair")
    check(len(domains) >= 8, f"corpus spans >=8 distinct domains ({len(domains)}: {sorted(domains)})")
    check(repaired == 0, f"0 of {total} real approved queries were rewritten (got {repaired})")


# 2 ----------------------------------------------------------------------------
def test_2_cosmic_filler_on_a_non_space_scene_is_repaired():
    """The chess_possible_games failure class, with its real query strings."""
    scenes = [{"search_query": "galaxy stars space",
               "voiceover": "After just four moves the board holds billions of arrangements.",
               "source_claim_ids": ["c1"]}]
    changed = V.repair_scene_queries(scenes, "chess", "math")
    check(len(changed) == 1, f"the cosmic-filler query is repaired ({changed})")
    check(changed[0][3] == V.DEFECT_COSMIC_FILLER, "classified as cosmic filler, precisely")
    new = scenes[0]["search_query"]
    check(new.startswith("chess"), f"the repair is subject-led ({new!r})")
    check(not V.COSMIC_FILLER_Q_RE.search(new), "and contains no cosmic filler")
    check(V.query_defect(new, scenes[0]["voiceover"], "math") is None,
          "the repaired query passes the SAME predicate validate() applies")


# 3 ----------------------------------------------------------------------------
def test_3_a_literal_astronomy_scene_may_still_use_space_words():
    """Cosmic imagery is correct for a space story. The rule must not ban it."""
    vo = "Venus spins so slowly that its day outlasts its year."
    check(V.query_defect("venus planet surface", vo, "space") is None,
          "a space-domain query is untouched")
    check(V.query_defect("milky way galaxy", vo, "space") is None,
          "even explicit cosmic wording is legal when the domain IS space")
    # and a deliberate space METAPHOR in a non-space story stays legal, because
    # the scene's own narration mentions space -- the pre-existing escape hatch.
    meta = "Its heart beats slower than a star collapses."
    check(V.query_defect("deep space nebula", meta, "biology") is None,
          "a scene whose own narration is space-related keeps its space imagery")


# 4 ----------------------------------------------------------------------------
def test_4_metaphor_words_never_become_the_visual_subject():
    """The Anglo-Zanzibar 'kingdom entire lunch' class.

    HONEST SCOPE: this salad carries no `query_defect` -- it is not unstockable
    vocabulary and not cosmic filler -- so the REPAIR path does not catch it. It
    is handled by PREVENTION instead: the subject-anchored diversifier refuses to
    build it. Both are asserted here so the division of labour is explicit."""
    vo = "An entire kingdom fell in less time than a lunch break."
    check(V.query_defect("kingdom entire lunch", vo, "history") is None,
          "the salad has no defect code -- repair is NOT the mechanism for it")
    built = V.subject_led_query("anglo zanzibar war", vo, {})
    check(built.startswith("anglo zanzibar war"), f"prevention builds subject-led ({built!r})")
    for metaphor in ("lunch", "entire"):
        check(metaphor not in built, f"the metaphor word {metaphor!r} is not the subject")
    check(M._subject_anchored_query("anglo zanzibar war", vo, {}) == built,
          "main.py delegates to the same contract -- one rule, not two")


# 5 ----------------------------------------------------------------------------
def test_5_repair_touches_only_search_query():
    """The accuracy invariant. Retrieval metadata is not a licence to edit science."""
    scenes = [{
        "id": 1, "duration": 5.0,
        "search_query": "deep space nebula",
        "voiceover": "Bananas carry a naturally radioactive form of potassium.",
        "on_screen_text": "POTASSIUM-40",
        "source_claim_ids": ["base_001", "base_002"],
        "motion": "zoom_in", "footage_mode": "video",
    }]
    original = copy.deepcopy(scenes[0])
    V.repair_scene_queries(scenes, "banana radiation", "physics")
    got = scenes[0]
    check(got["search_query"] != original["search_query"], "the query WAS repaired")
    for field in ("voiceover", "source_claim_ids", "on_screen_text", "id",
                  "duration", "motion", "footage_mode"):
        check(got[field] == original[field],
              f"{field} is byte-identical through repair")
    check(set(got) == set(original), "no field added or removed")


# 6 ----------------------------------------------------------------------------
def test_6_unrepairable_scene_keeps_its_query_and_still_fails():
    """Fail closed. Never ship unrelated footage just to obtain an MP4."""
    scenes = [{"search_query": "galaxy stars space", "voiceover": "It is there."}]
    changed = V.repair_scene_queries(scenes, "", "math")   # no subject to anchor to
    check(changed == [], "with nothing grounded to build from, nothing is repaired")
    check(scenes[0]["search_query"] == "galaxy stars space",
          "the original is left intact so validate() still rejects the candidate")
    check(V.subject_led_query("", "anything", {}) == "",
          "no subject -> empty, never invented filler")


# 7 ----------------------------------------------------------------------------
def test_7_no_topic_specific_conditionals():
    """The regression topics are FIXTURES, not production policy.

    Checks EXECUTABLE CODE, not raw text. Comments and docstrings naming the
    incident that motivated a rule are how this repo documents provenance
    everywhere ('render-209 bug', 'the Sun video'), and stripping that would make
    the code harder to maintain, not safer. What must not exist is a topic string
    the program can branch on."""
    import io, tokenize

    def code_only(path):
        """Source with every comment and string literal removed."""
        out = []
        with open(path, "rb") as fh:
            for tok in tokenize.tokenize(io.BytesIO(fh.read()).readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                out.append(tok.string)
        return " ".join(out).lower()

    for mod in ("visual_intent.py", "generate.py", "main.py"):
        src = code_only(ROOT / mod)
        for topic in ("chess", "zanzibar", "anglo", "banana", "shortest_war",
                      "possible_games"):
            check(topic not in src,
                  f"{mod} has no executable reference to {topic!r} (comments are fine)")

    # And no literal topic ids anywhere in the contract's own logic.
    vi = code_only(ROOT / "visual_intent.py")
    for tok in ("topic_id", "domain ==", "keyword =="):
        check(tok not in vi, f"the contract branches on no topic identity ({tok!r})")


# 8 ----------------------------------------------------------------------------
def test_8_abstract_topics_are_not_categorically_rejected():
    """An abstract concept is not automatically unfilmable."""
    cases = [
        ("chess", "Four moves produce billions of arrangements on the board.", "math"),
        ("dice probability", "Rolling two dice gives eleven possible totals.", "math"),
        ("information entropy", "Each coin flip carries exactly one bit.", "math"),
    ]
    for subject, vo, fam in cases:
        q = V.subject_led_query(subject, vo, {}, fam)
        check(q and q.startswith(subject),
              f"abstract subject {subject!r} still yields a usable query ({q!r})")
        check(V.query_defect(q, vo, fam) is None, f"and it is legal ({q!r})")


# 9 ----------------------------------------------------------------------------
def test_9_one_contract_not_two():
    """generate.py must not keep a private copy of the rule."""
    check(G.UNSTOCKABLE_Q is V.UNSTOCKABLE_Q, "UNSTOCKABLE_Q is the shared object")
    check(G.COSMIC_FILLER_Q_RE is V.COSMIC_FILLER_Q_RE, "COSMIC_FILLER_Q_RE is shared")
    check(G.SPACE_CONTEXT_RE is V.SPACE_CONTEXT_RE, "SPACE_CONTEXT_RE is shared")
    gsrc = (ROOT / "generate.py").read_text(encoding="utf-8")
    check(gsrc.count("COSMIC_FILLER_Q_RE = re.compile") == 0,
          "generate.py no longer defines its own copy")


# 10 ---------------------------------------------------------------------------
def test_10_visual_failure_is_distinguishable_from_provider_failure():
    """The chess run was reported as likely quota exhaustion while Gemini worked.

    Classification now comes from the shared predicate itself, never from
    brittle parsing of validate()'s human-readable error text.
    """
    scenes = [
        {"search_query": "galaxy stars space",
         "voiceover": "After four moves the board holds billions of arrangements."},
        {"search_query": "human anatomy",
         "voiceover": "A person lifts a hand."},
    ]
    for i, scene in enumerate(scenes, 1):
        err, code = G._visual_query_failure(scene, i, {"domain": "mathematics"})
        check(bool(err) and str(code).startswith("visual_intent:"),
              f"shared predicate classifies visual failure precisely ({code!r})")

    # Non-visual validator errors cannot acquire a visual defect code merely
    # because their prose happens to contain words such as "scene" or "hook".
    clean_scene = {"search_query": "chess board",
                   "voiceover": "A chess board can hold many different positions."}
    err, code = G._visual_query_failure(clean_scene, 1, {"domain": "mathematics"})
    check(err is None and code is None,
          "clean retrieval metadata is not mislabelled as visual failure")




# 11 ---------------------------------------------------------------------------
def test_11_subject_builder_preserves_the_pr88_stopword_floor():
    """Shared extraction must not re-admit glue words #88 already filtered."""
    cases = [
        ("octopus", "Because an octopus can squeeze through a tiny opening.", "octopus squeeze"),
        ("roots", "Water moves through roots before rising into the tree.", "roots rising"),
        ("shark", "A shark can live around ice for centuries.", "shark centuries"),
    ]
    banned = {"because", "through", "around", "before", "after", "during",
              "within", "without", "while", "since", "until"}
    for subject, voice, _label in cases:
        q = V.subject_led_query(subject, voice, {})
        tail = set(q.lower().split()) - set(subject.lower().split())
        check(not (tail & banned),
              f"{subject}: glue words never become retrieval discriminators ({q!r})")


# 12 ---------------------------------------------------------------------------
def test_12_visual_repair_is_idempotent():
    scenes = [{
        "search_query": "galaxy stars space",
        "voiceover": "After four moves the chessboard already has billions of arrangements.",
    }]
    first = V.repair_scene_queries(scenes, "chess", "math")
    after_first = copy.deepcopy(scenes)
    second = V.repair_scene_queries(scenes, "chess", "math")
    check(len(first) == 1, f"first pass repaired the defect ({first})")
    check(second == [], f"second pass is a no-op ({second})")
    check(scenes == after_first, "idempotent repair leaves the first repaired result byte-identical")


# 13 ---------------------------------------------------------------------------
def test_13_query_repair_cannot_hide_a_separate_content_defect():
    """Repairing disposable metadata never buys a pass for bad narration."""
    man = _load(CORPUS[0])
    man["scenes"][0]["search_query"] = "galaxy stars space"
    man["hook"] = "Too short"  # independent existing content gate, checked before scenes
    V.repair_scene_queries(man["scenes"], man.get("keyword", ""), G._domain_family(man.get("domain")))
    err = G.validate(man, man.get("viewer_job") or "CURIOSITY_ITCH")
    check(err is not None, "a separate content defect still fails after query-only repair")
    check("hook length" in err,
          f"the remaining failure is the narration/content defect, not silently cleared ({err!r})")


# 14 ---------------------------------------------------------------------------
def test_14_validate_consumes_the_shared_predicate_not_private_regex_logic():
    """One contract means validate's decision cannot drift from query_defect."""
    src = (ROOT / "generate.py").read_text(encoding="utf-8")
    check('UNSTOCKABLE_Q.search(s["search_query"])' not in src,
          "validate no longer hand-implements the unstockable predicate")
    check('COSMIC_FILLER_Q_RE.search(s["search_query"])' not in src,
          "validate no longer hand-implements the cosmic predicate")
    check("_visual_query_failure(s, i, fact)" in src,
          "validate delegates visual-query decisions through the shared predicate adapter")

    man = _load(CORPUS[0])
    man["scenes"][0]["search_query"] = "galaxy stars space"
    # Keep the line non-space so the shared predicate must reject.
    man["scenes"][0]["voiceover"] = "A shape-memory wire changes form when it warms."
    expected, code = G._visual_query_failure(man["scenes"][0], 1, {"domain": "materials"})
    check(code == V.DEFECT_COSMIC_FILLER, f"shared predicate classifies cosmic filler ({code})")
    got = G.validate(man, man.get("viewer_job") or "CURIOSITY_ITCH", fact={"domain": "materials"})
    check(got == expected, f"validate surfaces the shared predicate's exact decision ({got!r})")


# 15 ---------------------------------------------------------------------------
def test_15_terminal_failure_reporting_is_honest_and_load_bearing():
    """No-manifest is not synonymous with provider/quota exhaustion."""
    G._generation_failure_kinds.clear()
    G._record_generation_failure("visual_intent")
    msg = G._terminal_generation_failure_message()
    check("visual_intent" in msg, f"observed visual failure reaches terminal diagnosis ({msg!r})")
    check("likely LLM quota exhausted" not in msg,
          "terminal failure no longer makes the disproven quota inference")
    check("NOT inferred" in msg, "terminal text explicitly refuses the unsupported provider inference")
    G._generation_failure_kinds.clear()


# 16 ---------------------------------------------------------------------------
def test_16_near_miss_cannot_escape_to_generic_variety_wallpaper():
    """The last-resort path must use the same fail-closed visual contract."""
    src = (ROOT / "generate.py").read_text(encoding="utf-8")
    check('pool = (chosen_fact.get("queries", []) if chosen_fact else []) + VARIETY_QUERIES' not in src,
          "near-miss visual repair no longer selects from the generic variety pool")
    near = src.split("if not manifest and near_miss is not None:", 1)[1]
    check("repair_scene_queries(" in near,
          "near-miss path routes defective queries through the shared repair contract")

    scenes = [{"search_query": "galaxy stars space", "voiceover": "It is there."}]
    before = copy.deepcopy(scenes)
    changed = V.repair_scene_queries(scenes, "", "math")
    check(changed == [] and scenes == before,
          "an unrecoverable visual query remains defective instead of becoming generic wallpaper")


if __name__ == "__main__":
    test_1_good_queries_are_never_gratuitously_rewritten()
    test_2_cosmic_filler_on_a_non_space_scene_is_repaired()
    test_3_a_literal_astronomy_scene_may_still_use_space_words()
    test_4_metaphor_words_never_become_the_visual_subject()
    test_5_repair_touches_only_search_query()
    test_6_unrepairable_scene_keeps_its_query_and_still_fails()
    test_7_no_topic_specific_conditionals()
    test_8_abstract_topics_are_not_categorically_rejected()
    test_9_one_contract_not_two()
    test_10_visual_failure_is_distinguishable_from_provider_failure()
    test_11_subject_builder_preserves_the_pr88_stopword_floor()
    test_12_visual_repair_is_idempotent()
    test_13_query_repair_cannot_hide_a_separate_content_defect()
    test_14_validate_consumes_the_shared_predicate_not_private_regex_logic()
    test_15_terminal_failure_reporting_is_honest_and_load_bearing()
    test_16_near_miss_cannot_escape_to_generic_variety_wallpaper()
    print("visual intent contract tests: PASS")
