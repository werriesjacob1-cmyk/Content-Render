#!/usr/bin/env python3
"""Replay real August legacy scripts through the CURRENT deterministic gate stack.

THE QUESTION THIS ANSWERS

Twelve science videos rendered and scored 7.0-8.29 in August 2026 under the
legacy Writer. The Writer V2.1 certification path has never cleared the 6.8
floor. Two incompatible explanations:

  A. the gate stack drifted and now rejects scripts we already know work;
  B. the gates are reasonable and the V2.1 Writer produces worse scripts.

The only way to separate them at $0 is to feed the EXACT preserved narration of
the known-good videos through today's deterministic gates and see what happens.

WHAT THIS IS NOT

Zero LLM calls, zero network, zero providers. It therefore covers ONLY the
deterministic layer: `generate.validate()` plus the length contract. It cannot
and does not evaluate `score_script` (an LLM rubric call), the semantic support
critic, or information gain. Those need a provider and are out of scope here.

That limit is the point rather than a shortcoming: the V2.1 orchestrator scores
a candidate only when validate() already passed
(`writer_v21_orchestrator.py:161`: `score = None if validate_err else
G.score_script(...)`). So the deterministic layer decides whether a script
REACHES the scorer at all, and that is precisely what is being measured.

FAIRNESS RULES (these are load-bearing -- see reports/LEGACY_V21_CALIBRATION*.md)

* The narration is used byte-for-byte as committed. Nothing is rewritten,
  retrimmed or modernised to help it pass.
* Legacy manifests carry NO provenance metadata -- no `source_claim_ids`, no
  claim inventory, not even a `fact_id`. Traceability and semantic-support gates
  are therefore recorded NOT TESTABLE, never FAIL. Absent metadata is not
  evidence that a sentence was unsupported.
* `LENGTH_MODE` is an import-time switch, and the August renders alternated
  between short and long. Judging every legacy script against ONE mode would
  manufacture failures, so each script is replayed under BOTH and credited if
  either mode accepts it -- which is what the live pipeline would have done.
* The fact record comes from `memory_science.json` -> `topic_bank.json`, both
  committed contemporaneously. Nothing is researched from the web today and
  back-dated into the evidence.

Usage:  python legacy_v21_replay.py            (writes the report + JSON matrix)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "tests" / "fixtures" / "legacy_controls"
OUT_JSON = ROOT / "reports" / "legacy_v21_gate_matrix.json"

# Gates that cannot be evaluated without V2.1-era metadata the legacy manifests
# never carried. Recorded, never counted as failures.
NOT_TESTABLE = {
    "traceability_hard": "legacy manifests carry no source_claim_ids or claim inventory",
    "semantic_support": "requires the LLM critic and a claim inventory; neither exists here",
    "information_gain": "LLM call; excluded by the zero-provider constraint",
    "score_script": "LLM rubric call; excluded by the zero-provider constraint",
}


def _load_controls():
    index = json.loads((FIXTURES / "INDEX.json").read_text(encoding="utf-8"))
    bank = json.loads((ROOT / "topic_bank.json").read_text(encoding="utf-8"))
    items = bank if isinstance(bank, list) else (bank.get("facts") or bank.get("topics") or [])
    by_id = {f.get("id"): f for f in items}
    out = []
    for row in index:
        if not row.get("found"):
            continue
        man = json.loads((FIXTURES / f"{row['video_id']}.json").read_text(encoding="utf-8"))
        out.append({
            "video_id": row["video_id"],
            "fact_id": row["fact_id"],
            "stored_quality_overall": row["stored_quality_overall"],
            "manifest_commit_sha": row["manifest_commit_sha"],
            "manifest_commit_date": row["manifest_commit_date"],
            "manifest": man,
            # A fact_id with no bank entry means the fact was retired from the
            # bank after the render. Report that honestly rather than guessing.
            "fact": by_id.get(row["fact_id"]),
        })
    return out


def _replay_one_mode(mode):
    """Run validate() over every control in a SUBPROCESS pinned to one
    LENGTH_MODE. generate.py resolves the word window and scene bounds at import
    time, so the mode cannot be switched inside a single process."""
    code = r'''
import json, os, sys, copy
sys.path.insert(0, %(root)r)
os.environ.setdefault("GROQ_API_KEY", "x")
import generate as G
controls = json.loads(sys.stdin.read())
res = {}
for c in controls:
    m = copy.deepcopy(c["manifest"])          # validate() mutates its input
    job = m.get("viewer_job") or "MYTH_BUSTER"
    try:
        err = G.validate(m, job, fact=c["fact"])
    except Exception as e:                      # a crash is a result, not a pass
        err = "VALIDATE_CRASH: %%s: %%s" %% (type(e).__name__, e)
    res[c["video_id"]] = {
        "validate_err": err,
        "word_count": len((c["manifest"].get("script") or "").split()),
        "scene_count": len(c["manifest"].get("scenes") or []),
        "hook_words": len((c["manifest"].get("hook") or "").split()),
        "max_scene_words": max([len((s.get("voiceover") or "").split())
                                for s in (c["manifest"].get("scenes") or [])] or [0]),
        "cta_style": c["manifest"].get("cta_style"),
        "bounds": {"word_hard": [G.WORD_HARD_LO, G.WORD_HARD_HI],
                   "word_target": [G.WORD_LO, G.WORD_HI],
                   "scenes": [G.SCENE_MIN, G.SCENE_MAX],
                   "scene_word_cap": G.SCENE_WORD_CAP,
                   "hook_words": [G.HOOK_WORD_LO, G.HOOK_WORD_HI]},
    }
print(json.dumps(res))
''' % {"root": str(ROOT)}
    env = dict(os.environ, LENGTH_MODE=mode, GROQ_API_KEY="x")
    payload = json.dumps([{k: v for k, v in c.items()} for c in _load_controls()])
    p = subprocess.run([sys.executable, "-c", code], input=payload,
                       capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise SystemExit(f"replay subprocess failed for mode={mode}:\n{p.stderr[-3000:]}")
    return json.loads(p.stdout.strip().splitlines()[-1])


def _classify(err):
    """Bucket a validate() error string into the gate family that produced it.

    Deliberately coarse: the point is which KIND of requirement rejects a
    known-good script, not the exact wording."""
    if err is None:
        return None
    e = err.lower()
    for needle, family in (
        ("word count", "length:total_words"),
        ("scene count", "length:scene_count"),
        ("hook length", "length:hook_words"),
        ("voiceover too long", "length:per_scene_cap"),
        ("formal connector", "craft:formal_connector"),
        ("too similar (repetition)", "craft:repetition"),
        ("re-said as the crux", "craft:restated_fact"),
        ("restated in", "craft:restated_fact"),
        ("mandatory key terms", "content:key_terms"),
        ("whatif curiosity gap", "content:whatif_gap"),
        ("whatif payoff", "content:whatif_payoff"),
        ("too abstract", "hook:abstract"),
        ("dangling comparative", "hook:dangling_comparative"),
        ("phrased as a question", "hook:question"),
        ("banned wind-up", "hook:banned_opener"),
        ("falsely states a high-stakes", "hook:false_present_stakes[NEW since Aug]"),
        ("generic pseudo-payoff", "ending:generic_reframe_cliche[NEW since Aug]"),
        ("generic save-command", "ending:save_command"),
        ("hook_headline", "meta:hook_headline"),
        ("un-filmable terms", "footage:unstockable"),
        ("generic cosmic/space", "footage:generic_space"),
        ("unexplained jargon", "craft:jargon"),
        ("inverted", "craft:inverted_syntax"),
        ("comma-splices", "craft:comma_splice"),
        ("stacks a second named", "craft:entity_stacking"),
        ("contradictory numbers", "content:contradiction"),
        ("reference-worthy", "content:reference_worthy"),
        ("missing", "schema:missing_field"),
    ):
        if needle in e:
            return family
    return "other:" + err[:60]


def build_matrix():
    controls = _load_controls()
    short = _replay_one_mode("short")
    long_ = _replay_one_mode("long")
    rows = []
    for c in controls:
        s, l = short[c["video_id"]], long_[c["video_id"]]
        passes = [m for m, r in (("short", s), ("long", l)) if r["validate_err"] is None]
        rows.append({
            "video_id": c["video_id"],
            "fact_id": c["fact_id"],
            "fact_in_bank_today": c["fact"] is not None,
            "stored_quality_overall": c["stored_quality_overall"],
            "manifest_commit_sha": c["manifest_commit_sha"],
            "manifest_commit_date": c["manifest_commit_date"],
            "word_count": s["word_count"],
            "scene_count": s["scene_count"],
            "hook_words": s["hook_words"],
            "max_scene_words": s["max_scene_words"],
            "cta_style": s["cta_style"],
            "validate_err_short": s["validate_err"],
            "validate_err_long": l["validate_err"],
            "gate_family_short": _classify(s["validate_err"]),
            "gate_family_long": _classify(l["validate_err"]),
            "passes_modes": passes,
            "reaches_scorer": bool(passes),
            "provenance_testability": "NOT TESTABLE",
            "provenance_reason": NOT_TESTABLE["traceability_hard"],
        })
    return {
        "schema": "legacy-v21-calibration-v1",
        "bounds_short": short[controls[0]["video_id"]]["bounds"],
        "bounds_long": long_[controls[0]["video_id"]]["bounds"],
        "not_testable_gates": NOT_TESTABLE,
        "rows": rows,
    }


def render_report(matrix):
    rows = matrix["rows"]
    reached = [r for r in rows if r["reaches_scorer"]]
    out = []
    out.append("# Legacy -> V2.1 deterministic gate matrix\n")
    out.append(f"- controls: **{len(rows)}** real August renders, narration byte-for-byte as committed")
    out.append(f"- reach today's quality scorer: **{len(reached)}/{len(rows)}**")
    out.append(f"- short-mode bounds: {matrix['bounds_short']}")
    out.append(f"- long-mode bounds: {matrix['bounds_long']}\n")
    out.append("| video | stored score | words | scenes | passes under | reaches scorer | blocking gate (short / long) |")
    out.append("|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: -x["stored_quality_overall"]):
        modes = ", ".join(r["passes_modes"]) or "-"
        blk = f"{r['gate_family_short'] or 'PASS'} / {r['gate_family_long'] or 'PASS'}"
        out.append(f"| {r['video_id'][8:][:46]} | {r['stored_quality_overall']} | {r['word_count']} "
                   f"| {r['scene_count']} | {modes} | {'YES' if r['reaches_scorer'] else 'NO'} | {blk} |")
    fams = {}
    for r in rows:
        if not r["reaches_scorer"]:
            fams.setdefault(r["gate_family_long"] or "?", []).append(r["video_id"])
    out.append("\n## Blocking gate families (scripts blocked in BOTH modes)\n")
    if not fams:
        out.append("None -- every legacy control reaches the scorer under at least one length mode.")
    for fam, vids in sorted(fams.items(), key=lambda kv: -len(kv[1])):
        out.append(f"- **{fam}** — {len(vids)}: {', '.join(v[8:][:40] for v in vids)}")
    out.append("\n## Gates recorded NOT TESTABLE (never counted as failures)\n")
    for k, v in matrix["not_testable_gates"].items():
        out.append(f"- `{k}` — {v}")
    return "\n".join(out) + "\n"


CORPUS = ROOT / "tests" / "fixtures" / "writer_corpus"


def _v21_rounds():
    """Every preserved Writer V2.1 certification round, flagships 02-07.

    MEASUREMENT NOTE (this was wrong once, so it is pinned by
    `_verify_word_count_method` below). A round's `beats` list is the FULL
    spoken sequence: `beats[0]` IS the hook and `beats[-1]` IS the payoff, both
    also stored separately for convenience. Adding `hook` and `payoff` to the
    join double-counts them and inflates every word count by 20-30. Counting
    `beats` alone reproduces validate()'s own arithmetic exactly.
    """
    rounds = []
    for fp in sorted(CORPUS.glob("flagship_0*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        for att in data.get("attempts") or []:
            for r in att.get("rounds") or []:
                beats = r.get("beats") or []
                score = r.get("score")
                rounds.append({
                    "flagship": fp.stem,
                    "treatment": att.get("treatment"),
                    "words": len(" ".join(beats).split()),
                    "validate_err": r.get("validate_err"),
                    "gate_family": _classify(r.get("validate_err")),
                    "score_overall": (score.get("overall") if isinstance(score, dict) else score),
                })
    return rounds


def _verify_word_count_method(rounds):
    """Cross-check our word count against the number validate() itself printed.

    Any round whose validate_err names a word count gives us ground truth for
    free. If this ever disagrees, the comparison below is measuring the wrong
    thing and must not be reported."""
    import re
    agree = disagree = 0
    for r in rounds:
        m = re.search(r"script word count (\d+)", r["validate_err"] or "")
        if not m:
            continue
        agree, disagree = (agree + 1, disagree) if int(m.group(1)) == r["words"] \
            else (agree, disagree + 1)
    return agree, disagree


def render_comparison(matrix):
    import statistics
    rounds = _v21_rounds()
    agree, disagree = _verify_word_count_method(rounds)
    if disagree:
        raise SystemExit(f"word-count method disagrees with validate() on {disagree} rounds — "
                         f"refusing to report a comparison built on a bad measurement")
    legacy = [r["word_count"] for r in matrix["rows"]]
    v21 = [r["words"] for r in rounds]
    scored = [r["score_overall"] for r in rounds if r["score_overall"] is not None]
    legacy_scores = [r["stored_quality_overall"] for r in matrix["rows"]]

    o = ["\n## Head-to-head: known-good legacy vs Writer V2.1 certification\n",
         f"_word-count method cross-checked against validate()'s own arithmetic: "
         f"{agree} agree / {disagree} disagree._\n",
         "| | legacy controls | V2.1 rounds |",
         "|---|---|---|",
         f"| n | {len(legacy)} | {len(rounds)} |",
         f"| words median | {statistics.median(legacy)} | {statistics.median(v21)} |",
         f"| words range | {min(legacy)}-{max(legacy)} | {min(v21)}-{max(v21)} |",
         f"| over the 115 hard ceiling | {sum(1 for w in legacy if w > 115)} | "
         f"{sum(1 for w in v21 if w > 115)} |",
         f"| clears deterministic gates | {sum(1 for r in matrix['rows'] if r['reaches_scorer'])}"
         f"/{len(legacy)} | {sum(1 for r in rounds if r['validate_err'] is None)}/{len(rounds)} |",
         f"| score when it DOES reach the scorer | {min(legacy_scores)}-{max(legacy_scores)} | "
         f"{min(scored)}-{max(scored)} |",
         "\n### What blocks V2.1 rounds that are ALREADY a legal length\n",
         "If length were the binding constraint, these would pass.\n"]
    legal = {}
    for r in rounds:
        if 68 <= r["words"] <= 115:
            legal[r["gate_family"] or "PASS"] = legal.get(r["gate_family"] or "PASS", 0) + 1
    o.append(f"Of {sum(legal.values())} rounds inside a legal word window:\n")
    for k, v in sorted(legal.items(), key=lambda kv: -kv[1]):
        o.append(f"- {v} — {k}")
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    mx = build_matrix()
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(mx, indent=1), encoding="utf-8")
    report = render_report(mx) + render_comparison(mx)
    (ROOT / "reports" / "legacy_v21_gate_matrix.md").write_text(report, encoding="utf-8")
    print(report)
