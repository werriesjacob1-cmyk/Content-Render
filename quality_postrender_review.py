#!/usr/bin/env python3
"""Independent assembled-video review + deterministic targeted repair plan.

The existing renderer keeps its own final QA. This module adds a second,
modular review surface for private certification: nine chronological samples,
Gemini first / Qwen fallback, strict mechanical floors, and a deterministic
translation from evidence-group violations into bounded repair targets.

When the renderer's measured scene timeline is available, each repair target is
also mapped to the exact rendered scene IDs that overlap the failing window.
It never edits the video and never publishes. A failed verdict is valuable
artifact evidence: reports are written before returning non-zero.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

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


def load_scene_timeline(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = payload.get("scenes") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            start = float(row.get("start_s"))
            end = float(row.get("end_s"))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        out.append({
            "scene_id": str(row.get("scene_id") or ""),
            "scene_index": int(row.get("scene_index") or 0),
            "role": str(row.get("role") or "scene"),
            "start_s": round(start, 3),
            "end_s": round(end, 3),
            "search_query": str(row.get("search_query") or ""),
            "source_claim_ids": list(row.get("source_claim_ids") or []),
        })
    return out


def _overlapping_scenes(
    scene_timeline: Sequence[Mapping[str, Any]],
    start_s: float,
    end_s: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in scene_timeline:
        try:
            start = float(row.get("start_s"))
            end = float(row.get("end_s"))
        except (TypeError, ValueError):
            continue
        if end > start_s and start < end_s:
            out.append({
                "scene_id": str(row.get("scene_id") or ""),
                "scene_index": int(row.get("scene_index") or 0),
                "role": str(row.get("role") or "scene"),
                "start_s": round(start, 3),
                "end_s": round(end, 3),
                "search_query": str(row.get("search_query") or ""),
                "source_claim_ids": list(row.get("source_claim_ids") or []),
            })
    return out


def build_repair_targets(
    verdict: FQ.FinalQAVerdict,
    packet: FQ.SamplePacket,
    scene_timeline: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Convert reviewer evidence into bounded scene-aware instructions without AI."""
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
        affected = _overlapping_scenes(scene_timeline, start, end)
        targets.append({
            "category": category,
            "severity": violation.severity,
            "evidence_group": violation.evidence_group,
            "start_s": start,
            "end_s": end,
            "affected_scene_ids": [x["scene_id"] for x in affected],
            "affected_scenes": affected,
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

    unlocated = [str(x) for x in verdict.critical_failures if str(x).strip()]
    return {
        "schema": "quality-targeted-repair-plan-v2",
        "source_provider": verdict.provider,
        "source_model": verdict.model,
        "mechanical_pass": FQ.mechanical_gate(verdict)[0],
        "scene_timeline_available": bool(scene_timeline),
        "targets": targets,
        "unlocated_critical_failures": unlocated,
        "must_fix": list(verdict.must_fix),
        "automatic_repair_authorized": False,
        "policy": "repair the smallest failing scene/window; never regenerate the whole video when a bounded fix can preserve good work",
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
    scene_timeline_path: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    context = context_from_manifest(manifest)
    packet = FQ.build_sample_packet(video_path, work_dir)
    timeline = load_scene_timeline(scene_timeline_path)
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
            "scene_timeline_available": bool(timeline),
        }
        repair = {
            "schema": "quality-targeted-repair-plan-v2",
            "mechanical_pass": False,
            "scene_timeline_available": bool(timeline),
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
        "scene_timeline_available": bool(timeline),
    })
    repair = build_repair_targets(verdict, packet, timeline)
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
    p.add_argument("--scene-timeline", default="out/scene_timeline.json")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        passed, report = review(
            args.manifest,
            args.video,
            args.report,
            args.repair_plan,
            args.work_dir,
            args.scene_timeline,
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
