#!/usr/bin/env python3
"""Append-only learning ledger for Content Render quality manufacturing.

This is intentionally separate from ``memory_science.json``. Operational memory
may stay tiny and mutable for recent-topic dedup; this ledger is durable evidence
about attempts, treatments, defects, repairs, QA, and human verdicts.

The module is stdlib-only, provider-free, and safe to import from private
certification, selection, and later production paths.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "content-render-learning-v1"
DEFAULT_PATH = os.getenv("CONTENT_RENDER_LEARNING_LEDGER", "quality_learning.jsonl")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_list(values: Iterable[Any] | None) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return tuple(out)


def stable_attempt_id(*parts: Any) -> str:
    payload = "\x1f".join(str(x or "") for x in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class LearningRecord:
    attempt_id: str
    topic_id: str
    treatment: str = ""
    stage: str = "writer"
    status: str = "failed"  # attempted | failed | accepted | rendered | certified | rejected
    created_at: str = field(default_factory=_utc_now)
    writer_version: str = "writer_v2.1"
    certification_version: str = "private_flagship_v1"
    provider: str = ""
    model: str = ""
    failure_classes: tuple[str, ...] = ()
    repair_types: tuple[str, ...] = ()
    scene_ids: tuple[str, ...] = ()
    human_verdict: str = ""
    score: float | None = None
    notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.attempt_id.strip():
            errors.append("attempt_id required")
        if not self.topic_id.strip():
            errors.append("topic_id required")
        if self.status not in {"attempted", "failed", "accepted", "rendered", "certified", "rejected"}:
            errors.append(f"unsupported status {self.status!r}")
        if self.stage not in {"selection", "writer", "render", "qa", "human", "production"}:
            errors.append(f"unsupported stage {self.stage!r}")
        if self.human_verdict and self.human_verdict not in {
            "definitely_post", "probably_post", "borderline", "reject"
        }:
            errors.append("invalid human_verdict")
        if self.score is not None:
            try:
                score = float(self.score)
            except (TypeError, ValueError):
                errors.append("score must be numeric")
            else:
                if not (0.0 <= score <= 10.0):
                    errors.append("score must be 0..10")
        return errors

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema"] = SCHEMA
        payload["failure_classes"] = list(self.failure_classes)
        payload["repair_types"] = list(self.repair_types)
        payload["scene_ids"] = list(self.scene_ids)
        payload["metadata"] = dict(self.metadata)
        return payload


def record_from_mapping(data: Mapping[str, Any]) -> LearningRecord:
    if str(data.get("schema") or SCHEMA) != SCHEMA:
        raise ValueError(f"unsupported learning schema {data.get('schema')!r}")
    rec = LearningRecord(
        attempt_id=str(data.get("attempt_id") or "").strip(),
        topic_id=str(data.get("topic_id") or "").strip(),
        treatment=str(data.get("treatment") or "").strip(),
        stage=str(data.get("stage") or "writer").strip(),
        status=str(data.get("status") or "failed").strip(),
        created_at=str(data.get("created_at") or _utc_now()).strip(),
        writer_version=str(data.get("writer_version") or "writer_v2.1").strip(),
        certification_version=str(data.get("certification_version") or "private_flagship_v1").strip(),
        provider=str(data.get("provider") or "").strip(),
        model=str(data.get("model") or "").strip(),
        failure_classes=_clean_list(data.get("failure_classes") or ()),
        repair_types=_clean_list(data.get("repair_types") or ()),
        scene_ids=_clean_list(data.get("scene_ids") or ()),
        human_verdict=str(data.get("human_verdict") or "").strip(),
        score=(float(data["score"]) if data.get("score") is not None else None),
        notes=str(data.get("notes") or "").strip(),
        metadata=dict(data.get("metadata") or {}),
    )
    errors = rec.validate()
    if errors:
        raise ValueError("; ".join(errors))
    return rec


def read_records(path: str | Path = DEFAULT_PATH, *, strict: bool = True) -> list[LearningRecord]:
    p = Path(path)
    if not p.exists():
        return []
    records: list[LearningRecord] = []
    for lineno, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
            if not isinstance(obj, Mapping):
                raise ValueError("row is not an object")
            records.append(record_from_mapping(obj))
        except Exception as exc:
            if strict:
                raise ValueError(f"{p}:{lineno}: {exc}") from exc
    return records


def append_once(record: LearningRecord, path: str | Path = DEFAULT_PATH) -> bool:
    errors = record.validate()
    if errors:
        raise ValueError("; ".join(errors))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = {r.attempt_id for r in read_records(p, strict=True)}
    if record.attempt_id in existing:
        return False
    line = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    return True


def recent_treatments(records: Sequence[LearningRecord], n: int = 6) -> list[str]:
    vals: list[str] = []
    for rec in records[-max(0, int(n)) :]:
        if rec.treatment:
            vals.append(rec.treatment)
    return vals


def failed_pair_counts(records: Sequence[LearningRecord]) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for rec in records:
        if rec.status in {"failed", "rejected"} and rec.topic_id and rec.treatment:
            key = (rec.topic_id, rec.treatment)
            out[key] = out.get(key, 0) + 1
    return out


def compact_lessons(
    records: Sequence[LearningRecord],
    *,
    topic_id: str = "",
    treatment: str = "",
    max_items: int = 8,
) -> dict[str, Any]:
    """Return bounded deterministic lessons, never raw unbounded history."""
    relevant = [
        r for r in records
        if (not topic_id or r.topic_id == topic_id)
        and (not treatment or r.treatment == treatment)
    ]
    if not relevant and topic_id:
        relevant = [r for r in records if r.topic_id == topic_id]
    if not relevant and treatment:
        relevant = [r for r in records if r.treatment == treatment]
    recent = relevant[-max(1, int(max_items)) :]
    failures: dict[str, int] = {}
    repairs: dict[str, int] = {}
    for rec in recent:
        for item in rec.failure_classes:
            failures[item] = failures.get(item, 0) + 1
        for item in rec.repair_types:
            repairs[item] = repairs.get(item, 0) + 1
    return {
        "schema": "content-render-compact-lessons-v1",
        "topic_id": topic_id,
        "treatment": treatment,
        "records_considered": len(recent),
        "failure_counts": dict(sorted(failures.items(), key=lambda kv: (-kv[1], kv[0]))[:max_items]),
        "repair_counts": dict(sorted(repairs.items(), key=lambda kv: (-kv[1], kv[0]))[:max_items]),
        "recent_human_verdicts": [r.human_verdict for r in recent if r.human_verdict][-max_items:],
        "failed_pair_count": failed_pair_counts(recent).get((topic_id, treatment), 0) if topic_id and treatment else 0,
    }


def classify_writer_attempt(attempt: Mapping[str, Any]) -> tuple[str, ...]:
    classes: list[str] = []
    for row in attempt.get("rounds") or []:
        err = str(row.get("validate_err") or "").lower()
        if "script word count" in err or "voiceover too long" in err:
            classes.append("length")
        if "question" in err:
            classes.append("hook_question")
        if "similar" in err or "repetition" in err or "restated" in err:
            classes.append("repetition")
        if "thus" in err or "therefore" in err:
            classes.append("formal_register")
        if int(row.get("mechanical_hard_count") or 0) > 0:
            classes.append("traceability")
        if int(row.get("semantic_violation_count") or 0) > 0:
            classes.append("semantic")
        if row.get("semantic_verified") is False:
            classes.append("semantic_unverified")
    if attempt.get("accepted") is not True and not classes:
        classes.append("writer_rejected")
    return _clean_list(classes)


def records_from_writer_attempts(
    topic_id: str,
    payload: Mapping[str, Any],
    *,
    run_identity: str,
) -> list[LearningRecord]:
    out: list[LearningRecord] = []
    for idx, attempt in enumerate(payload.get("attempts") or [], 1):
        if not isinstance(attempt, Mapping):
            continue
        treatment = str(attempt.get("treatment") or "").strip()
        calls = attempt.get("calls") or []
        provider = ""
        model = ""
        for call in reversed(calls):
            if isinstance(call, Mapping) and call.get("provider"):
                provider = str(call.get("provider") or "")
                model = str(call.get("model") or "")
                break
        repair_types = _clean_list(
            (row.get("repair_plan") or {}).get("repair_type")
            for row in (attempt.get("rounds") or [])
            if isinstance(row, Mapping)
        )
        accepted = attempt.get("accepted") is True
        out.append(LearningRecord(
            attempt_id=stable_attempt_id(run_identity, topic_id, idx, treatment, attempt.get("candidate_kind")),
            topic_id=topic_id,
            treatment=treatment,
            stage="writer",
            status="accepted" if accepted else "failed",
            provider=provider,
            model=model,
            failure_classes=() if accepted else classify_writer_attempt(attempt),
            repair_types=repair_types,
            notes=str(attempt.get("error") or attempt.get("validate_err") or ""),
            metadata={
                "run_identity": run_identity,
                "attempt_index": idx,
                "candidate_kind": attempt.get("candidate_kind"),
                "total_calls": attempt.get("total_calls"),
                "repair_rounds": attempt.get("repair_rounds"),
            },
        ))
    return out
