"""Curiosity gate: decide whether a bank fact forces a mental-model update BEFORE
the writer ever sees it (pure, zero-network).

The research the user asked us to act on (moderate knowledge gap; a minimal,
specific violation of an intuitive expectation; a satisfying mechanism) points at
the premise, not the polish: a perfectly graded video about "this thing is
extremely large" is still a boring fact. This scorer reads a fact's own text and
flags (a) facts whose ONLY strength is magnitude and (b) facts with no
mechanism or expectation violation at all.

It is deliberately a transparent heuristic, not a model: every point is traceable
to words in the fact, so a reviewer can disagree with it. An LLM scorer can be
layered on later; the verdict file format is the same.

  score 0-8 (higher = stronger premise)   verdict: keep | weak | reject
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SCORES_PATH = os.path.join(ROOT, "curiosity_scores.json")

# the fact states the opposite of what a viewer assumes
_VIOLATION = re.compile(
    r"\b(actually|not a|isn'?t|aren'?t|doesn'?t|don'?t|can'?t|never|instead|rather than|"
    r"even though|despite|opposite|backwards?|wrong|myth|misconception|still|yet|"
    r"only|without|no longer|survives?|reverses?)\b", re.I)
# a causal "why/how"
_MECHANISM = re.compile(
    r"\b(because|so that|which is why|that'?s why|this is why|by (?:\w+ing)|"
    r"when|as the|caused by|due to|thanks to|results? in|turns? into|converts?|"
    r"rebuilds?|replaces?|pressure|heat|gravity|chemical|enzyme|cells?|molecules?|"
    r"light|waves?|electric\w*|magnetic|proteins?|acid|oxygen|carbon|dna)\b", re.I)
# the premise is a number being big / small / old / far
_MAGNITUDE = re.compile(
    r"\b(million|billion|trillion|thousand|largest|biggest|smallest|tiniest|heaviest|"
    r"tallest|oldest|fastest|slowest|hottest|coldest|densest|enormous|massive|huge|tiny|"
    r"vast|infinite|incredibly|extremely|times (?:bigger|larger|smaller|heavier|faster|"
    r"more|longer)|light[- ]years?|miles? (?:wide|long|across)|km)\b", re.I)
_NUMBER = re.compile(r"\b\d[\d,\.]*\b")
# attachable to something the viewer owns, does or sees
_RELATABLE = re.compile(
    r"\b(you|your|you'?re|human|body|skin|eyes?|brain|blood|stomach|hair|sleep|"
    r"morning|kitchen|water|phone|tree|dog|cat|banana|salt|coffee|rain|rainbow|sky)\b", re.I)
_VISUAL = re.compile(
    r"\b(see|look|watch|glow|shine|colou?r|shape|circle|spiral|flow|grow|melt|freeze|"
    r"burst|spin|fall|float|swim|fly|crack|bend|reflect|shadow)\w*\b", re.I)

KEEP_AT_LEAST = 5


def score_fact(f):
    """(score, notes) for one bank fact. Reads only the fact's own text fields."""
    text = " ".join(str(f.get(k, "")) for k in ("fact", "angle"))
    extra = " ".join(str(f.get(k, "")) for k in ("whatif", "wow"))
    notes, s = [], 0
    v = len(_VIOLATION.findall(text))
    if v:
        s += 2 if v >= 2 else 1; notes.append(f"expectation-violation x{v}")
    m = len(_MECHANISM.findall(text + " " + extra))
    if m:
        s += 2 if m >= 2 else 1; notes.append(f"mechanism x{m}")
    if _RELATABLE.search(text):
        s += 1; notes.append("relatable")
    if _VISUAL.search(text + " " + extra):
        s += 1; notes.append("visualisable")
    if str(f.get("whatif", "")).strip().endswith("?") or "?" in str(f.get("whatif", "")):
        s += 1; notes.append("open question")
    # magnitude-only: lots of big/small/number language and NO mechanism or violation
    mag = len(_MAGNITUDE.findall(text)) + (1 if len(_NUMBER.findall(text)) >= 3 else 0)
    if mag >= 2 and not (v or m):
        s = min(s, 1); notes.append("MAGNITUDE-ONLY")
    elif mag >= 3 and not m:
        s -= 1; notes.append("magnitude-heavy, no mechanism")
    return max(0, min(8, s)), notes


def verdict(score, notes=()):
    """reject ONLY on the explicit magnitude-only finding. A low score alone is NOT a
    rejection: replayed over the real bank, a plain score cutoff threw out good
    premises (atoms_empty, birthday_paradox, flavor_is_mostly_smell) because a
    keyword heuristic cannot see a mechanism it has no word for. The score is for
    RANKING; rejection needs the specific, explainable failure."""
    if "MAGNITUDE-ONLY" in notes:
        return "reject"
    return "keep" if score >= KEEP_AT_LEAST else "weak"


def rank(bank):
    out = []
    for f in bank:
        s, n = score_fact(f)
        out.append({"id": f.get("id"), "domain": f.get("domain"), "score": s,
                    "verdict": verdict(s, n), "notes": n})
    return sorted(out, key=lambda r: -r["score"])


def rejected_ids(path=SCORES_PATH):
    """IDs the committed score file marks 'reject'. Fail-open: a missing/corrupt
    file rejects nothing, so deleting it restores the old selector."""
    try:
        with open(path) as fh:
            data = json.load(fh)
        return {r["id"] for r in data.get("scores", []) if r.get("verdict") == "reject" and r.get("id")}
    except Exception:  # noqa: BLE001
        return set()


def main(argv=None):
    bank = json.load(open(os.path.join(ROOT, "topic_bank.json"))).get("facts", [])
    ranked = rank(bank)
    if argv and "--write" in argv:
        json.dump({"note": "heuristic curiosity scores; see curiosity_gate.py",
                   "scores": ranked},
                  open(SCORES_PATH, "w"), indent=1)
    counts = {v: sum(1 for r in ranked if r["verdict"] == v) for v in ("keep", "weak", "reject")}
    print(counts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
