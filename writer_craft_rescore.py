#!/usr/bin/env python3
"""Retrospective craft rescore of the stored Writer corpus. Zero LLM, zero network.

Answers the question a flagship run cannot: when a repair improves factual or
mechanical correctness, does it preserve, improve, or damage craft?

The corpus could not answer it before because `score.overall` is populated only
when `validate_err` is null, so "mechanical improvement" and "both sides scored"
never co-occur (0 of 36 pairs). Rescoring with `generate.score_script` would not
fix that: it is an LLM call, so a retrospective pass costs provider spend and a
prospective one costs it on every render -- and the instrument is stochastic, on
a corpus that already caught an LLM judge moving 7.11 -> 6.56 on byte-identical
text.

So this uses the deterministic diagnostics the repo already ships. They are pure
functions over the spoken lines, they already declare `"gating": False`, and
nothing in `select_best_candidate`, `_clears_quality_floor` or `classify_repair`
consults them. Eligibility is untouched by construction rather than by promise.

The metric is fixed in `reports/CRAFT_METRIC_PREREGISTRATION.md`, committed
before any delta here was computed. Read that first; in particular it records
which signals were EXCLUDED for circularity with `validate()` and why.

    python writer_craft_rescore.py --out reports/flagship_craft_rescore.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import writer_v21_editorial_diagnostics as ED
import writer_v21_hook_payoff as HP
import writer_v21_story_shape as SS

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "tests" / "fixtures" / "writer_corpus"

# The five preregistered components. `better` is +1 when a HIGHER value is
# better, -1 when LOWER is better. Nothing here is checked by validate().
CRAFT_COMPONENTS = (
    ("generic_ai_moralizing", -1),
    ("generic_payoff_hits", -1),
    ("unique_function_count", +1),
    ("repeated_primary_runs", -1),
    ("resolution_cue_present", +1),
)


def craft_signals(hook: str, beats: list[str], payoff: str,
                  central_question: str = "") -> dict[str, Any]:
    """The five preregistered numbers for one round. Pure and deterministic."""
    ed = ED.editorial_diagnostics(hook=hook, beats=beats, payoff=payoff)
    shape = SS.shape_signature(hook, beats, payoff)
    proof = HP.payoff_proof_report(hook=hook, payoff=payoff,
                                   central_question=central_question)
    return {
        # KEY NAME MATTERS: editorial_diagnostics returns
        # "generic_ai_moralizing_hits". An earlier version of this file read
        # "moralizing_hits", silently got None, and reported 0 on all 72 rounds
        # -- a dead component that looked like a real measurement.
        "generic_ai_moralizing": len(ed.get("generic_ai_moralizing_hits") or []),
        "generic_payoff_hits": len(proof.get("generic_payoff_hits") or []),
        "unique_function_count": int(shape.get("unique_function_count") or 0),
        "repeated_primary_runs": int(shape.get("repeated_primary_runs") or 0),
        "resolution_cue_present": 1 if proof.get("resolution_cue_present") else 0,
    }


def _round_lines(rnd: dict[str, Any]) -> tuple[str, list[str], str]:
    """hook / middle beats / payoff from a stored round.

    The fixtures store `beats` as the FULL spoken sequence including the hook at
    index 0 and the payoff at index -1 (verified: `hook` and `payoff` are literal
    copies of those entries in every round checked). Splitting here keeps the
    diagnostics' own hook/beats/payoff contract honest.
    """
    seq = [str(x or "") for x in (rnd.get("beats") or [])]
    hook = str(rnd.get("hook") or (seq[0] if seq else ""))
    payoff = str(rnd.get("payoff") or (seq[-1] if len(seq) > 1 else ""))
    middle = seq[1:-1] if len(seq) >= 2 else []
    return hook, middle, payoff


def _mech_improved(p: dict[str, Any], c: dict[str, Any]) -> bool:
    if int(c.get("mechanical_hard_count") or 0) < int(p.get("mechanical_hard_count") or 0):
        return True
    if int(c.get("semantic_violation_count") or 0) < int(p.get("semantic_violation_count") or 0):
        return True
    return bool(p.get("validate_err")) and not c.get("validate_err")


def _new_violation(p: dict[str, Any], c: dict[str, Any]) -> bool:
    if int(c.get("mechanical_hard_count") or 0) > int(p.get("mechanical_hard_count") or 0):
        return True
    return (not p.get("validate_err")) and bool(c.get("validate_err"))


def compare(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Preregistered verdict for one parent->child pair."""
    improved = degraded = 0
    deltas = {}
    for name, better in CRAFT_COMPONENTS:
        d = child[name] - parent[name]
        deltas[name] = d
        if d == 0:
            continue
        if (d > 0) == (better > 0):
            improved += 1
        else:
            degraded += 1
    verdict = "FLAT"
    if improved > degraded:
        verdict = "IMPROVED"
    elif degraded > improved:
        verdict = "DEGRADED"
    return {"deltas": deltas, "improved": improved, "degraded": degraded, "verdict": verdict}


