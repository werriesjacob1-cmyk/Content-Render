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


def test_manual_plus_one_shot_main_only_read_only_contract():
    text = WF.read_text(encoding="utf-8")
    check("workflow_dispatch:" in text, "certification workflow remains manually dispatchable")
    check("schedule:" not in text and "repository_dispatch:" not in text,
          "certification workflow has no schedule or external trigger")
    check("push:" in text and '".github/quality-certification-trigger"' in text,
          "temporary push bridge is restricted to one inert marker path")
    check("branches:\n      - main" in text, "temporary push bridge is main-only")
    check("github.event_name == 'push'" in text,
          "push bridge is explicit rather than silently bypassing provider acknowledgement")
    check("github.ref == 'refs/heads/main'" in text, "provider-backed certification is main-only")
    check("contents: read" in text and "contents: write" not in text, "token is read-only")
    check("persist-credentials: false" in text, "checkout credentials are not persisted")
    check('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in text, "exact trusted SHA is proved before calls")
    check("github.event_name == 'workflow_dispatch' && inputs.topic_id || 'venus_day'" in text,
          "path-triggered attempt 3 uses the explicit treatment-fit Venus flagship topic")
    check("TIMELINE_TRANSFORMATION" in text and "curated" in text,
          "workflow records why the explicit topic is evidence-dense and structurally compatible")
    check("github.event_name == 'push' || inputs.confirm_free_science_network == 'YES'" in text,
          "path-triggered certification explicitly enables only free authentic-science network")


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
    check("quality_certification_retry.py" in text and "--allow-provider-calls" in text,
          "workflow uses bounded resilient V2.1 certification wrapper")
    check("--max-writer-attempts 3" in text and 'QUALITY_CERTIFICATION_WRITER_ATTEMPTS: "3"' in text,
          "flagship Writer retry budget is explicit and capped in workflow")
    check("quality_certification_generate.py" not in text,
          "workflow cannot bypass resilience wrapper by invoking one-shot generator directly")
    check("quality_science_render.py artifacts/quality_certification/manifest.json" in text,
          "exact sealed manifest is handed to authentic-first deterministic-science renderer")
    check("quality_render_bridge.py artifacts/quality_certification/manifest.json" not in text,
          "workflow cannot bypass deterministic-science wrapper by invoking older bridge directly")
    check("quality_asset_provenance.json" in text and "qa_report.json" in text,
          "legacy viewer-facing QA and scene provenance are retained with MP4")


def test_audio_mastering_gate_is_local_and_load_bearing():
    text = WF.read_text(encoding="utf-8")
    audio_pos = text.index("python quality_audio_qa.py")
    render_pos = text.index("python quality_science_render.py")
    holistic_pos = text.index("python quality_postrender_review.py")
    check(render_pos < audio_pos < holistic_pos, "final encoded audio is measured before holistic visual review")
    block = text.split("Local final-audio mastering QA", 1)[1].split("Independent holistic QA", 1)[0]
    check("secrets." not in block, "audio mastering QA uses no provider secret")
    check("continue-on-error" not in block, "bad final audio remains a red certification condition")
    check("audio_qa_report.json" in text, "measured audio evidence is retained in private package")


def test_independent_holistic_qa_is_scene_aware_load_bearing_and_actionable():
    text = WF.read_text(encoding="utf-8")
    check("python quality_postrender_review.py" in text, "assembled MP4 receives independent modular holistic QA")
    check("--report out/holistic_qa_report.json" in text, "independent holistic verdict is retained")
    check("--repair-plan out/targeted_repair_plan.json" in text, "failed dimensions produce bounded repair targets")
    check("--scene-timeline out/scene_timeline.json" in text, "repair planner receives exact rendered scene boundaries")
    qa_block = text.split("Independent holistic QA + bounded repair targets", 1)[1].split("Collect viewer-facing evidence", 1)[0]
    check("continue-on-error" not in qa_block, "holistic QA failure remains load-bearing")


def test_failed_certification_still_preserves_all_viewer_evidence():
    text = WF.read_text(encoding="utf-8")
    collect_block = text.split("Collect viewer-facing evidence even on QA failure", 1)[1]
    check("if: ${{ always() }}" in collect_block, "artifact collection runs after red render/audio/QA state")
    required = (
        "audio_qa_report.json", "holistic_qa_report.json", "targeted_repair_plan.json",
        "scene_timeline.json", "quality_asset_provenance.json",
    )
    check(all(x in collect_block for x in required), "failed certification preserves audio, visual, timeline, provenance, and repair evidence")
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
    test_manual_plus_one_shot_main_only_read_only_contract()
    test_no_publish_or_write_capability_is_present()
    test_generated_visual_and_paid_voice_side_doors_are_closed()
    test_evidence_bound_generator_and_bridge_are_load_bearing()
    test_audio_mastering_gate_is_local_and_load_bearing()
    test_independent_holistic_qa_is_scene_aware_load_bearing_and_actionable()
    test_failed_certification_still_preserves_all_viewer_evidence()
    test_real_render_dependencies_are_proved_before_execution()
    print("quality certification workflow tests: PASS")
