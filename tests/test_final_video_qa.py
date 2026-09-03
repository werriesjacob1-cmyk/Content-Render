#!/usr/bin/env python3
"""Zero-network regressions for final_video_qa.py."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import final_video_qa as Q  # noqa: E402


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _context():
    return Q.FinalQAContext(
        title="Why the storm has an eye",
        narration=(
            "Warm ocean water feeds the storm. Air rises around the center. "
            "The eye itself can become comparatively calm."
        ),
        scene_intents=(
            "satellite view of hurricane eye",
            "diagram of rising air around eye wall",
            "close view of storm center",
        ),
        factual_subjects=("hurricane", "eye wall", "ocean"),
        expected_duration_s=30,
    )


def _packet(td):
    paths = []
    for i in range(3):
        p = os.path.join(td, f"sheet{i+1}.jpg")
        with open(p, "wb") as f:
            f.write(b"fake-jpeg-" + bytes([i]))
        paths.append(p)
    return Q.SamplePacket(
        video_path=os.path.join(td, "final.mp4"),
        duration_s=30.0,
        timestamps_s=Q.sample_timestamps(30.0),
        frame_paths=tuple(os.path.join(td, f"f{i}.jpg") for i in range(9)),
        sheet_paths=tuple(paths),
    )


def _good_payload(overall=8.2):
    return {
        "overall_score": overall,
        "scores": {
            "hook_visual": 8.0,
            "narration_visual_match": 8.4,
            "scientific_visual_integrity": 9.0,
            "visual_variety": 7.5,
            "pacing": 7.8,
            "caption_legibility": 8.5,
            "continuity": 7.6,
            "payoff_visual": 8.1,
            "ai_artifact_control": 9.0,
        },
        "critical_failures": [],
        "violations": [
            {
                "category": "pacing",
                "severity": "minor",
                "evidence_group": 2,
                "detail": "middle section holds slightly long",
            }
        ],
        "summary": "Strong and visually grounded.",
        "must_fix": [],
    }


def test_temporal_sampling():
    times = Q.sample_timestamps(40.0)
    check(len(times) == 9, "nine temporal samples generated")
    check(times == tuple(sorted(times)), "samples are chronological")
    check(times[0] > 0 and times[-1] < 40, "sampling avoids exact first/last frame")
    check(abs(times[4] - 20.0) < 0.01, "middle sample lands at video midpoint")


def test_prompt_is_holistic_and_evidence_ordered():
    with tempfile.TemporaryDirectory() as td:
        packet = _packet(td)
        prompt = Q.build_qa_prompt(_context(), packet)
    check("left to right" in prompt and "contact sheet 3" in prompt,
          "prompt defines chronological contact-sheet order")
    check("scientific visual integrity" in prompt.lower(),
          "prompt judges scientific visual integrity")
    check("wrong animals/objects" in prompt,
          "prompt explicitly catches wrong generated subject")
    check("cinematic beauty" in prompt,
          "beauty cannot compensate for wrong science")
    check("payoff" in prompt.lower(), "final visual payoff is evaluated")


def test_verdict_gate_hard_floors():
    good = Q.parse_verdict(_good_payload(), "test", "model")
    passed, reasons = Q.mechanical_gate(good)
    check(passed and not reasons, "strong verdict clears mechanical pre-human gate")

    weak = _good_payload(overall=7.4)
    weak["scores"]["pacing"] = 5.8
    verdict = Q.parse_verdict(weak, "test", "model")
    passed, reasons = Q.mechanical_gate(verdict)
    check(not passed, "overall/category floor failure rejects")
    check(any("overall" in r for r in reasons) and any("pacing" in r for r in reasons),
          "gate reports exact failed floors")

    critical = _good_payload()
    critical["critical_failures"] = ["wrong central animal"]
    critical["violations"].append({
        "category": "scientific_subject",
        "severity": "critical",
        "evidence_group": 1,
        "detail": "wrong animal shown",
    })
    verdict = Q.parse_verdict(critical, "test", "model")
    passed, reasons = Q.mechanical_gate(verdict)
    check(not passed and any("critical" in r for r in reasons),
          "critical visual contradiction is an automatic failure")


def test_malformed_verdict_fails_closed():
    bad = _good_payload()
    bad["scores"]["hook_visual"] = 11
    try:
        Q.parse_verdict(bad, "test", "model")
        raise AssertionError("out-of-range score should fail")
    except Q.FinalQAError:
        pass
    check(True, "out-of-range model score is rejected")

    bad = _good_payload()
    bad["violations"][0]["evidence_group"] = 4
    try:
        Q.parse_verdict(bad, "test", "model")
        raise AssertionError("bad evidence group should fail")
    except Q.FinalQAError:
        pass
    check(True, "violation must point to one of three evidence groups")


def test_qwen_contract_strict_schema_three_images():
    with tempfile.TemporaryDirectory() as td:
        packet = _packet(td)
        captured = {}
        old = Q._json_http

        def fake(url, payload, headers, timeout=60):
            captured["url"] = url
            captured["payload"] = payload
            return {
                "choices": [{
                    "message": {"content": json.dumps(_good_payload())}
                }]
            }

        Q._json_http = fake
        try:
            verdict = Q.qa_with_qwen(_context(), packet, api_key="x")
        finally:
            Q._json_http = old

    payload = captured["payload"]
    check(payload["model"] == "qwen/qwen3.8-27b",
          "Qwen QA uses current multimodal model")
    rf = payload["response_format"]
    check(rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True,
          "Qwen verdict is strict-schema constrained")
    content = payload["messages"][0]["content"]
    images = [x for x in content if x.get("type") == "image_url"]
    check(len(images) == 3, "Qwen receives exactly three chronological contact sheets")
    check(verdict.provider == "groq", "Qwen verdict provenance recorded")


def test_gemini_contract_structured_three_images():
    with tempfile.TemporaryDirectory() as td:
        packet = _packet(td)
        captured = {}
        old = Q._json_http

        def fake(url, payload, headers, timeout=60):
            captured["url"] = url
            captured["payload"] = payload
            return {
                "candidates": [{
                    "content": {"parts": [{"text": json.dumps(_good_payload())}]}
                }]
            }

        Q._json_http = fake
        try:
            verdict = Q.qa_with_gemini(_context(), packet, api_key="x")
        finally:
            Q._json_http = old

    payload = captured["payload"]
    check("gemini-3.8-flash" in captured["url"],
          "Gemini QA uses current stable Flash model")
    parts = payload["contents"][0]["parts"]
    images = [x for x in parts if "inline_data" in x]
    check(len(images) == 3, "Gemini receives the same three chronological sheets")
    fmt = payload["generationConfig"]["responseFormat"]["text"]
    check(fmt["mimeType"] == "application/json" and fmt["schema"] == Q.QA_SCHEMA,
          "Gemini verdict uses structured JSON schema")
    check(verdict.provider == "gemini", "Gemini verdict provenance recorded")


def test_no_provider_means_no_synthetic_pass():
    old_g = os.environ.pop("GEMINI_API_KEY", None)
    old_q = os.environ.pop("GROQ_API_KEY", None)
    try:
        with tempfile.TemporaryDirectory() as td:
            got = Q.final_qa_with_fallback(_context(), _packet(td))
        check(got is None, "no evaluator fails closed instead of fabricating QA")
    finally:
        if old_g is not None:
            os.environ["GEMINI_API_KEY"] = old_g
        if old_q is not None:
            os.environ["GROQ_API_KEY"] = old_q


def test_real_ffmpeg_sampling_smoke():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("PASS final-video temporal smoke skipped: ffmpeg/ffprobe unavailable")
        return
    with tempfile.TemporaryDirectory() as td:
        video = os.path.join(td, "fixture.mp4")
        proc = subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=12:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", video,
        ], capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr[-1000:])
        packet = Q.build_sample_packet(video, os.path.join(td, "qa"))
        check(not packet.validate(), "real temporal sample packet validates")
        check(all(os.path.getsize(x) > 500 for x in packet.sheet_paths),
              "three real contact sheets were rendered")
        check(len(packet.frame_paths) == 9, "nine real source frames were extracted")


if __name__ == "__main__":
    test_temporal_sampling()
    test_prompt_is_holistic_and_evidence_ordered()
    test_verdict_gate_hard_floors()
    test_malformed_verdict_fails_closed()
    test_qwen_contract_strict_schema_three_images()
    test_gemini_contract_structured_three_images()
    test_no_provider_means_no_synthetic_pass()
    test_real_ffmpeg_sampling_smoke()
    print("final_video_qa tests: PASS")
