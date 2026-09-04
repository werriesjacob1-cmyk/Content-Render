#!/usr/bin/env python3
"""Modular per-asset vision gateway for the Content Render quality stack.

This module intentionally does NOT replace the existing Gemini code in main.py yet.
It provides a clean Qwen 3.8 multimodal backend that the integration orchestrator
can call for generated still/video verification.  The contract is fail-closed:
no key, disabled vision, malformed response, or provider failure returns None.

No network call occurs merely by importing this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
import urllib.error
import urllib.request
from typing import Mapping, Sequence, Any

GROQ_VISION_URL = "https://api.groq.com/openai/v1/chat/completions"
QWEN_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")


@dataclass(frozen=True)
class VisionVerdict:
    score: int
    literal_subject_match: bool
    anatomy_or_object_ok: bool
    garbled_text: bool
    watermark_or_logo: bool
    unsafe_or_unusable: bool
    reason: str
    provider: str = "groq"
    model: str = QWEN_VISION_MODEL

    @property
    def production_eligible(self) -> bool:
        return bool(
            self.score >= 8
            and self.literal_subject_match
            and self.anatomy_or_object_ok
            and not self.garbled_text
            and not self.watermark_or_logo
            and not self.unsafe_or_unusable
        )


VISION_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 10},
        "literal_subject_match": {"type": "boolean"},
        "anatomy_or_object_ok": {"type": "boolean"},
        "garbled_text": {"type": "boolean"},
        "watermark_or_logo": {"type": "boolean"},
        "unsafe_or_unusable": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": [
        "score",
        "literal_subject_match",
        "anatomy_or_object_ok",
        "garbled_text",
        "watermark_or_logo",
        "unsafe_or_unusable",
        "reason",
    ],
    "additionalProperties": False,
}


def enabled() -> bool:
    return os.getenv("VISION_JUDGE", "1").strip().lower() not in {"0", "false", "off", "no"}


def backend_status() -> dict:
    return {
        "qwen": {
            "model": QWEN_VISION_MODEL,
            "available": bool(enabled() and os.getenv("GROQ_API_KEY", "")),
            "max_images_per_call": 3,
        },
        "gemini_existing_main": {
            "available": bool(enabled() and os.getenv("GEMINI_API_KEY", "")),
            "delegated": True,
            "note": "existing main.py Gemini path remains first-choice until modular migration",
        },
    }


def _request_qwen(prompt: str, image_blobs: Sequence[bytes], api_key: str, timeout_s: int = 45) -> Mapping[str, Any] | None:
    if not prompt.strip() or not image_blobs or not api_key:
        return None
    content: list[dict] = [{"type": "text", "text": prompt.strip()}]
    for raw in list(image_blobs)[:3]:
        if not raw:
            continue
        content.append({
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")},
        })
    if len(content) < 2:
        return None
    body = {
        "model": QWEN_VISION_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_completion_tokens": 320,
        "reasoning_effort": "none",
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "asset_vision_verdict", "strict": True, "schema": VISION_SCHEMA},
        },
    }
    req = urllib.request.Request(
        GROQ_VISION_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "content-render/quality-stack",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = payload["choices"][0]["message"].get("content") or ""
        obj = json.loads(text)
        return obj if isinstance(obj, Mapping) else None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError, TypeError):
        return None


def qwen_asset_verdict(intent: str, image_blobs: Sequence[bytes], api_key: str | None = None) -> VisionVerdict | None:
    """Judge up to three frames from one asset; fail closed on uncertainty.

    Generated video callers should pass early/middle/late frames. Generated still
    callers pass one image. This function never silently treats provider failure
    as approval.
    """
    if not enabled():
        return None
    key = api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")
    if not key:
        return None
    prompt = (
        "You are the independent visual safety reviewer for a short science video. "
        f"The asset is supposed to literally show: {intent!r}. "
        "Judge only what is visible. Penalize wrong species/objects, impossible or broken anatomy, "
        "subject mutation across frames, unrelated CGI, baked-in gibberish text, watermarks/logos, "
        "or any frame that contradicts the intended science. Score 8-10 only when the literal subject "
        "is clear and the asset is clean enough to use in a final video. Do not be generous."
    )
    obj = _request_qwen(prompt, image_blobs, key)
    if not isinstance(obj, Mapping):
        return None
    try:
        return VisionVerdict(
            score=max(0, min(10, int(obj["score"]))),
            literal_subject_match=bool(obj["literal_subject_match"]),
            anatomy_or_object_ok=bool(obj["anatomy_or_object_ok"]),
            garbled_text=bool(obj["garbled_text"]),
            watermark_or_logo=bool(obj["watermark_or_logo"]),
            unsafe_or_unusable=bool(obj["unsafe_or_unusable"]),
            reason=str(obj["reason"] or "").strip(),
        )
    except (KeyError, TypeError, ValueError):
        return None
