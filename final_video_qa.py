"""Holistic final-video QA for Content Render.

This module inspects the assembled MP4 rather than trusting scene-level checks.
It is intentionally isolated from publishing/render defaults.  The quality
contract is:

  finished video -> deterministic temporal sampling -> multimodal review
                 -> mechanical acceptance gate -> human review

The fallback path samples nine moments and groups them into three chronological
contact sheets so Groq Qwen 3.8 can inspect the full arc within its three-image
limit.  Gemini 3.8 Flash uses the same evidence packet for comparable results.

No provider call is made unless an API key is explicitly present and the caller
invokes a provider.  Sampling/render helpers are local FFmpeg only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import base64
import json
import math
import os
import re
import subprocess
import tempfile
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GEMINI_QA_MODEL = os.getenv("GEMINI_FINAL_QA_MODEL", "gemini-3.8-flash")
GROQ_QA_MODEL = os.getenv("GROQ_FINAL_QA_MODEL", "qwen/qwen3.8-27b")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_QA_MODEL}:generateContent"
)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SAMPLE_FRACTIONS = (0.06, 0.17, 0.28, 0.39, 0.50, 0.61, 0.72, 0.83, 0.94)
SHEETS = ((0, 1, 2), (3, 4, 5), (6, 7, 8))

QUALITY_FLOOR = 7.5
DIMENSION_FLOOR = 6.0


class FinalQAError(RuntimeError):
    pass


@dataclass(frozen=True)
class FinalQAContext:
    title: str
    narration: str
    scene_intents: tuple[str, ...] = ()
    factual_subjects: tuple[str, ...] = ()
    expected_duration_s: float | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.title.strip():
            errors.append("title required")
        if not self.narration.strip():
            errors.append("narration required")
        if self.expected_duration_s is not None:
            try:
                d = float(self.expected_duration_s)
                if not math.isfinite(d) or d <= 0:
                    errors.append("expected_duration_s must be finite and > 0")
            except (TypeError, ValueError):
                errors.append("expected_duration_s must be numeric")
        return errors


@dataclass(frozen=True)
class SamplePacket:
    video_path: str
    duration_s: float
    timestamps_s: tuple[float, ...]
    frame_paths: tuple[str, ...]
    sheet_paths: tuple[str, ...]

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.duration_s <= 0:
            errors.append("duration_s must be > 0")
        if len(self.timestamps_s) != 9:
            errors.append("exactly 9 timestamps required")
        if len(self.frame_paths) != 9:
            errors.append("exactly 9 frame paths required")
        if len(self.sheet_paths) != 3:
            errors.append("exactly 3 contact sheets required")
        if tuple(sorted(self.timestamps_s)) != self.timestamps_s:
            errors.append("timestamps must be monotonic")
        if self.timestamps_s and (
            self.timestamps_s[0] < 0 or self.timestamps_s[-1] > self.duration_s + 0.001
        ):
            errors.append("timestamps outside video duration")
        return errors


@dataclass(frozen=True)
class QAViolation:
    category: str
    severity: str
    evidence_group: int
    detail: str


@dataclass(frozen=True)
class FinalQAVerdict:
    overall_score: float
    hook_visual: float
    narration_visual_match: float
    scientific_visual_integrity: float
    visual_variety: float
    pacing: float
    caption_legibility: float
    continuity: float
    payoff_visual: float
    ai_artifact_control: float
    critical_failures: tuple[str, ...]
    violations: tuple[QAViolation, ...]
    summary: str
    must_fix: tuple[str, ...]
    provider: str
    model: str

    def scores(self) -> Mapping[str, float]:
        return {
            "hook_visual": self.hook_visual,
            "narration_visual_match": self.narration_visual_match,
            "scientific_visual_integrity": self.scientific_visual_integrity,
            "visual_variety": self.visual_variety,
            "pacing": self.pacing,
            "caption_legibility": self.caption_legibility,
            "continuity": self.continuity,
            "payoff_visual": self.payoff_visual,
            "ai_artifact_control": self.ai_artifact_control,
        }


QA_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "overall_score": {"type": "number", "minimum": 0, "maximum": 10},
        "scores": {
            "type": "object",
            "properties": {
                "hook_visual": {"type": "number", "minimum": 0, "maximum": 10},
                "narration_visual_match": {"type": "number", "minimum": 0, "maximum": 10},
                "scientific_visual_integrity": {"type": "number", "minimum": 0, "maximum": 10},
                "visual_variety": {"type": "number", "minimum": 0, "maximum": 10},
                "pacing": {"type": "number", "minimum": 0, "maximum": 10},
                "caption_legibility": {"type": "number", "minimum": 0, "maximum": 10},
                "continuity": {"type": "number", "minimum": 0, "maximum": 10},
                "payoff_visual": {"type": "number", "minimum": 0, "maximum": 10},
                "ai_artifact_control": {"type": "number", "minimum": 0, "maximum": 10},
            },
            "required": [
                "hook_visual",
                "narration_visual_match",
                "scientific_visual_integrity",
                "visual_variety",
                "pacing",
                "caption_legibility",
                "continuity",
                "payoff_visual",
                "ai_artifact_control",
            ],
            "additionalProperties": False,
        },
        "critical_failures": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "violations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "major", "minor"],
                    },
                    "evidence_group": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 3,
                    },
                    "detail": {"type": "string"},
                },
                "required": ["category", "severity", "evidence_group", "detail"],
                "additionalProperties": False,
            },
            "maxItems": 15,
        },
        "summary": {"type": "string"},
        "must_fix": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 10,
        },
    },
    "required": [
        "overall_score",
        "scores",
        "critical_failures",
        "violations",
        "summary",
        "must_fix",
    ],
    "additionalProperties": False,
}


def sample_timestamps(duration_s: float) -> tuple[float, ...]:
    """Nine monotonic times avoiding fragile exact first/last frames."""
    d = float(duration_s)
    if not math.isfinite(d) or d <= 0:
        raise ValueError("duration must be finite and > 0")
    # For sub-second clips, clamping can collapse positions.  Such clips are
    # not valid final Content Render outputs, but keep the helper deterministic.
    vals = [max(0.0, min(d, d * f)) for f in SAMPLE_FRACTIONS]
    return tuple(round(v, 3) for v in vals)


def ffprobe_duration(path: str) -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", path,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise FinalQAError(f"ffprobe failed: {proc.stderr[-800:]}")
    try:
        value = float(proc.stdout.strip())
    except ValueError as exc:
        raise FinalQAError("ffprobe returned non-numeric duration") from exc
    if not math.isfinite(value) or value <= 0:
        raise FinalQAError("video duration is invalid")
    return value


def frame_command(video_path: str, timestamp_s: float, dest: str) -> list[str]:
    return [
        "ffmpeg", "-y",
        "-ss", f"{timestamp_s:.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-vf", "scale=360:640:force_original_aspect_ratio=decrease,"
               "pad=360:640:(ow-iw)/2:(oh-ih)/2:black",
        "-q:v", "3",
        dest,
    ]


def sheet_command(frame_paths: Sequence[str], dest: str) -> list[str]:
    if len(frame_paths) != 3:
        raise ValueError("contact sheet requires exactly 3 frames")
    return [
        "ffmpeg", "-y",
        "-i", frame_paths[0],
        "-i", frame_paths[1],
        "-i", frame_paths[2],
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3[v]",
        "-map", "[v]",
        "-frames:v", "1",
        "-q:v", "3",
        dest,
    ]


def _run(cmd: Sequence[str], timeout: int = 45) -> None:
    proc = subprocess.run(
        list(cmd), capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise FinalQAError(f"command failed: {proc.stderr[-1200:]}")


def build_sample_packet(video_path: str, work_dir: str) -> SamplePacket:
    """Extract nine frames + three ordered triptych contact sheets."""
    if not os.path.exists(video_path) or os.path.getsize(video_path) < 1000:
        raise FinalQAError("final video missing or too small")
    duration = ffprobe_duration(video_path)
    times = sample_timestamps(duration)
    os.makedirs(work_dir, exist_ok=True)

    frames: list[str] = []
    for idx, ts in enumerate(times):
        path = os.path.join(work_dir, f"qa_frame_{idx+1:02d}_{ts:.3f}.jpg")
        _run(frame_command(video_path, ts, path))
        if not os.path.exists(path) or os.path.getsize(path) < 200:
            raise FinalQAError(f"frame extraction failed at {ts:.3f}s")
        frames.append(path)

    sheets: list[str] = []
    for group_no, idxs in enumerate(SHEETS, 1):
        path = os.path.join(work_dir, f"qa_sheet_{group_no}.jpg")
        group = [frames[i] for i in idxs]
        _run(sheet_command(group, path))
        if not os.path.exists(path) or os.path.getsize(path) < 500:
            raise FinalQAError(f"contact sheet {group_no} was not produced")
        sheets.append(path)

    packet = SamplePacket(
        video_path=video_path,
        duration_s=duration,
        timestamps_s=times,
        frame_paths=tuple(frames),
        sheet_paths=tuple(sheets),
    )
    errors = packet.validate()
    if errors:
        raise FinalQAError("; ".join(errors))
    return packet


def _compact(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:limit]


def build_qa_prompt(context: FinalQAContext, packet: SamplePacket) -> str:
    errors = context.validate() + packet.validate()
    if errors:
        raise ValueError("; ".join(errors))
    groups = []
    for group_no, idxs in enumerate(SHEETS, 1):
        times = ", ".join(f"{packet.timestamps_s[i]:.2f}s" for i in idxs)
        groups.append(f"contact sheet {group_no} contains chronological frames at {times}")
    scene_text = "; ".join(_compact(x, 120) for x in context.scene_intents[:12])
    subjects = ", ".join(_compact(x, 80) for x in context.factual_subjects[:12])
    expected = (
        f"{float(context.expected_duration_s):.2f}s"
        if context.expected_duration_s is not None else "not supplied"
    )
    return (
        "You are the final independent QA editor for a vertical science video. "
        "Judge the finished viewer experience, not the sophistication of the tools. "
        "The three images are chronological contact sheets; within each sheet, read left to right. "
        + " ".join(groups)
        + "\n\nTITLE: " + _compact(context.title, 180)
        + "\nEXPECTED DURATION: " + expected
        + "\nACTUAL DURATION: " + f"{packet.duration_s:.2f}s"
        + "\nNARRATION: " + _compact(context.narration, 6500)
        + ("\nSCENE INTENTS: " + scene_text if scene_text else "")
        + ("\nFACTUAL SUBJECTS: " + subjects if subjects else "")
        + "\n\nScore 0-10 on: hook visual strength in the opening, narration/visual match, "
          "scientific visual integrity, visual variety (penalize repetitive wallpaper), pacing, "
          "caption legibility, continuity, whether the visual payoff actually lands, and control "
          "of AI artifacts. Look specifically for wrong animals/objects, impossible anatomy, "
          "garbled baked-in text, irrelevant stock, repeated subjects, dead shots, confusing "
          "diagrams, visually unsupported narration, awkward transitions, captions obscuring "
          "important evidence, and a payoff that is only spoken rather than shown. "
          "Do not reward cinematic beauty when the science subject is wrong. "
          "Critical failures include a visually false scientific claim, wrong central subject, "
          "severe generated anatomy/object corruption, prominent unreadable baked-in text, or "
          "a material narration/visual contradiction. Be demanding: this is a human-review-first "
          "publishing gate, not a completion check."
    )


def _image_parts(paths: Sequence[str], *, groq: bool) -> list[Mapping[str, Any]]:
    if len(paths) != 3:
        raise ValueError("QA provider expects exactly three contact sheets")
    out: list[Mapping[str, Any]] = []
    for path in paths:
        with open(path, "rb") as f:
            raw = f.read()
        b64 = base64.b64encode(raw).decode("ascii")
        if groq:
            out.append({
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + b64},
            })
        else:
            out.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": b64,
                }
            })
    return out


def _json_http(
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout: int = 60,
) -> Mapping[str, Any]:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **dict(headers)},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        if not isinstance(obj, Mapping):
            raise FinalQAError("provider returned non-object JSON")
        return obj
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:600]
        except Exception:
            pass
        raise FinalQAError(f"HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise FinalQAError(f"{type(exc).__name__}: {exc}") from exc


def _validate_numeric(value: Any, field_name: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise FinalQAError(f"{field_name} is not numeric") from exc
    if not math.isfinite(x) or not 0 <= x <= 10:
        raise FinalQAError(f"{field_name} outside 0..10")
    return x


def parse_verdict(payload: Mapping[str, Any], provider: str, model: str) -> FinalQAVerdict:
    scores = payload.get("scores")
    if not isinstance(scores, Mapping):
        raise FinalQAError("missing scores object")
    fields = (
        "hook_visual",
        "narration_visual_match",
        "scientific_visual_integrity",
        "visual_variety",
        "pacing",
        "caption_legibility",
        "continuity",
        "payoff_visual",
        "ai_artifact_control",
    )
    vals = {name: _validate_numeric(scores.get(name), name) for name in fields}
    overall = _validate_numeric(payload.get("overall_score"), "overall_score")

    critical_raw = payload.get("critical_failures")
    if not isinstance(critical_raw, list):
        raise FinalQAError("critical_failures must be a list")
    critical = tuple(_compact(str(x), 500) for x in critical_raw if _compact(str(x), 500))

    violations_raw = payload.get("violations")
    if not isinstance(violations_raw, list):
        raise FinalQAError("violations must be a list")
    violations: list[QAViolation] = []
    for row in violations_raw:
        if not isinstance(row, Mapping):
            raise FinalQAError("violation row is not an object")
        severity = str(row.get("severity") or "")
        if severity not in {"critical", "major", "minor"}:
            raise FinalQAError("invalid violation severity")
        try:
            group = int(row.get("evidence_group"))
        except (TypeError, ValueError) as exc:
            raise FinalQAError("invalid violation evidence_group") from exc
        if group not in {1, 2, 3}:
            raise FinalQAError("violation evidence_group outside 1..3")
        violations.append(QAViolation(
            category=_compact(str(row.get("category") or ""), 100),
            severity=severity,
            evidence_group=group,
            detail=_compact(str(row.get("detail") or ""), 600),
        ))

    must_raw = payload.get("must_fix")
    if not isinstance(must_raw, list):
        raise FinalQAError("must_fix must be a list")

    return FinalQAVerdict(
        overall_score=overall,
        critical_failures=critical,
        violations=tuple(violations),
        summary=_compact(str(payload.get("summary") or ""), 1500),
        must_fix=tuple(_compact(str(x), 500) for x in must_raw if _compact(str(x), 500)),
        provider=provider,
        model=model,
        **vals,
    )


def mechanical_gate(verdict: FinalQAVerdict) -> tuple[bool, tuple[str, ...]]:
    """Hard publication-readiness gate; human review is still required after pass."""
    reasons: list[str] = []
    if verdict.critical_failures:
        reasons.append(f"{len(verdict.critical_failures)} critical failure(s)")
    if verdict.overall_score < QUALITY_FLOOR:
        reasons.append(
            f"overall {verdict.overall_score:.2f} below {QUALITY_FLOOR:.2f}"
        )
    for name, score in verdict.scores().items():
        if score < DIMENSION_FLOOR:
            reasons.append(f"{name} {score:.2f} below {DIMENSION_FLOOR:.2f}")
    if any(v.severity == "critical" for v in verdict.violations):
        reasons.append("critical evidence violation present")
    return (not reasons, tuple(reasons))


def qa_with_qwen(
    context: FinalQAContext,
    packet: SamplePacket,
    api_key: str | None = None,
) -> FinalQAVerdict:
    key = api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")
    if not key:
        raise FinalQAError("GROQ_API_KEY is not configured")
    prompt = build_qa_prompt(context, packet)
    content: list[Mapping[str, Any]] = [{"type": "text", "text": prompt}]
    content.extend(_image_parts(packet.sheet_paths, groq=True))
    payload = {
        "model": GROQ_QA_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "reasoning_effort": "none",
        "max_completion_tokens": 1000,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "final_video_qa",
                "strict": True,
                "schema": QA_SCHEMA,
            },
        },
    }
    raw = _json_http(
        GROQ_URL,
        payload,
        {"Authorization": f"Bearer {key}"},
    )
    try:
        text = raw["choices"][0]["message"]["content"]
        obj = json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise FinalQAError("Qwen returned no parseable structured verdict") from exc
    if not isinstance(obj, Mapping):
        raise FinalQAError("Qwen verdict is not an object")
    return parse_verdict(obj, "groq", GROQ_QA_MODEL)


def qa_with_gemini(
    context: FinalQAContext,
    packet: SamplePacket,
    api_key: str | None = None,
) -> FinalQAVerdict:
    key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise FinalQAError("GEMINI_API_KEY is not configured")
    prompt = build_qa_prompt(context, packet)
    parts: list[Mapping[str, Any]] = [{"text": prompt}]
    parts.extend(_image_parts(packet.sheet_paths, groq=False))
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "responseFormat": {
                "text": {
                    "mimeType": "application/json",
                    "schema": QA_SCHEMA,
                }
            },
        },
    }
    raw = _json_http(
        GEMINI_URL,
        payload,
        {"x-goog-api-key": key},
    )
    try:
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        obj = json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise FinalQAError("Gemini returned no parseable structured verdict") from exc
    if not isinstance(obj, Mapping):
        raise FinalQAError("Gemini verdict is not an object")
    return parse_verdict(obj, "gemini", GEMINI_QA_MODEL)


def final_qa_with_fallback(
    context: FinalQAContext,
    packet: SamplePacket,
) -> FinalQAVerdict | None:
    """Gemini first, Qwen fallback, fail closed (None) when neither can judge."""
    if os.getenv("GEMINI_API_KEY", ""):
        try:
            return qa_with_gemini(context, packet)
        except Exception as exc:
            print(f"[final-qa] Gemini unavailable: {exc}")
    if os.getenv("GROQ_API_KEY", ""):
        try:
            return qa_with_qwen(context, packet)
        except Exception as exc:
            print(f"[final-qa] Qwen unavailable: {exc}")
    return None


def verdict_report(verdict: FinalQAVerdict) -> Mapping[str, Any]:
    passed, reasons = mechanical_gate(verdict)
    return {
        "provider": verdict.provider,
        "model": verdict.model,
        "overall_score": verdict.overall_score,
        "scores": dict(verdict.scores()),
        "critical_failures": list(verdict.critical_failures),
        "violations": [
            {
                "category": v.category,
                "severity": v.severity,
                "evidence_group": v.evidence_group,
                "detail": v.detail,
            }
            for v in verdict.violations
        ],
        "summary": verdict.summary,
        "must_fix": list(verdict.must_fix),
        "mechanical_pass": passed,
        "mechanical_reasons": list(reasons),
        "human_review_required": True,
    }
