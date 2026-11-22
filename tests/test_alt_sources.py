#!/usr/bin/env python3
"""Zero-network: a weak primary-source result must also consult NASA/archive sources."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")
import main as M


def test_weak_primary_falls_to_alt_source():
    accepted = []
    M._gather_candidates = lambda q: [{"id": "px1", "url": "u", "desc": "party balloons", "source": "Pexels"}]
    M._alt_candidates = lambda q: [{"id": "nasa1", "url": "u2", "desc": "Cassini infrared Saturn rings", "source": "NASA"}]
    M._best_keyword_match = lambda q, c: 0 if c and c[0]["id"] == "nasa1" else None
    M._gemini_vision_pick = lambda i, c: (0, 2)
    M._groq_judge = lambda i, c: (0, 2)
    M._groq_requery = lambda i, q: []
    M._accept = lambda c, dest, q, sc: accepted.append(c["id"])
    ok, _ = M.fetch_clip("saturn planet rings", "/tmp/x.mp4")
    assert ok and accepted == ["nasa1"], (ok, accepted)
    print("PASS weak Pexels result is rescued by a NASA candidate")


def test_alt_sources_can_be_disabled():
    accepted = []
    os.environ["ALT_SOURCES_ON_WEAK"] = "0"
    M._best_keyword_match = lambda q, c: None
    M._accept = lambda c, dest, q, sc: accepted.append(c["id"])
    ok, _ = M.fetch_clip("saturn planet rings", "/tmp/x.mp4")
    os.environ.pop("ALT_SOURCES_ON_WEAK")
    assert not ok and not accepted
    print("PASS ALT_SOURCES_ON_WEAK=0 restores the old behaviour")


if __name__ == "__main__":
    test_weak_primary_falls_to_alt_source()
    test_alt_sources_can_be_disabled()
    print("ALL PASS")
