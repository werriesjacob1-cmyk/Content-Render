#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_asset_lineage as L


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label)


def test_lineage_requires_visual_identity_and_renderer():
    good = L.AssetLineageEntry(
        scene_id="1", scene_index=1, visual_intent="hook_proof",
        subject_id="shark_abc123", subject="Greenland shark",
        renderer_kind="authentic_science_video", output_file="s1.mp4", duration_s=4.1,
        selected_asset_ids=("nasa-1",), attributable=True,
    )
    check(not good.validate(), "complete rendered-scene lineage validates")
    bad = L.AssetLineageEntry(
        scene_id="1", scene_index=1, visual_intent="", subject_id="", subject="x",
        renderer_kind="", output_file="s1.mp4", duration_s=4.0,
    )
    check(bool(bad.validate()), "rendered scene without intent/subject/renderer fails closed")


def test_write_lineage_reports_attribution_coverage():
    rows = [
        L.AssetLineageEntry("1", 1, "hook_proof", "a", "A", "legacy_real_video", "s1.mp4", 3.0, attributable=True),
        L.AssetLineageEntry("2", 2, "payoff_proof", "b", "B", "unattributed", "s2.mp4", 3.0, attributable=False),
    ]
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "lineage.json"
        payload = L.write_lineage(rows, p)
        saved = json.loads(p.read_text())
    check(payload["scene_count"] == 2 and payload["attributable_scene_count"] == 1, "coverage counts exact")
    check(payload["all_rendered_scenes_attributable"] is False, "unattributed rendered scene remains visible")
    check(saved["schema"] == "content-render-final-asset-lineage-v1", "lineage persists explicit schema")


def test_legacy_artifact_classification_is_concrete_file_based():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "s2_raw.mp4").write_bytes(b"x")
        kind, names = L.classify_legacy_artifacts(root, 2)
        check(kind == "legacy_real_video" and "s2_raw.mp4" in names, "raw selected footage is classified from actual artifact")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]:
        fn()
    print("quality_asset_lineage tests: PASS")
