#!/usr/bin/env python3
"""Static zero-network safety checks for private certification workflow."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "quality_certification_render.yml"


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_manual_main_only_read_only_contract():
    text = WF.read_text(encoding="utf-8")
    check("workflow_dispatch:" in text, "certification workflow is manually dispatchable")
    check("schedule:" not in text and "repository_dispatch:" not in text,
          "certification workflow has no unattended or external trigger")
    check("github.ref == 'refs/heads/main'" in text, "provider-backed certification is main-only")
    check("contents: read" in text and "contents: write" not in text, "token is read-only")
    check("persist-credentials: false" in text, "checkout credentials are not persisted")
    check('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in text, "exact trusted SHA is proved before calls")


def test_no_publish_or_write_capability_is_present():
    text = WF.read_text(encoding="utf-8")
    lowered = text.lower()
    forbidden = (
        "actions/create-release", "softprops/action-gh-release", "publer_api_key",
        "buffer", "repository_dispatch", "git push", "gh release", "deploy-pages",
    )
    hits = [x for x in forbidden if x in lowered]
    check(not hits, f"workflow exposes no publish/write lane: {hits}")
    check("actions/upload-artifact@v4" in text, "finished video exits only as private Actions artifact")


def test_generated_visual_and_paid_voice_side_doors_are_closed():
    text = WF.read_text(encoding="utf-8")
    check('AI_IMAGE: "0"' in text, "legacy Pollinations/Imagen image fallback disabled")
    check('FAL_KEY: ""' in text and 'FAL_API_KEY: ""' in text, "legacy direct FAL generation disabled")
    check('ELEVENLABS_API_KEY: ""' in text, "certification cannot silently spend ElevenLabs")
    render_step = text.split("Render through quality-first certification bridge", 1)[1]
    check("secrets.FAL" not in render_step and "secrets.ELEVEN" not in render_step,
          "render step is not secretly provisioned with disabled paid-generation/voice credentials")


def test_evidence_bound_generator_and_bridge_are_load_bearing():
    text = WF.read_text(encoding="utf-8")
    check("quality_certification_generate.py" in text and "--allow-provider-calls" in text,
          "workflow uses guarded V2.1 certification bundle generator")
    check("quality_render_bridge.py artifacts/quality_certification/manifest.json" in text,
          "exact sealed manifest is handed to quality-first renderer")
    check("writer_evidence.json" not in text or "artifacts/quality_certification" in text,
          "evidence bundle remains inside uploaded certification package")
    check("quality_asset_provenance.json" in text and "qa_report.json" in text,
          "viewer-facing QA and scene provenance are retained with MP4")


if __name__ == "__main__":
    test_manual_main_only_read_only_contract()
    test_no_publish_or_write_capability_is_present()
    test_generated_visual_and_paid_voice_side_doors_are_closed()
    test_evidence_bound_generator_and_bridge_are_load_bearing()
    print("quality certification workflow tests: PASS")
