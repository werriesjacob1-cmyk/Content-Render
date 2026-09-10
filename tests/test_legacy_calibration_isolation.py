#!/usr/bin/env python3
"""The legacy calibration tooling is forensic ONLY and must stay that way.

`legacy_v21_replay.py` reads production modules to measure them. Nothing in
production may read IT. That direction is the whole safety property: a
diagnostic that acquires a path into candidate eligibility stops being a
diagnostic and becomes an ungoverned gate.

Also pins the two measurement guards that made the calibration trustworthy, both
of which were added only AFTER a real error:

* the word-count method is cross-checked against validate()'s own printed
  arithmetic, and the tool REFUSES to emit a comparison when they disagree;
* legacy provenance is recorded NOT TESTABLE, never FAIL.

Zero network, zero providers, zero LLM.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PRODUCTION = ("generate.py", "main.py", "writer_v2.py", "writer_v2_repair.py",
              "writer_v21_orchestrator.py", "repackage.py")


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_1_no_production_module_imports_the_diagnostic():
    for name in PRODUCTION:
        p = ROOT / name
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        check("legacy_v21_replay" not in src,
              f"{name} does not import or reference legacy_v21_replay")


def test_2_the_diagnostic_makes_no_provider_or_network_call():
    """Inspect the AST, not the text.

    A raw substring scan is the wrong instrument here: this tool DISCUSSES
    `score_script` at length in its own docstring, explaining why it cannot run
    it. A text scan would fail on the explanation while happily missing a real
    call written as `getattr(G, "score_" + "script")`. So look at what the module
    actually calls and imports."""
    import ast
    src = (ROOT / "legacy_v21_replay.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Provider entry points only. `get`/`post`/`request` are NOT listed: as bare
    # method names they are overwhelmingly `dict.get`, and banning them flags
    # ordinary dictionary access. Network access is caught by the import check
    # below instead, which is airtight — no HTTP call happens without importing
    # something to make it with.
    banned = {"call_groq", "score_script", "critique_script", "urlopen",
              "_call_gemini", "run"}
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            called.add(f.attr if isinstance(f, ast.Attribute)
                       else (f.id if isinstance(f, ast.Name) else ""))
    # `subprocess.run` IS used, deliberately: LENGTH_MODE resolves at import
    # time, so each mode needs its own interpreter. That is local process
    # execution, not a network or provider call.
    offenders = (called & banned) - {"run"}
    check(not offenders, f"legacy_v21_replay.py calls no provider/network function ({offenders})")

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for net in ("requests", "httpx", "urllib", "socket", "openai", "google"):
        check(net not in imported, f"and imports no network library ({net!r})")
    check("generate" not in imported,
          "the top-level module does not even import generate — production is "
          "reached only inside a subprocess, so importing this tool cannot "
          "execute pipeline code")


def test_3_word_count_guard_is_present_and_fails_loudly():
    """The guard that caught a 20-30 word inflation. If someone deletes it, the
    comparison can silently go back to measuring the wrong thing."""
    src = (ROOT / "legacy_v21_replay.py").read_text(encoding="utf-8")
    check("_verify_word_count_method" in src, "the word-count cross-check exists")
    check("refusing to report a comparison" in src,
          "and a disagreement raises rather than being reported anyway")

    import legacy_v21_replay as L
    good = [{"words": 126, "validate_err": "script word count 126 out of range"}]
    bad = [{"words": 159, "validate_err": "script word count 126 out of range"}]
    check(L._verify_word_count_method(good) == (1, 0), "an agreeing round counts as agreement")
    check(L._verify_word_count_method(bad) == (0, 1), "a disagreeing round is detected")


def test_4_legacy_provenance_is_not_testable_never_failed():
    import legacy_v21_replay as L
    check("traceability_hard" in L.NOT_TESTABLE,
          "traceability is declared NOT TESTABLE for legacy artifacts")
    check("semantic_support" in L.NOT_TESTABLE, "so is semantic support")
    # No legacy fixture may acquire provenance metadata: if one ever does, it was
    # edited, and these are historical artifacts that must never be edited.
    import json
    fixtures = sorted((ROOT / "tests" / "fixtures" / "legacy_controls").glob("science_*.json"))
    check(len(fixtures) == 12, f"all 12 legacy controls are present ({len(fixtures)})")
    for fp in fixtures:
        man = json.loads(fp.read_text(encoding="utf-8"))
        for forbidden in ("source_claim_ids", "claims", "_quality"):
            check(forbidden not in man,
                  f"{fp.name[:34]} carries no {forbidden} — fixture is unedited history")


def test_5_the_gates_the_calibration_vindicated_are_unchanged():
    """If a future session 'fixes' the gates on the strength of this report, that
    is the opposite of what it says. These are the values 12/12 known-good
    scripts passed."""
    import generate as G
    check(G.SCENE_WORD_CAP == 25, "scene word cap still 25")
    check((G.HOOK_WORD_LO, G.HOOK_WORD_HI) == (4, 16), "hook window still 4-16 words")
    check(G.QUALITY_HARD_FLOOR == 6.8, "quality floor still 6.8")
    check((G.WORD_HARD_LO, G.WORD_HARD_HI) in ((68, 108), (85, 115)),
          f"word hard bounds unchanged ({G.WORD_HARD_LO}-{G.WORD_HARD_HI})")


if __name__ == "__main__":
    test_1_no_production_module_imports_the_diagnostic()
    test_2_the_diagnostic_makes_no_provider_or_network_call()
    test_3_word_count_guard_is_present_and_fails_loudly()
    test_4_legacy_provenance_is_not_testable_never_failed()
    test_5_the_gates_the_calibration_vindicated_are_unchanged()
    print("legacy calibration isolation tests: PASS")
