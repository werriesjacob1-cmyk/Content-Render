#!/usr/bin/env python3
"""Independent assembled-video review + deterministic targeted repair plan.

The existing renderer keeps its own final QA. This module adds a second,
modular review surface for private certification: nine chronological samples,
Gemini first / Qwen fallback, strict mechanical floors, and a deterministic
translation from evidence-group violations into bounded repair targets.

It never edits the video and never publishes. A failed verdict is valuable
artifact evidence: the report and repair plan are written before returning a
non-zero status so the certification package can still be inspected.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

import final_video_qa as FQ
from narration import spoken_text


_CATEGORY_ACTIONS = {
    "hook_visual": "replace or strengthen opening visual evidence; preserve accepted narration and facts",
    "narration_visual_match": "re-resolve the affected visual against the spoken scene intent; preserve narration",
    "scientific_visual_integrity": "replace with authentic or evidence-bound deterministic science media; do not cosmetically patch wrong science",
    "visual_variety": "change source shot, crop, or motion rhythm inside this window without changing factual content",
    "pacing": "retime cuts/transitions inside this window while preserving narration order and word timing",
    "caption_legibility": "repair caption placement/size/timing only; preserve underlying scene evidence",
    "continuity": "repair the transition or visual continuity while preserving the accepted scene sequence",
    "payoff_visual": "replace the payoff visual with a literal proof/reveal asset that shows the spoken realization",
    "ai_artifact_control": "reject the corrupted generated asset; prefer authentic media or regenerate only through independent vision QA",
}


def _norm_category(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "narration_visual": "narration_visual_match",
        "visual_match": "narration_visual_match",
        "science": "scientific_visual_integrity",
        "scientific_integrity": "scientific_visual_integrity",
        "captions": "caption_legibility",
        "payoff": "payoff_visual",
        "ai_artifacts": "ai_artifact_control",
    }
    return aliases.get(text, text)


def _group_window(packet: FQ.SamplePacket, group: int) -> tuple[float, float]:
    idxs = FQ.SHEETS[group - 1]
    start = max(0.0, packet.timestamps_s[idxs[0]] - 0.6)
    end = min(packet.duration_s, packet.timestamps_s[idxs[-1]] + 0.6)
    return round(start, 3), round(end, 3)


def build_repair_targets(
    verdict: FQ.FinalQAVerdict,
    packet: FQ.SamplePacket,
) -> dict[str, Any]:
    """Convert reviewer evidence into bounded repair instructions without AI."""
    targets: list[dict[str, Any]] = []
    for violation in verdict.violations:
        if violation.severity not in {"critical", "major"}:
            continue
        category = _norm_category(violation.category)
        start, end = _group_window(packet, violation.evidence_group)
        action = _CATEGORY_ACTIONS.get(
            category,
            "repair only the cited viewer-facing defect in this window; preserve narration, factual claims, and unaffected footage",
        )
        targets.append({
            "category": category,
            "severity": violation.severity,
            "evidence_group": violation.evidence_group,
            "start_s": start,
            "end_s": end,
            "problem": violation.detail,
            "recommended_action": action,
            "preserve": [
                "accepted Writer V2.1 narration",
                "sealed source claim IDs",
                "unaffected scenes",
                "caption word timing unless caption_legibility/pacing is the defect",
            ],
            "automatic_repair_authorized": False,
        })

    # Critical failures may not be duplicated in the structured violation list.
    # Preserve them visibly instead of silently dropping them from the repair plan.
    unlocated = [str(x) for x in verdict.critical_failures if str(x).strip()]
    return {
        "schema": "quality-targeted-repair-plan-v1",
        "source_provider": verdict.provider,
        "source_model": verdict.model,
        "mechanical_pass": FQ.mechanical_gate(verdict)[0],
        "targets": targets,
        "unlocated_critical_failures": unlocated,
        "must_fix": list(verdict.must_fix),
        "automatic_repair_authorized": False,
        "policy": "repair the smallest failing window; never regenerate the whole video when a bounded fix can preserve good work",
    }


def context_from_manifest(manifest: Mapping[str, Any]) -> FQ.FinalQAContext:
    scenes = [s for s in (manifest.get("scenes") or []) if isinstance(s, Mapping)]
    narration = spoken_text(manifest)
    intents = tuple(
        " | ".join(x for x in (
            str(s.get("search_query") or "").strip(),
            str(s.get("voiceover") or "").strip(),
        ) if x)
        for s in scenes
    )
    subjects = tuple(str(s.get("search_query") or "").strip() for s in scenes if str(s.get("search_query") or "").strip())
    return FQ.FinalQAContext(
        title=str(manifest.get("title") or "").strip(),
        narration=narration,
        scene_intents=intents,
        factual_subjects=subjects,
    )


def review(
    manifest_path: str,
    video_path: str,
    report_path: str,
    repair_path: str,
    work_dir: str,
) -> tuple[bool, dict[str, Any]]:
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    context = context_from_manifest(manifest)
    packet = FQ.build_sample_packet(video_path, work_dir)
    verdict = FQ.final_qa_with_fallback(context, packet)

    report_file = Path(report_path)
    repair_file = Path(repair_path)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    repair_file.parent.mkdir(parents=True, exist_ok=True)

    if verdict is None:
        report = {
            "schema": "quality-holistic-review-v1",
            "ran": False,
            "mechanical_pass": False,
            "reason": "no configured holistic QA provider returned a verdict",
            "human_review_required": True,
            "sample_timestamps_s": list(packet.timestamps_s),
        }
        repair = {
            "schema": "quality-targeted-repair-plan-v1",
            "mechanical_pass": False,
            "targets": [],
            "unlocated_critical_failures": ["holistic QA unavailable"],
            "automatic_repair_authorized": False,
        }
        report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        repair_file.write_text(json.dumps(repair, indent=2), encoding="utf-8")
        return False, report

    report = dict(FQ.verdict_report(verdict))
    report.update({
        "schema": "quality-holistic-review-v1",
        "ran": True,
        "sample_timestamps_s": list(packet.timestamps_s),
        "contact_sheet_count": len(packet.sheet_paths),
    })
    repair = build_repair_targets(verdict, packet)
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    repair_file.write_text(json.dumps(repair, indent=2), encoding="utf-8")
    return bool(report["mechanical_pass"]), report


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--video", required=True)
    p.add_argument("--report", default="out/holistic_qa_report.json")
    p.add_argument("--repair-plan", default="out/targeted_repair_plan.json")
    p.add_argument("--work-dir", default="work/holistic_qa")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        passed, report = review(
            args.manifest, args.video, args.report, args.repair_plan, args.work_dir
        )
    except Exception as exc:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps({
            "schema": "quality-holistic-review-v1",
            "ran": False,
            "mechanical_pass": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "human_review_required": True,
        }, indent=2), encoding="utf-8")
        print(f"HOLISTIC QA FAILED TO RUN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