def _identity() -> dict[str, Any]:
    """Bind every number to the exact code and fixtures that produced it."""
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        sha = "(unavailable)"
    fixtures = {}
    for path in sorted(CORPUS.glob("flagship_*.json")):
        fixtures[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    modules = {}
    for mod in (ED, SS, HP):
        src = Path(mod.__file__).read_bytes()
        modules[Path(mod.__file__).name] = hashlib.sha256(src).hexdigest()[:16]
    return {"code_sha": sha, "fixture_sha256_16": fixtures, "scorer_sha256_16": modules,
            "components": [c[0] for c in CRAFT_COMPONENTS],
            "provider_calls": 0, "network_calls": 0}


def build_rows() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(CORPUS.glob("flagship_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        topic = data.get("topic_id") or data.get("topic_hint") or "(unrecorded)"
        for att in data.get("attempts") or []:
            rounds = att.get("rounds") or []
            for i in range(1, len(rounds)):
                p, c = rounds[i - 1], rounds[i]
                ph, pb, ppay = _round_lines(p)
                ch, cb, cpay = _round_lines(c)
                ps, cs = craft_signals(ph, pb, ppay), craft_signals(ch, cb, cpay)
                cmp_ = compare(ps, cs)
                rows.append({
                    "fixture": path.name.split("_")[1],
                    "topic": topic,
                    "treatment": att.get("treatment") or "",
                    "attempt": att.get("attempt"),
                    "pair": f"{p.get('round')}->{c.get('round')}",
                    "repair_type": ((p.get("repair_plan") or {}).get("repair_type") or ""),
                    "mech_improved": _mech_improved(p, c),
                    "new_violation": _new_violation(p, c),
                    "parent": ps, "child": cs, **cmp_,
                })
    return rows


def render_report(rows: list[dict[str, Any]]) -> str:
    ident = _identity()
    out = ["# Retrospective craft rescore — flagships 02-07", "",
           "Metric fixed in `reports/CRAFT_METRIC_PREREGISTRATION.md` **before** any",
           "delta below was computed. Deterministic, zero LLM, zero network.", "",
           "## Identity", "", "```", json.dumps(ident, indent=2), "```", ""]

    measurable = len(rows)
    mech = [r for r in rows if r["mech_improved"]]
    out += ["## Headline", "",
            f"- parent->child pairs: **{len(rows)}**",
            f"- **craft-measurable pairs: {measurable} of {len(rows)} (100%)** "
            f"— was **1 of 36 (2.8%)** with `score.overall`",
            f"- pairs with factual/mechanical improvement: **{len(mech)}**", ""]

    def tally(sub):
        return {v: sum(1 for r in sub if r["verdict"] == v)
                for v in ("IMPROVED", "FLAT", "DEGRADED")}

    t_all, t_mech = tally(rows), tally(mech)
    out += ["## The north-star question", "",
            "| population | IMPROVED | FLAT | DEGRADED |", "|---|---|---|---|",
            f"| all pairs (N={len(rows)}) | {t_all['IMPROVED']} | {t_all['FLAT']} | {t_all['DEGRADED']} |",
            f"| **mechanical improvement (N={len(mech)})** | **{t_mech['IMPROVED']}** | "
            f"**{t_mech['FLAT']}** | **{t_mech['DEGRADED']}** |", ""]

    newv = [r for r in rows if r["new_violation"]]
    out += [f"- pairs introducing a NEW violation: **{len(newv)}** "
            f"(craft: {tally(newv)})", ""]

    out += ["## Per-component totals (raw magnitudes, not signs)", "",
            "| component | mean delta, all | mean delta, mech-improved | worsened | improved |",
            "|---|---|---|---|---|"]
    for name, better in CRAFT_COMPONENTS:
        allm = sum(r["deltas"][name] for r in rows) / max(len(rows), 1)
        mm = sum(r["deltas"][name] for r in mech) / max(len(mech), 1)
        w = sum(1 for r in rows if r["deltas"][name] != 0
                and (r["deltas"][name] > 0) != (better > 0))
        i = sum(1 for r in rows if r["deltas"][name] != 0
                and (r["deltas"][name] > 0) == (better > 0))
        out.append(f"| `{name}` ({'higher' if better>0 else 'lower'} better) | "
                   f"{allm:+.2f} | {mm:+.2f} | {w} | {i} |")
    out.append("")

    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r["repair_type"] or "(none)", []).append(r)
    out += ["## By repair type", "", "| repair_type | N | IMPROVED | FLAT | DEGRADED |",
            "|---|---|---|---|---|"]
    for k, sub in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        t = tally(sub)
        out.append(f"| {k} | {len(sub)} | {t['IMPROVED']} | {t['FLAT']} | {t['DEGRADED']} |")
    out.append("")

    by_fx: dict[str, list] = {}
    for r in rows:
        by_fx.setdefault(r["fixture"], []).append(r)
    out += ["## By flagship (N per cell is tiny — descriptive only)", "",
            "| flagship | topic | N | IMPROVED | FLAT | DEGRADED |", "|---|---|---|---|---|---|"]
    for k, sub in sorted(by_fx.items()):
        t = tally(sub)
        out.append(f"| {k} | {sub[0]['topic']} | {len(sub)} | {t['IMPROVED']} | "
                   f"{t['FLAT']} | {t['DEGRADED']} |")
    out.append("")

    out += ["## Every pair", "",
            "| fx | att | pair | repair_type | mech+ | new viol | " +
            " | ".join(c[0][:14] for c in CRAFT_COMPONENTS) + " | verdict |",
            "|---|---|---|---|---|---|" + "---|" * (len(CRAFT_COMPONENTS) + 1)]
    for r in rows:
        d = " | ".join(f"{r['deltas'][c[0]]:+d}" for c in CRAFT_COMPONENTS)
        out.append(f"| {r['fixture']} | {r['attempt']} | {r['pair']} | {r['repair_type']} | "
                   f"{'Y' if r['mech_improved'] else '-'} | {'Y' if r['new_violation'] else '-'} | "
                   f"{d} | {r['verdict']} |")
    out += ["", "## Limits", "",
            "36 pairs from 6 runs on a few topics is a convenience corpus, not a sample of",
            "any population. No significance testing is offered and none is implied. The",
            "five components are proxies for craft, not craft: a repair could move all five",
            "the right way and still read worse aloud.", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    rows = build_rows()
    report = render_report(rows)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"wrote {args.out} ({len(rows)} pairs)")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
