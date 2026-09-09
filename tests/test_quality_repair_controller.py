#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_repair_controller as R


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label)


def plan():
    return {
        "targets": [{
            "category": "narration_visual_match", "severity": "major",
            "affected_scene_ids": ["2"], "start_s": 3.0, "end_s": 6.0,
            "recommended_action": "replace scene 2 visual only",
            "preserve": ["accepted Writer V2.1 narration", "sealed source claim IDs", "unaffected scenes"],
            "automatic_repair_authorized": False,
        }]
    }


def test_target_validation_preserves_writer_and_claims():
    tasks = R.tasks_from_plan(plan())
    check(len(tasks) == 1 and tasks[0].affected_scene_ids == ("2",), "bounded scene target loads")
    bad = plan(); bad["targets"][0]["preserve"] = ["keep style"]
    try:
        R.tasks_from_plan(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("repair without Writer/claim preservation must fail")


def test_apply_replacement_changes_only_target():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scenes = {}
        for i in range(1, 4):
            p = root / f"s{i}.mp4"; p.write_bytes((f"scene-{i}" * 100).encode()); scenes[str(i)] = p
        replacement = root / "replacement.mp4"; replacement.write_bytes(b"replacement" * 200)
        output = root / "final.mp4"
        def assemble(files, dest):
            with open(dest, "wb") as f:
                for p in files:
                    f.write(Path(p).read_bytes())
        evidence = R.execute_replacements(
            plan=plan(), scene_files=scenes, replacements={"2": replacement},
            output_scene_dir=root / "new", output_video=output, assemble=assemble,
        )
        check(evidence["targeted_scene_changed"] == {"2": True}, "target scene must actually change")
        check(all(x["unchanged"] for x in evidence["unaffected_scene_preservation"].values()), "all non-target scenes stay byte-identical")
        check(evidence["provider_calls_made"] == 0 and evidence["provider_repair_authorized"] is False,
              "controller cannot silently authorize a paid/provider repair")


def test_replacement_set_must_exactly_match_targets():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); p = root / "s1.mp4"; p.write_bytes(b"x" * 2000)
        try:
            R.execute_replacements(plan=plan(), scene_files={"1": p}, replacements={},
                                   output_scene_dir=root / "new", output_video=root / "f.mp4",
                                   assemble=lambda files, dest: shutil.copyfile(files[0], dest))
        except ValueError:
            pass
        else:
            raise AssertionError("partial/extra replacement set must fail closed")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]:
        fn()
    print("quality_repair_controller tests: PASS")
