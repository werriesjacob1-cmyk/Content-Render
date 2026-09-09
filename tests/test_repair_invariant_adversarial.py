#!/usr/bin/env python3
"""Adversarial regressions for the bounded QA -> repair -> re-QA invariant (A6).

A targeted repair may change the authorized scene's asset. It must NEVER
downgrade the finished product: captions, music, mastering, encoding and the QA
requirements all have to survive. The real factory proof already caught the
worst version of this -- the repair path re-assembled with a bare concat, so
the repaired video silently lost captions, music and loudness normalization
while the initial assembly kept them. These tests attack the invariant from the
directions that bug came from, plus the ones nothing has exercised yet.

Zero network, zero providers, no ffmpeg: the repair controller's contract is
enforced on file identity and callback behaviour, so it is provable with plain
files and a stub assembler.
"""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import quality_repair_controller as RC

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _plan(scene_ids=("2",)):
    """A VALID bounded repair plan: the controller also demands a positive
    window and an explicit Writer/claim preservation contract."""
    return {
        "targets": [{
            "category": "narration_visual_match",
            "severity": "major",
            "affected_scene_ids": list(scene_ids),
            "start_s": 3.0,
            "end_s": 6.0,
            "recommended_action": "replace the affected scene visual only",
            "preserve": ["accepted Writer V2.1 narration", "sealed source claim IDs",
                         "unaffected scenes"],
        }],
    }


def _scene_files(td, n=4):
    out = {}
    for i in range(1, n + 1):
        p = Path(td) / f"s{i}.mp4"
        p.write_bytes(b"ORIGINAL-SCENE-%d" % i + b"\x00" * 2048)
        out[str(i)] = str(p)
    return out


def _replacement(td, sid):
    p = Path(td) / f"repl_{sid}.mp4"
    p.write_bytes(b"REPLACEMENT-%s" % sid.encode() + b"\xff" * 2048)
    return str(p)


def _assemble_ok(files, dest):
    Path(dest).write_bytes(b"ASSEMBLED" + b"\x00" * 4096)


def test_repair_cannot_touch_an_unauthorized_scene():
    with tempfile.TemporaryDirectory() as td:
        scenes = _scene_files(td)
        # Plan authorizes scene 2; caller tries to also swap scene 3.
        repls = {"2": _replacement(td, "2"), "3": _replacement(td, "3")}
        try:
            RC.execute_replacements(
                plan=_plan(("2",)), scene_files=scenes, replacements=repls,
                output_scene_dir=Path(td) / "o", output_video=Path(td) / "o.mp4",
                assemble=_assemble_ok,
            )
            raise AssertionError("unauthorized extra scene should be refused")
        except ValueError as exc:
            check("must exactly equal" in str(exc),
                  "a replacement for a scene the plan never authorized is refused")


def test_repair_cannot_silently_skip_an_authorized_scene():
    with tempfile.TemporaryDirectory() as td:
        scenes = _scene_files(td)
        try:
            RC.execute_replacements(
                plan=_plan(("2", "3")), scene_files=scenes,
                replacements={"2": _replacement(td, "2")},   # 3 omitted
                output_scene_dir=Path(td) / "o", output_video=Path(td) / "o.mp4",
                assemble=_assemble_ok,
            )
            raise AssertionError("partial replacement set should be refused")
        except ValueError as exc:
            check("must exactly equal" in str(exc),
                  "a plan targeting two scenes cannot be satisfied by repairing one")


def test_missing_replacement_asset_fails_closed():
    with tempfile.TemporaryDirectory() as td:
        scenes = _scene_files(td)
        try:
            RC.execute_replacements(
                plan=_plan(("2",)), scene_files=scenes,
                replacements={"2": str(Path(td) / "does_not_exist.mp4")},
                output_scene_dir=Path(td) / "o", output_video=Path(td) / "o.mp4",
                assemble=_assemble_ok,
            )
            raise AssertionError("missing replacement file should be refused")
        except ValueError as exc:
            check("source missing" in str(exc),
                  "a replacement asset that does not exist fails closed")


def test_a_replacement_identical_to_the_original_is_refused():
    """A 'repair' that changes nothing must not be reported as a repair."""
    with tempfile.TemporaryDirectory() as td:
        scenes = _scene_files(td)
        try:
            RC.execute_replacements(
                plan=_plan(("2",)), scene_files=scenes,
                replacements={"2": scenes["2"]},   # same bytes
                output_scene_dir=Path(td) / "o", output_video=Path(td) / "o.mp4",
                assemble=_assemble_ok,
            )
            raise AssertionError("no-op replacement should be refused")
        except RuntimeError as exc:
            check("byte-identical" in str(exc),
                  "a replacement byte-identical to the original is not a repair")


