"""Claim verification: does the verified source actually support what the script says?

Run 455's ending said "animals survive two minutes flatlined" -- fluent, confident and
wrong -- and nothing in the pipeline compares a script to its source: validate() checks
shape, the rubric judges quality, final QA looks at frames. This module is the missing
check. Pure (prompt build + reply parsing + decision); generate.verify_claims makes the
one LLM call.

Honest limits: the checker is an LLM from the same provider chain as the writer, so it is
a second opinion, not an independent authority, and it can only call a line unsupported
relative to the SOURCE it is given. It fails OPEN (a down/garbled checker never blocks a
script), because a false 'unsupported' on a true line costs a regeneration.
"""
from __future__ import annotations

import json
import re

SUPPORTED, UNSUPPORTED, CONTRADICTED, NOT_A_CLAIM = "SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "NOT_A_CLAIM"
UNSUPPORTED_REJECT_AT = 3     # one or two unsupported lines are logged; three reject the script


def build_prompt(source, lines):
    numbered = "\n".join(f"{i}. {t.strip()}" for i, t in enumerate(lines, 1))
    return (
        "You are a strict science fact-checker. SOURCE is the only verified material.\n\n"
        f"SOURCE:\n{source.strip()[:6000]}\n\n"
        "NARRATION LINES:\n" + numbered + "\n\n"
        "For EACH line give one verdict:\n"
        "- SUPPORTED: stated by, or clearly implied by, the SOURCE.\n"
        "- UNSUPPORTED: a factual claim (number, date, name, causal statement, or a "
        "characterisation such as 'flatlined', 'violently', 'always', 'the only') that the SOURCE "
        "does not support.\n"
        "- CONTRADICTED: conflicts with the SOURCE.\n"
        "- NOT_A_CLAIM: a question, transition or opinion with no factual content.\n"
        "Be strict about wording that sounds right but changes the meaning. "
        'Reply with JSON only: {"lines":[{"n":1,"verdict":"SUPPORTED","why":"short"}]}'
    )


def parse(reply, n_lines):
    """{line_number(1-based): (verdict, why)} from a model reply. Unknown/garbled -> {}."""
    try:
        m = re.search(r"\{.*\}", reply or "", re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for item in (data.get("lines") or []):
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        v = str(item.get("verdict", "")).strip().upper().replace(" ", "_")
        if 1 <= n <= n_lines and v in (SUPPORTED, UNSUPPORTED, CONTRADICTED, NOT_A_CLAIM):
            out[n] = (v, str(item.get("why", "")).strip()[:160])
    return out


def decide(verdicts, lines):
    """(error_or_None, notes). CONTRADICTED rejects at once; UNSUPPORTED_REJECT_AT or more
    UNSUPPORTED lines reject; a single unsupported line is only noted."""
    bad = [(n, w) for n, (v, w) in sorted(verdicts.items()) if v == CONTRADICTED]
    if bad:
        n, why = bad[0]
        return (f"line {n} ({lines[n - 1]!r}) contradicts the verified source: {why}"), []
    uns = [(n, w) for n, (v, w) in sorted(verdicts.items()) if v == UNSUPPORTED]
    if len(uns) >= UNSUPPORTED_REJECT_AT:
        shown = "; ".join(f"line {n} ({lines[n - 1]!r}): {w}" for n, w in uns[:3])
        return (f"{len(uns)} lines make claims the verified source does not support — {shown}. "
                f"Say only what the source supports"), []
    return None, [f"line {n} ({lines[n - 1]!r}) unsupported: {w}" for n, w in uns]
