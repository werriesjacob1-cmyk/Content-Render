#!/usr/bin/env python3
"""Seal execution identity and provider-causal thresholds into a quality-proof plan.

This is zero-network and must run BEFORE live generation. It takes the freshly
prepared plan, verifies its existing seal, stamps the exact trusted execution SHA,
adds the versioned same-draft-model thresholds, and re-seals the plan.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

import wr21_quality_bakeoff as C
import writer_v21_provider_guardrail as P

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def preregister(plan: dict[str, Any], execution_sha: str) -> dict[str, Any]:
    C._verify_envelope_hash(plan, "plan_sha256")
    if not _SHA_RE.fullmatch(execution_sha):
        raise C.Q.BakeoffProtocolError("execution_sha must be an exact 40-char lowercase git SHA")
    protocol = plan.get("protocol")
    if not isinstance(protocol, dict):
        raise C.Q.BakeoffProtocolError("plan protocol must be object")
    out = dict(plan)
    out.pop("plan_sha256", None)
    p = dict(protocol)
    p.update(P.DEFAULTS)
    p["provider_guardrail_version"] = P.VERSION
    out["protocol"] = p
    out["execution_sha"] = execution_sha
    out["plan_sha256"] = C._digest(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--execution-sha", required=True)
    args = ap.parse_args(argv)
    try:
        path = Path(args.plan)
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise C.Q.BakeoffProtocolError("plan must be object")
        sealed = preregister(doc, args.execution_sha)
        _write(path, sealed)
        print(f"preregistered execution_sha={sealed['execution_sha']}")
        print(f"provider_guardrail_version={sealed['protocol']['provider_guardrail_version']}")
        print(f"plan_sha256={sealed['plan_sha256']}")
        return 0
    except (OSError, json.JSONDecodeError, C.Q.BakeoffProtocolError) as exc:
        print(f"PREREGISTRATION ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
