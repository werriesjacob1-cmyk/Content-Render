#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label)


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_render_schedule_spend_is_opt_in_during_legacy_transition():
    y = text(".github/workflows/render.yml")
    check("LEGACY_SCHEDULED_GENERATION_ENABLED == 'true'" in y, "scheduled legacy render spend requires explicit repo variable")
    check("github.event_name != 'schedule'" in y, "manual/repository dispatch remain available independently")


def test_buffer_schedule_spend_is_opt_in_and_queue_is_stamped():
    y = text(".github/workflows/buffer.yml")
    check("LEGACY_SCHEDULED_GENERATION_ENABLED == 'true'" in y, "scheduled legacy buffer spend requires explicit repo variable")
    check("quality_queue_contract.py --stamp" in y, "buffered manifests receive explicit writer/certification identity")
    check("quality_production_generate.py --enqueue" in y, "buffer uses capability-aware provider wrapper")


def test_render_dequeue_is_version_compatible_and_live_generation_guarded():
    y = text(".github/workflows/render.yml")
    check("quality_queue_contract.py" in y and "--required-writer" in y and "--required-cert" in y,
          "render can only dequeue inventory compatible with active factory contract")
    check("quality_production_generate.py manifest.json" in y, "live unattended generation uses capability-aware wrapper")


def test_render_prerequisites_use_single_combined_install_path():
    y = text(".github/workflows/render.yml")
    check("fc-match" in y, "production uses robust fc-match font probe")
    check("ffmpeg fonts-dejavu-core" in y, "ffmpeg and DejaVu install together")
    check("fc-list | grep -qi dejavu" not in y, "old SIGPIPE-prone/slow font probe removed")
    check(y.count("apt-get update") == 1, "production prerequisite step has at most one apt update")


def test_private_learning_is_cache_only_and_artifact_visible():
    y = text(".github/workflows/quality_certification_render.yml")
    check("permissions:\n  contents: read" in y, "private flagship keeps repository read-only permission")
    check("quality_learning_capture.py" in y, "private attempt is persisted into learning ledger")
    check("actions/cache/restore@v4" in y and "actions/cache/save@v4" in y, "learning survives runs without repo commits")
    check("quality_learning.jsonl" in y, "learning ledger snapshot enters private evidence package")
    check("visual_bible.json" in y and "final_asset_lineage.json" in y, "visual continuity and actual asset lineage enter artifact")


def test_publishing_kill_switch_boundaries_unchanged():
    y = text(".github/workflows/render.yml")
    check("vars.AUTO_PUBLISH_ENABLED == 'true'" in y, "Release/Publer remain exact-true gated")
    check("certification_only != 'true'" in y, "manual certification remains independently non-publishing")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]:
        fn()
    print("production transition contract tests: PASS")