def test_unaffected_scenes_are_proven_unchanged_by_hash():
    with tempfile.TemporaryDirectory() as td:
        scenes = _scene_files(td)
        ev = RC.execute_replacements(
            plan=_plan(("2",)), scene_files=scenes,
            replacements={"2": _replacement(td, "2")},
            output_scene_dir=Path(td) / "o", output_video=Path(td) / "o.mp4",
            assemble=_assemble_ok,
        )
        pres = ev["unaffected_scene_preservation"]
        check(set(pres) == {"1", "3", "4"},
              "every non-target scene is accounted for in preservation evidence")
        check(all(v["unchanged"] and v["before"] == v["after"] for v in pres.values()),
              "unaffected scenes carry identical before/after hashes")
        check(ev["targeted_scene_changed"] == {"2": True},
              "the authorized scene is recorded as actually changed")
        check(ev["provider_calls_made"] == 0 and ev["provider_repair_authorized"] is False,
              "a bounded repair makes no provider calls and claims no provider authorization")


def test_re_qa_is_measured_on_the_repaired_output_not_the_original():
    """Stale QA is the failure mode PR #70 fixed upstream: evidence computed for
    one artifact must never be presented as evidence for a different one."""
    with tempfile.TemporaryDirectory() as td:
        scenes = _scene_files(td)
        manifest = Path(td) / "manifest.json"
        manifest.write_text(json.dumps({"scenes": []}), encoding="utf-8")
        out_video = Path(td) / "repaired.mp4"
        seen = {}
        original_review = RC.AQA.review

        def fake_review(video, mpath):
            seen["video"] = str(video)
            return {"mechanical_pass": True, "integrated_lufs": -14.0}

        RC.AQA.review = fake_review
        try:
            ev = RC.execute_replacements(
                plan=_plan(("2",)), scene_files=scenes,
                replacements={"2": _replacement(td, "2")},
                output_scene_dir=Path(td) / "o", output_video=out_video,
                assemble=_assemble_ok, manifest_path=manifest,
            )
        finally:
            RC.AQA.review = original_review
        check(seen.get("video") == str(out_video),
              "re-QA is run against the REPAIRED video, never the pre-repair one")
        check(ev["re_qa"]["audio_mechanical_pass"] is True,
              "the repaired artifact's own audio verdict is recorded")
        check(ev["output_sha256"] and len(ev["output_sha256"]) == 64,
              "the repaired output is hashed so its identity is pinned to this evidence")


def test_failing_re_qa_is_reported_not_swallowed():
    with tempfile.TemporaryDirectory() as td:
        scenes = _scene_files(td)
        manifest = Path(td) / "manifest.json"
        manifest.write_text(json.dumps({"scenes": []}), encoding="utf-8")
        original_review = RC.AQA.review
        RC.AQA.review = lambda v, m: {"mechanical_pass": False,
                                      "mechanical_reasons": ["integrated loudness out of range"]}
        try:
            ev = RC.execute_replacements(
                plan=_plan(("2",)), scene_files=scenes,
                replacements={"2": _replacement(td, "2")},
                output_scene_dir=Path(td) / "o", output_video=Path(td) / "r.mp4",
                assemble=_assemble_ok, manifest_path=manifest,
            )
        finally:
            RC.AQA.review = original_review
        check(ev["re_qa"]["audio_mechanical_pass"] is False,
              "a failing post-repair audio QA is surfaced as False, not dropped")
        check(ev["re_qa"]["audio"]["mechanical_reasons"],
              "the reasons the repaired audio failed are retained for review")


def test_repair_reassembles_through_the_canonical_finishing_path():
    """The regression the real factory proof caught: the repair used a bare
    concat, so the repaired video lost captions, music and loudnorm while the
    initial assembly kept them. Both must use the SAME finishing function."""
    src = (ROOT / "quality_downstream_factory_proof.py").read_text(encoding="utf-8")
    check("def _finish_assembly(" in src,
          "there is a single named finishing path for assemblies")
    check("mix = _finish_assembly(scene_files, final)" in src,
          "the initial assembly goes through the canonical finishing path")
    check("assemble=_finish_assembly" in src,
          "the repair re-assembles through that SAME finishing path")
    check("assemble=lambda files, dest: legacy.build_body_concat" not in src,
          "no bare-concat repair path remains")
    # the finishing path must actually do the finishing work
    body = src.split("def _finish_assembly(", 1)[1].split("\n        final =", 1)[0]
    for stage, why in (("build_body_concat", "concat"), ("build_ass", "captions"),
                       ("_make_captioned", "caption burn"), ("_mix_final", "music + loudnorm")):
        check(stage in body, f"the canonical finishing path performs {why}")


if __name__ == "__main__":
    test_repair_cannot_touch_an_unauthorized_scene()
    test_repair_cannot_silently_skip_an_authorized_scene()
    test_missing_replacement_asset_fails_closed()
    test_a_replacement_identical_to_the_original_is_refused()
    test_unaffected_scenes_are_proven_unchanged_by_hash()
    test_re_qa_is_measured_on_the_repaired_output_not_the_original()
    test_failing_re_qa_is_reported_not_swallowed()
    test_repair_reassembles_through_the_canonical_finishing_path()
    print("bounded repair adversarial tests: PASS")
