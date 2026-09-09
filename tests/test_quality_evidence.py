#!/usr/bin/env python3
"""Regressions for the single JSON evidence boundary.

The zero-provider factory proof died in CI with "Object of type PosixPath is
not JSON serializable". Patching that one field would have left the identical
landmine at the nine other evidence-writing sites, each only discoverable in a
real render. These tests pin the boundary's contract instead.
"""
from __future__ import annotations

import dataclasses
import enum
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")

import quality_evidence as QE

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


class _Kind(enum.Enum):
    VIDEO = "video"


@dataclasses.dataclass
class _Decision:
    scene_id: str
    asset: Path
    kind: _Kind


def test_paths_are_converted_at_every_nesting_depth():
    """The exact CI failure, plus the shapes evidence actually takes."""
    payload = {
        "top": Path("/tmp/final.mp4"),
        "nested": {"deep": {"deeper": Path("/tmp/repaired.mp4")}},
        "in_list": [Path("/a.mp4"), {"p": Path("/b.mp4")}],
        "in_tuple": (Path("/c.mp4"), 3),
    }
    safe = QE.json_safe(payload)
    text = json.dumps(safe)  # must not raise -- this is what CI hit
    check(safe["top"] == "/tmp/final.mp4", "a top-level Path becomes a string")
    check(safe["nested"]["deep"]["deeper"] == "/tmp/repaired.mp4",
          "a Path nested three dicts deep is converted")
    check(safe["in_list"][0] == "/a.mp4" and safe["in_list"][1]["p"] == "/b.mp4",
          "Paths inside lists and inside dicts inside lists are converted")
    check(safe["in_tuple"] == ["/c.mp4", 3], "tuples become lists with Paths converted")
    check("PosixPath" not in text, "no repr of a Path object leaks into the JSON text")


def test_enums_and_dataclasses_are_converted_not_guessed():
    d = _Decision(scene_id="2", asset=Path("/x/s2.mp4"), kind=_Kind.VIDEO)
    safe = QE.json_safe({"decision": d})
    check(safe["decision"]["asset"] == "/x/s2.mp4",
          "a Path inside a dataclass is converted")
    check(safe["decision"]["kind"] == "video", "an Enum serializes as its value")
    json.dumps(safe)


def test_unknown_types_fail_closed_rather_than_corrupting_evidence():
    """Silently str()-ing an object writes '<Foo object at 0x..>' into evidence:
    a file that looks like a successful run but says nothing true."""
    class Opaque:
        pass

    for payload in ({"bad": Opaque()}, [Opaque()], {"deep": {"bad": Opaque()}}):
        try:
            QE.json_safe(payload)
            raise AssertionError("unknown object should not serialize")
        except QE.UnserializableEvidence as exc:
            check("Opaque" in str(exc), "the error names the offending type")
            check("$" in str(exc), "the error names where in the evidence it sits")
    try:
        QE.json_safe({"raw": b"\x00\x01"})
        raise AssertionError("bytes should not serialize")
    except QE.UnserializableEvidence:
        check(True, "raw bytes are refused rather than mangled into text")


def test_numbers_keep_their_scientific_meaning():
    """NaN means 'unmeasurable' in audio QA. Rewriting it to satisfy a
    serializer would be altering a measurement, not formatting it."""
    safe = QE.json_safe({"lufs": float("nan"), "peak": float("-inf"), "n": 0, "ok": False})
    check(safe["lufs"] != safe["lufs"], "NaN is passed through untouched")
    check(safe["peak"] == float("-inf"), "infinity is passed through untouched")
    check(safe["n"] == 0 and safe["ok"] is False, "zero and False survive intact")


def test_sets_become_deterministic_lists():
    safe = QE.json_safe({"ids": {"3", "1", "2"}})
    check(safe["ids"] == ["1", "2", "3"], "sets serialize sorted so evidence is diffable")


def test_write_json_round_trips_and_creates_parents():
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "nested" / "dir" / "evidence.json"
        QE.write_json(dest, {"video": Path("/tmp/final.mp4"), "scenes": [1, 2]})
        check(dest.is_file(), "write_json creates missing parent directories")
        back = json.loads(dest.read_text())
        check(back["video"] == "/tmp/final.mp4", "written evidence round-trips as JSON")


def test_every_evidence_writer_uses_the_boundary():
    """A new raw json.dumps at an evidence site reintroduces the whole bug."""
    for name in ("quality_downstream_factory_proof.py", "quality_repair_controller.py",
                 "quality_asset_lineage.py", "quality_visual_bible.py",
                 "quality_science_render.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        check("quality_evidence" in src, f"{name} imports the evidence boundary")
        offenders = [
            ln.strip() for ln in src.splitlines()
            if ("json.dumps(" in ln or "json.dump(" in ln) and "QE." not in ln
        ]
        check(not offenders, f"{name} has no raw json.dump(s) evidence write: {offenders[:2]}")


if __name__ == "__main__":
    test_paths_are_converted_at_every_nesting_depth()
    test_enums_and_dataclasses_are_converted_not_guessed()
    test_unknown_types_fail_closed_rather_than_corrupting_evidence()
    test_numbers_keep_their_scientific_meaning()
    test_sets_become_deterministic_lists()
    test_write_json_round_trips_and_creates_parents()
    test_every_evidence_writer_uses_the_boundary()
    print("quality evidence boundary tests: PASS")
