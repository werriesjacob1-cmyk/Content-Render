"""Composed Writer V2.1 experimental runtime.

Keeps the two promotion-critical takeover changes isolated from Claude's source:
1) fail-closed semantic orchestration (`writer_v21_orchestrator`)
2) correct spoken-scene manifest (`writer_v21_manifest`)

`writer_v21_orchestrator` deliberately reuses `writer_v2.assemble_manifest_v2`.
For this experiment we temporarily substitute the corrected assembly function for
the duration of one synchronous candidate call, then restore the original in a
`finally` block. This avoids a risky 278k `generate.py` rewrite while keeping the
live bakeoff path exactly testable. Production integration should replace this
with ordinary dependency injection/delegation once promotion is earned.
"""
from __future__ import annotations

import writer_v21_manifest as M
import writer_v21_orchestrator as O


def generate_candidate_v21(*args, **kwargs):
    original = O.W.assemble_manifest_v2
    O.W.assemble_manifest_v2 = M.assemble_manifest_v21
    try:
        manifest, debug = O.generate_candidate_v21(*args, **kwargs)
        if isinstance(debug, dict):
            debug["manifest_assembly"] = "writer_v21_manifest.assemble_manifest_v21"
        return manifest, debug
    finally:
        O.W.assemble_manifest_v2 = original
