#!/usr/bin/env python3
"""Offline, zero-provider replay of the real flagship Writer rejection corpus.

Flagship certification runs #2-#5 all died at the Writer stage, and every one
of them uploaded its per-round debug as an Actions artifact. Those artifacts are
preserved verbatim under ``tests/fixtures/writer_corpus/``. This module replays
them so a Writer/prompt/repair change can be evaluated at $0 instead of costing
a paid Gemini run per experiment -- which is the reason this class of bug
survived four flagship attempts.

It never calls a provider and never renders. It reads what the Writer actually
produced, classifies why each round was rejected, and reports what a proposed
repair policy WOULD have done with the same rounds.

CLI:  python writer_replay.py            # failure matrix + summary
      python writer_replay.py --json     # machine-readable
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "tests", "fixtures", "writer_corpus")

# --- defect taxonomy -------------------------------------------------------
# Each entry: (family, regex). Order matters -- first match wins.
_FAMILIES = (
    ("total_word_count", re.compile(r"^script word count (\d+) out of range")),
    ("scene_word_cap", re.compile(r"^scene (\d+) voiceover too long \((\d+) words")),
    ("hook_length", re.compile(r"^hook length (\d+) words out of range")),
    ("hook_is_question", re.compile(r"^hook .* is phrased a")),
    ("repetition", re.compile(r"too similar \(repetition\)")),
    ("fact_restated", re.compile(r"^the verified fact is restated in")),
    ("formal_connector", re.compile(r"uses the formal connector")),
    ("key_terms_missing", re.compile(r"mandatory key terms named")),
    ("headline_echo", re.compile(r"^hook_headline .* is nearly identical")),
    ("stacked_clause", re.compile(r"^scene \d+ voiceover '.*while")),
)

# Families that are pure length/format arithmetic. These are exactly the class
# the deterministic mechanical trim can fix with zero network calls -- and
# exactly the class the writer prompt failed to state a budget for.
MECHANICAL_FAMILIES = frozenset({"total_word_count", "scene_word_cap", "hook_length"})

# Families that are craft/storytelling defects: real writing problems that a
# length trim can never fix and that need either a better prompt or a craft
# repair round.
CRAFT_FAMILIES = frozenset({
    "repetition", "fact_restated", "hook_is_question", "formal_connector",
    "headline_echo", "stacked_clause",
})


def classify_validate_err(validate_err):
    """Pure. Map a validate() rejection string to a defect family + magnitude."""
    text = (validate_err or "").strip()
    if not text:
        return {"family": None, "detail": None, "overage": 0}
    for family, rx in _FAMILIES:
        m = rx.search(text)
        if not m:
            continue
        overage = 0
        if family == "total_word_count":
            hard = re.search(r"hard \d+-(\d+)", text)
            if hard:
                overage = max(0, int(m.group(1)) - int(hard.group(1)))
        elif family == "scene_word_cap":
            cap = re.search(r"cap is (\d+)", text)
            if cap:
                overage = max(0, int(m.group(2)) - int(cap.group(1)))
        return {"family": family, "detail": text[:120], "overage": overage}
    return {"family": "other", "detail": text[:120], "overage": 0}


def tier1_clean(rnd):
    """Pure. True when no factual/provenance/semantic blocker remains in a round.

    This is the precondition the deterministic mechanical trim requires: it must
    never rewrite narration while a real factual problem is still unresolved,
    because trimming can delete the very text a provenance repair would fix.
    """
    return (
        int(rnd.get("mechanical_hard_count") or 0) == 0
        and int(rnd.get("semantic_violation_count") or 0) == 0
        and bool(rnd.get("semantic_verified"))
    )


def replay_attempt(attempt, max_repair_rounds=2):
    """Pure. Replay one recorded candidate attempt and describe what happened,
    plus what a terminal mechanical-salvage policy WOULD have changed.

    Baseline policy (shipped): the loop breaks the moment round_idx reaches
    MAX_REPAIR_ROUNDS, BEFORE any trim is attempted -- so a candidate whose only
    remaining blocker on its final round is pure length arithmetic is discarded
    even though a zero-network fix was sitting right there.
    """
    rounds = list(attempt.get("rounds") or [])
    out = {
        "treatment": attempt.get("treatment"),
        "accepted": bool(attempt.get("accepted")),
        "round_count": len(rounds),
        "rounds": [],
        "trims_applied": 0,
        "terminal_family": None,
        "terminal_tier1_clean": False,
        "salvageable_by_terminal_trim": False,
    }
    for rnd in rounds:
        cls = classify_validate_err(rnd.get("validate_err"))
        row = {
            "round": rnd.get("round"),
            "family": cls["family"],
            "overage": cls["overage"],
            "tier1_clean": tier1_clean(rnd),
            "mech_hard": int(rnd.get("mechanical_hard_count") or 0),
            "sem_viol": int(rnd.get("semantic_violation_count") or 0),
            "trim_applied": bool(rnd.get("mechanical_trim_applied")),
            "critic_avg": rnd.get("critic_avg"),
        }
        out["trims_applied"] += 1 if row["trim_applied"] else 0
        out["rounds"].append(row)

    if out["rounds"]:
        last = out["rounds"][-1]
        out["terminal_family"] = last["family"]
        out["terminal_tier1_clean"] = last["tier1_clean"]
        # A terminal salvage only helps when the final round was blocked SOLELY
        # by length arithmetic and nothing factual was outstanding.
        out["salvageable_by_terminal_trim"] = bool(
            last["family"] in MECHANICAL_FAMILIES
            and last["tier1_clean"]
            and out["round_count"] > max_repair_rounds
        )
    return out


def load_corpus(corpus_dir=CORPUS_DIR, only=None):
    """`only` = an iterable of fixture filenames to restrict the load to.

    The corpus grows every flagship, but a measurement is only ever about the
    runs it was taken over. Restricting by filename lets a historical result
    stay pinned to the exact fixtures that produced it instead of drifting --
    or being renumbered -- each time a new run is added.
    """
    keep = set(only) if only is not None else None
    fixtures = []
    for path in sorted(glob.glob(os.path.join(corpus_dir, "flagship_*.json"))):
        name = os.path.basename(path)
        if keep is not None and name not in keep:
            continue
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["_file"] = name
        fixtures.append(data)
    return fixtures


# The fixtures the 2026-09-08 Writer diagnosis was measured over. Pinned by
# name so adding run 06 (or 07...) cannot silently restate that result.
HISTORICAL_BASELINE_FIXTURES = (
    "flagship_02_2dbad04.json",
    "flagship_03_4b7584c.json",
    "flagship_04_39275e3.json",
    "flagship_05_240bdc1.json",
)


def replay_corpus(corpus_dir=CORPUS_DIR, only=None):
    fixtures = load_corpus(corpus_dir, only=only)
    families, rows = {}, []
    totals = {
        "fixtures": len(fixtures), "attempts": 0, "rounds": 0,
        "mechanical_rounds": 0, "craft_rounds": 0,
        "trims_applied": 0, "salvageable_attempts": 0,
        "rounds_blocked_only_by_length": 0,
    }
    for fx in fixtures:
        for attempt in fx.get("attempts") or []:
            rep = replay_attempt(attempt)
            totals["attempts"] += 1
            totals["rounds"] += rep["round_count"]
            totals["trims_applied"] += rep["trims_applied"]
            totals["salvageable_attempts"] += 1 if rep["salvageable_by_terminal_trim"] else 0
            for row in rep["rounds"]:
                fam = row["family"]
                if fam:
                    families[fam] = families.get(fam, 0) + 1
                if fam in MECHANICAL_FAMILIES:
                    totals["mechanical_rounds"] += 1
                    if row["tier1_clean"]:
                        totals["rounds_blocked_only_by_length"] += 1
                elif fam in CRAFT_FAMILIES:
                    totals["craft_rounds"] += 1
            rows.append({"fixture": fx["_file"], "attempt": attempt.get("attempt"), **rep})
    return {"totals": totals, "families": families, "attempts": rows}


def _main(argv):
    result = replay_corpus()
    if "--json" in argv:
        print(json.dumps(result, indent=2))
        return 0
    t, fams = result["totals"], result["families"]
    print("=" * 72)
    print("WRITER REJECTION CORPUS REPLAY (zero provider calls)")
    print("=" * 72)
    print(f"fixtures={t['fixtures']}  attempts={t['attempts']}  rounds={t['rounds']}")
    print()
    print("defect families (by round):")
    for fam, n in sorted(fams.items(), key=lambda kv: -kv[1]):
        kind = ("MECHANICAL" if fam in MECHANICAL_FAMILIES
                else "CRAFT" if fam in CRAFT_FAMILIES else "other")
        pct = 100.0 * n / max(1, t["rounds"])
        print(f"  {n:>3}  ({pct:4.1f}%)  {fam:<20} [{kind}]")
    print()
    print(f"rounds blocked by pure length arithmetic : {t['mechanical_rounds']}"
          f" ({100.0 * t['mechanical_rounds'] / max(1, t['rounds']):.1f}%)")
    print(f"  ...of those, Tier-1 already clean      : {t['rounds_blocked_only_by_length']}"
          f"   <- zero-network trim could fix these")
    print(f"rounds blocked by craft defects          : {t['craft_rounds']}")
    print(f"mechanical trims actually applied        : {t['trims_applied']}")
    print(f"attempts a TERMINAL salvage would rescue : {t['salvageable_attempts']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
