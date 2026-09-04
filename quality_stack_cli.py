#!/usr/bin/env python3
"""CLI entry point for the modular Content Render quality stack.

Default invocation is deliberately zero-spend and zero-network. It reads an
existing manifest, validates the integration modules and writes a complete tool
plan. Permission flags only change the PLAN's eligibility matrix; this CLI does
not execute providers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import capability_preflight as CP
import quality_stack as Q


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="manifest.json")
    ap.add_argument("--out", default="quality_plan.json")
    ap.add_argument("--status-only", action="store_true")
    ap.add_argument("--preflight", action="store_true",
                    help="report credentials/binaries available on this runner; ZERO provider calls")
    ap.add_argument("--allow-network", action="store_true")
    ap.add_argument("--allow-paid", action="store_true")
    ap.add_argument("--allow-generated-visuals", action="store_true")
    ap.add_argument("--enable-voice-experiments", action="store_true")
    ap.add_argument("--enable-sound-design", action="store_true")
    ap.add_argument("--enable-repair", action="store_true")
    ap.add_argument("--enable-final-qa-provider-calls", action="store_true")
    ap.add_argument("--execution-plan", action="store_true",
                    help="mark plan_only false in the eligibility matrix; still makes ZERO provider calls")
    args = ap.parse_args()

    status = Q.integration_status()
    required_missing = [m for m in Q.required_module_names() if not any(
        row["module"] == m and row["module_present"] for row in status.values()
    )]
    if required_missing:
        print("Missing required integration modules: " + ", ".join(required_missing), file=sys.stderr)
        return 2

    if args.preflight:
        report = {
            "integration_status": status,
            "runner_preflight": CP.summary(),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    if args.status_only:
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0

    if not os.path.exists(args.manifest):
        print(f"manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)
    if not isinstance(manifest, dict):
        print("manifest must be a JSON object", file=sys.stderr)
        return 2

    policy = Q.QualityPolicy(
        plan_only=not args.execution_plan,
        allow_network=args.allow_network,
        allow_paid=args.allow_paid,
        allow_generated_visuals=args.allow_generated_visuals,
        enable_voice_experiments=args.enable_voice_experiments,
        enable_sound_design=args.enable_sound_design,
        enable_repair=args.enable_repair,
        enable_final_qa_provider_calls=args.enable_final_qa_provider_calls,
    )
    plan = Q.build_quality_plan(manifest, policy)
    if plan.get("provider_calls_made") != 0 or plan.get("publishing_enabled") is not False:
        raise AssertionError("quality planner violated zero-execution contract")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"Wrote {args.out}: {len(plan['scenes'])} scene(s), zero provider calls, publishing disabled")
    if not plan.get("writer_v2_present"):
        print("Writer V2 slot: waiting for Claude V2.1 approval/landing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
