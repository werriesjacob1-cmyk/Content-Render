#!/usr/bin/env python3
"""Zero-network: the final-QA verdict is found even when the reply's first part is prose (run 466)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")
import main as M

V = '{"footage_matches_narration": 7, "visual_variety": 6, "caption_legible": 9, "narration_flow": 8, "biggest_issue": "none"}'


def reply(*texts, thought_first=False):
    return {"candidates": [{"content": {"parts": [{"text": t} for t in texts]}}]}


def test_plain_json():
    assert M._extract_qa_verdict(reply(V))["footage_matches_narration"] == 7
    print("PASS plain JSON reply")


def test_prose_first_part_then_json():
    r = reply("The user wants an evaluation of a short-form science video based on 8 frames.", V)
    assert M._extract_qa_verdict(r)["narration_flow"] == 8
    print("PASS prose first part, JSON in a later part (run 466)")


def test_fenced_and_inline_prose():
    r = reply("- Frame 1: dust (good)\n- Frame 2: bright\n```json\n" + V + "\n```")
    assert M._extract_qa_verdict(r)["visual_variety"] == 6
    print("PASS fenced JSON after bullet prose")


def test_thought_parts_are_ignored_and_no_json_raises():
    r = {"candidates": [{"content": {"parts": [{"text": '{"footage_matches_narration": 1}', "thought": True}, {"text": V}]}}]}
    assert M._extract_qa_verdict(r)["footage_matches_narration"] == 7
    try:
        M._extract_qa_verdict(reply("only prose here"))
    except ValueError:
        print("PASS a thought part is ignored; a reply with no verdict still raises")
        return
    raise AssertionError("expected ValueError")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("ALL PASS")
