#!/usr/bin/env python3
"""A8: per-scene provenance must survive a bounded repair.

Lineage is the record of what a shipped artifact actually contains. The factory
proof exposed the gap: ``final_asset_lineage.json`` is written once, before the
repair, and still names ``work/s2.mp4`` and ``work/s3.mp4`` after those exact
scenes have been replaced. The repaired video ships with a provenance file that
is confidently wrong -- worse than an absent one, because it reads as attribution
while attributing the wrong assets.

The four shapes this pins, all of which previously passed unnoticed:
  1. an unattributable scene,
  2. a phantom asset (lineage names a file that is not there),
  3. stale-after-repair lineage (provenance of the pre-repair artifact reused),
  4. repaired lineage that does not identify WHICH scenes were replaced.

Zero network, zero providers, no ffmpeg.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import quality_asset_lineage as QAL

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _entry(sid, idx, path, **over):
    kw = dict(
        scene_id=str(sid), scene_index=idx, visual_intent="demonstrate",
        subject_id="subj", subject="a subject", renderer_kind="fixture_video",
        output_file=str(path), duration_s=4.0, attributable=True,
    )
    kw.update(over)
    return QAL.AssetLineageEntry(**kw)


def _base(td, n=4):
    files = []
    for i in range(1, n + 1):
        p = Path(td) / f"s{i}.mp4"
        p.write_bytes(b"ORIGINAL-%d" % i)
        files.append(p)
    entries = [_entry(i, i, files[i - 1]) for i in range(1, n + 1)]
    return QAL.write_lineage(entries, Path(td) / "final_asset_lineage.json"), files


# --- 1. unattributable scene ------------------------------------------------

def test_an_unattributable_rendered_scene_is_visible_in_the_record():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s1.mp4"
        p.write_bytes(b"x")
        payload = QAL.write_lineage(
            [_entry(1, 1, p), _entry(2, 2, p, attributable=False)],
            Path(td) / "l.json")
        check(payload["all_rendered_scenes_attributable"] is False,
              "one unattributable RENDERED scene falsifies the whole-video claim")
        check(payload["attributable_scene_count"] == 1,
              "and the count says how many scenes are actually accounted for")


def test_a_rendered_scene_with_no_renderer_kind_is_refused():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s1.mp4"
        p.write_bytes(b"x")
        try:
            QAL.write_lineage([_entry(1, 1, p, renderer_kind="")], Path(td) / "l.json")
            raise AssertionError("a rendered scene with no renderer_kind should be refused")
        except ValueError as exc:
            check("renderer_kind" in str(exc),
                  "a scene with real duration but no renderer identity cannot be written")


# --- 2. phantom asset -------------------------------------------------------

def test_a_phantom_asset_is_detected():
    with tempfile.TemporaryDirectory() as td:
        payload, files = _base(td)
        check(QAL.phantom_assets(payload) == (),
              "a lineage whose files all exist reports no phantoms")
        files[1].unlink()
        check(QAL.phantom_assets(payload) == ("2",),
              "deleting the asset behind scene 2 makes that entry a detected phantom")


def test_the_factory_proof_fails_on_a_phantom_asset():
    src = (ROOT / "quality_downstream_factory_proof.py").read_text(encoding="utf-8")
    check("phantom_assets(" in src,
          "the factory proof checks its lineage against files that actually exist")
    check("lineage attributes scene(s)" in src,
          "and fails the run rather than reporting an attributed video it cannot back")


# --- 3. stale-after-repair lineage -----------------------------------------

def test_repaired_lineage_points_at_the_files_the_repair_assembled():
    with tempfile.TemporaryDirectory() as td:
        payload, files = _base(td)
        repl = {}
        for sid in ("2", "3"):
            p = Path(td) / f"scene_{sid}_repaired.mp4"
            p.write_bytes(b"REPLACEMENT-" + sid.encode())
            repl[sid] = str(p)
        out = QAL.repaired_lineage(
            payload, repl,
            repaired_video=str(Path(td) / "repaired.mp4"),
            base_video=str(Path(td) / "final.mp4"))
        by_id = {r["scene_id"]: r for r in out["scenes"]}
        check(by_id["2"]["output_file"] == repl["2"],
              "the repaired lineage names the REPLACEMENT file for scene 2")
        check(by_id["2"]["replaced_output_file"].endswith("s2.mp4"),
              "and still records what that scene used to be, so the swap is auditable")
        check(by_id["1"]["output_file"] == str(files[0]),
              "an unrepaired scene keeps its original attribution untouched")
        check(by_id["1"]["repair_replaced"] is False and by_id["2"]["repair_replaced"] is True,
              "every scene states whether it was replaced -- no scene is ambiguous")


def test_the_repaired_record_is_bound_to_the_repaired_artifact():
    with tempfile.TemporaryDirectory() as td:
        payload, _ = _base(td)
        p = Path(td) / "r2.mp4"
        p.write_bytes(b"R")
        out = QAL.repaired_lineage(payload, {"2": str(p)},
                                   repaired_video="/o/repaired.mp4",
                                   base_video="/o/final.mp4")
        check(out["schema"] == QAL.REPAIRED_SCHEMA,
              "a repaired lineage carries its own schema, not the pre-repair one")
        check(out["applies_to_video"] == "/o/repaired.mp4",
              "it names the artifact it actually describes")
        check(out["repair_of_video"] == "/o/final.mp4",
              "and the artifact it was derived from, so the two cannot be confused")


def test_the_factory_proof_rebuilds_lineage_after_repairing():
    """The exact staleness the real proof shipped with."""
    src = (ROOT / "quality_downstream_factory_proof.py").read_text(encoding="utf-8")
    check("write_repaired_lineage(" in src,
          "the factory proof writes lineage for the REPAIRED artifact too")
    lineage_at = src.find("write_lineage(")
    repaired_at = src.find("write_repaired_lineage(")
    repair_at = src.find("execute_replacements(")
    check(0 < lineage_at < repair_at < repaired_at,
          "and it does so AFTER the repair -- lineage written only before it "
          "would describe assets the repaired video no longer contains")
    check('repaired_scene_files' in src,
          "it rebuilds from the files the repair controller actually assembled, "
          "not from a re-derivation of what it assumes those were")


def test_the_controller_reports_what_it_assembled():
    src = (ROOT / "quality_repair_controller.py").read_text(encoding="utf-8")
    check('"repaired_scene_files": dict(new_paths)' in src,
          "the repair controller names the per-scene files it assembled, so "
          "provenance is rebuilt from fact rather than inference")


# --- 4. a repaired record that does not identify the replacement ------------

def test_a_repaired_lineage_that_repaired_nothing_is_refused():
    with tempfile.TemporaryDirectory() as td:
        payload, _ = _base(td)
        try:
            QAL.repaired_lineage(payload, {}, repaired_video="/o/r.mp4",
                                 base_video="/o/f.mp4")
            raise AssertionError("an empty replacement set should be refused")
        except ValueError as exc:
            check("at least one replaced scene" in str(exc),
                  "a 'repaired' lineage naming no replacement is a false claim, refused")


def test_a_no_op_replacement_is_refused():
    with tempfile.TemporaryDirectory() as td:
        payload, files = _base(td)
        try:
            QAL.repaired_lineage(payload, {"2": str(files[1])},
                                 repaired_video="/o/r.mp4", base_video="/o/f.mp4")
            raise AssertionError("replacing a file with itself should be refused")
        except ValueError as exc:
            check("not a repair" in str(exc),
                  "a replacement identical to the file it replaces is refused, so the "
                  "record cannot claim a repair that did not happen")


def test_a_replacement_for_an_unknown_scene_is_refused():
    with tempfile.TemporaryDirectory() as td:
        payload, _ = _base(td)
        p = Path(td) / "x.mp4"
        p.write_bytes(b"X")
        try:
            QAL.repaired_lineage(payload, {"9": str(p)},
                                 repaired_video="/o/r.mp4", base_video="/o/f.mp4")
            raise AssertionError("a scene absent from the base lineage should be refused")
        except ValueError as exc:
            check("absent from the base lineage" in str(exc),
                  "provenance cannot be invented for a scene the render never had")


def test_the_repaired_scene_ids_are_stated_explicitly():
    with tempfile.TemporaryDirectory() as td:
        payload, _ = _base(td)
        repl = {}
        for sid in ("3", "2"):
            p = Path(td) / f"r{sid}.mp4"
            p.write_bytes(b"R" + sid.encode())
            repl[sid] = str(p)
        out = QAL.repaired_lineage(payload, repl, repaired_video="/o/r.mp4",
                                   base_video="/o/f.mp4")
        check(out["repaired_scene_ids"] == ["2", "3"],
              "the repaired scenes are listed explicitly and deterministically, so a "
              "reviewer never has to diff two files to learn what changed")
        check(json.dumps(out, sort_keys=True),
              "the repaired lineage is JSON-serializable as written")


if __name__ == "__main__":
    test_an_unattributable_rendered_scene_is_visible_in_the_record()
    test_a_rendered_scene_with_no_renderer_kind_is_refused()
    test_a_phantom_asset_is_detected()
    test_the_factory_proof_fails_on_a_phantom_asset()
    test_repaired_lineage_points_at_the_files_the_repair_assembled()
    test_the_repaired_record_is_bound_to_the_repaired_artifact()
    test_the_factory_proof_rebuilds_lineage_after_repairing()
    test_the_controller_reports_what_it_assembled()
    test_a_repaired_lineage_that_repaired_nothing_is_refused()
    test_a_no_op_replacement_is_refused()
    test_a_replacement_for_an_unknown_scene_is_refused()
    test_the_repaired_scene_ids_are_stated_explicitly()
    print("asset lineage after repair tests: PASS")
