#!/usr/bin/env python3
"""Static zero-network safety checks for private certification workflow."""
from __future__ import annotations

from pathlib import Path

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
    render_step = text.split("Render through authentic-first + deterministic-science certification bridge", 1)[1]
    check("secrets.FAL" not in render_step and "secrets.ELEVEN" not in render_step,
          "render step is not secretly provisioned with disabled paid-generation/voice credentials")


def test_evidence_bound_generator_and_bridge_are_load_bearing():
    text = WF.read_text(encoding="utf-8")
    check("quality_certification_generate.py" in text and "--allow-provider-calls" in text,
          "workflow uses guarded V2.1 certification bundle generator")
    check("quality_science_render.py artifacts/quality_certification/manifest.json" in text,
          "exact sealed manifest is handed to authentic-first deterministic-science renderer")
    check("quality_render_bridge.py artifacts/quality_certification/manifest.json" not in text,
          "workflow cannot bypass deterministic-science wrapper by invoking older bridge directly")
    check("quality_asset_provenance.json" in text and "qa_report.json" in text,
          "legacy viewer-facing QA and scene provenance are retained with MP4")


def test_independent_holistic_qa_is_load_bearing_and_actionable():
    text = WF.read_text(encoding="utf-8")
    review = "python quality_postrender_review.py"
    check(review in text, "assembled MP4 receives independent modular holistic QA")
    check("--report out/holistic_qa_report.json" in text,
          "independent holistic verdict is retained")
    check("--repair-plan out/targeted_repair_plan.json" in text,
          "failed dimensions produce bounded repair targets")
    render_pos = text.index("python quality_science_render.py")
    qa_pos = text.index(review)
    check(render_pos < qa_pos, "holistic QA judges the assembled output, not pre-render plans")
    # The QA step has no continue-on-error: a mechanical fail remains a red
    # certification, while later always() steps preserve evidence for diagnosis.
    qa_block = text.split("Independent holistic QA + bounded repair targets", 1)[1].split("Collect viewer-facing evidence", 1)[0]
    check("continue-on-error" not in qa_block, "holistic QA failure remains load-bearing")


def test_failed_certification_still_preserves_viewer_evidence():
    text = WF.read_text(encoding="utf-8")
    collect_block = text.split("Collect viewer-facing evidence even on QA failure", 1)[1]
    check("if: ${{ always() }}" in collect_block, "artifact collection runs after red QA/render state")
    check("holistic_qa_report.json" in collect_block and "targeted_repair_plan.json" in collect_block,
          "failed-review evidence and repair plan are copied into certification package")
    upload_block = text.split("Upload private certification package", 1)[1]
    check("if: ${{ always() }}" in upload_block, "private artifact upload survives failed QA")


def test_real_render_dependencies_are_proved_before_execution():
    text = WF.read_text(encoding="utf-8")
    render_pos = text.index("python quality_science_render.py")
    ffmpeg_pos = text.index("ffmpeg -version")
    deps_pos = text.index("pip install -r requirements.txt")
    check(ffmpeg_pos < render_pos and deps_pos < render_pos,
          "ffmpeg and Python render dependencies are proven before flagship rendering")


if __name__ == "__main__":
    test_manual_main_only_read_only_contract()
    test_no_publish_or_write_capability_is_present()
    test_generated_visual_and_paid_voice_side_doors_are_closed()
    test_evidence_bound_generator_and_bridge_are_load_bearing()
    test_independent_holistic_qa_is_load_bearing_and_actionable()
    test_failed_certification_still_preserves_viewer_evidence()
    test_real_render_dependencies_are_proved_before_execution()
    print("quality certification workflow tests: PASS")
