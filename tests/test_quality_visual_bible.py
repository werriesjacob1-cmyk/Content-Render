#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_visual_bible as V


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label)


def manifest():
    return {
        "treatment": "HIDDEN_MECHANISM",
        "scenes": [
            {"id": 1, "_v2_role": "hook", "voiceover": "A shark can live for centuries.", "search_query": "Greenland shark swimming"},
            {"id": 2, "_v2_role": "beat", "voiceover": "Inside its eye, a process slows damage.", "search_query": "Greenland shark eye"},
            {"id": 3, "_v2_role": "beat", "voiceover": "That process causes tissue to stay stable longer.", "search_query": "Greenland shark eye"},
            {"id": 4, "_v2_role": "payoff", "voiceover": "Some individuals were alive before modern nations existed.", "search_query": "Greenland shark close up"},
        ],
    }


def test_hook_and_payoff_intents_are_load_bearing():
    bible = V.build_visual_bible(manifest())
    check(bible.scenes[0].intent == "hook_proof", "hook receives literal proof intent")
    check(bible.scenes[-1].intent == "payoff_proof", "payoff receives proof/reframe intent")


def test_repeated_subject_gets_continuity_link():
    bible = V.build_visual_bible(manifest())
    eye = [x for x in bible.scenes if x.subject == "Greenland shark eye"]
    check(len(eye) == 2, "repeated exact subject recognized")
    check(eye[1].continuity_with == (eye[0].scene_id,), "later repeated subject explicitly links to prior representation")
    check(eye[0].subject_id == eye[1].subject_id, "stable subject ID survives scenes")


def test_scale_and_process_intents_are_deterministic():
    m = {"scenes": [
        {"id": 1, "voiceover": "A normal cell fits on this reference.", "search_query": "cell"},
        {"id": 2, "voiceover": "This structure is one million times larger in scale.", "search_query": "cell scale comparison"},
        {"id": 3, "voiceover": "Material flows through the process because pressure moves it.", "search_query": "cell process"},
    ]}
    bible = V.build_visual_bible(m)
    check(bible.scenes[1].intent in {"compare", "establish_scale"}, "scale scene cannot fall to generic demonstrate intent")
    check(bible.scenes[2].intent == "payoff_proof", "final scene remains payoff proof even if process wording appears")


def test_visual_bible_contains_anti_metaphor_and_typography_rules():
    bible = V.build_visual_bible(manifest())
    check("never rely on provider-baked" in bible.typography_rule, "typography remains renderer-owned")
    check(all(any("metaphorical" in x for x in s.avoid) for s in bible.scenes), "every scene rejects metaphor substitution")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]:
        fn()
    print("quality_visual_bible tests: PASS")
