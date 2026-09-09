#!/usr/bin/env python3
"""Proof artifacts must not be able to fill the account's Actions storage again.

WHAT HAPPENED (2026-09-09)

GitHub emailed: "You have used 100% of the Actions storage included for the
werriesjacob1-cmyk account" -- 0.5 GB. Measured from the real API rather than
guessed: 604 MB live across 43 artifacts, every one created that same day.

    downstream-factory-proof    16 x ~22.4 MB = 360 MB
    production-realism-proof     9 x ~27.0 MB = 244 MB
    quality-certification       18 x  ~0.006  = 0.1 MB

Nothing was old. The proofs upload a fresh copy per push, so one day of ordinary
PR iteration on two branches consumed the whole monthly allowance. And the size
is almost entirely video: the realism artifact measured 27.59 MB of which
final.mp4 was 27.588 MB -- **99.98%**.

THE FIX THIS PINS

Split each heavy proof upload in two:

  * evidence  -- the measured reports a reviewer actually reads (loudness, true
    peak, sample rate, dimensions, alignment, lineage) plus the proof frame.
    Hundreds of KB, kept long enough to be useful for an async review.
  * media     -- the rendered MP4s. Kept only as long as anyone reaches for them.

This costs nothing in rigor. Probing the real artifact is this project's core
doctrine -- the 96 kHz defect and the -0.0 dBTP defect were both found by
downloading and probing, never from a green tick -- and both were found within
hours of the run that produced them. If a stale run needs re-examining, re-running
CI regenerates the video exactly.

The counterweight assertion matters as much as the split: the EVIDENCE artifact
must outlive the media. A "fix" that simply shortened everything to one day would
pass a naive size check and destroy the audit trail.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS = ROOT / ".github" / "workflows"

# The two workflows that render real video on every push. These are the ones
# that filled the allowance; render.yml and the flagship run rarely and are
# excluded deliberately rather than by oversight.
HEAVY_PROOFS = ("tests.yml", "production_realism_proof.yml")

MEDIA_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav")
MAX_MEDIA_RETENTION_DAYS = 2
MIN_EVIDENCE_RETENTION_DAYS = 7


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _upload_steps(path: Path):
    """Upload steps, parsed WITHOUT PyYAML.

    The zero-quota job installs no dependencies -- that is the point of it -- so
    this walks the step blocks by indentation instead. It is a narrow parser for
    a shape this repo controls, not a general YAML reader, and it fails loudly
    rather than silently returning nothing: see the guard in each test that a
    minimum number of steps was found. (Written after the first version of this
    file imported yaml, passed locally, and turned CI red.)
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    steps, cur = [], None
    for i, raw in enumerate(lines):
        m = re.match(r"^(\s*)- (?:name|uses):\s*(.*)$", raw)
        if m:
            if cur:
                # Close the previous block HERE. Forgetting this let every block
                # run to EOF, so each one "contained" every later step and the
                # last retention-days in the file won every lookup.
                cur["end"] = i
                steps.append(cur)
            cur = {"indent": len(m.group(1)), "start": i, "end": len(lines)}
            continue
        if cur is not None:
            stripped = raw.strip()
            indent = len(raw) - len(raw.lstrip())
            if stripped and not stripped.startswith("#") and indent <= cur["indent"]:
                cur["end"] = i
                steps.append(cur)
                cur = None
    if cur:
        steps.append(cur)

    for st in steps:
        block = lines[st["start"]:st["end"]]
        text = "\n".join(block)
        if "actions/upload-artifact" not in text:
            continue
        name = _scalar(block, "name:", skip_step_name=True)
        head = block[0].split("#", 1)[0].strip()
        step_label = head[len("- name:"):].strip() if head.startswith("- name:") else "upload-artifact"
        retention = _scalar(block, "retention-days:")
        yield {
            "name": name or "",
            "paths": _path_list(block),
            "retention": int(retention) if retention and retention.isdigit() else None,
            "step": step_label,
        }


def _scalar(block, key, skip_step_name=False):
    """Last value for `key` in the block, ignoring comments.

    `skip_step_name` skips the step's own `- name:` line so the artifact name
    inside `with:` is what is returned.
    """
    found = None
    for ln in block:
        s = ln.split("#", 1)[0].rstrip()
        stripped = s.strip()
        if skip_step_name and stripped.startswith("- name:"):
            continue
        if stripped.startswith(key):
            found = stripped[len(key):].strip()
    return found


def _path_list(block):
    """The `path:` value, whether inline or a `|` block scalar."""
    for i, ln in enumerate(block):
        stripped = ln.split("#", 1)[0].strip()
        if not stripped.startswith("path:"):
            continue
        inline = stripped[len("path:"):].strip()
        if inline and inline != "|":
            return [inline]
        indent = len(ln) - len(ln.lstrip())
        out = []
        for nxt in block[i + 1:]:
            body = nxt.split("#", 1)[0]
            if not body.strip():
                continue
            if len(body) - len(body.lstrip()) <= indent:
                break
            out.append(body.strip())
        return out
    return []


def _mentions_media(paths) -> bool:
    for p in paths:
        if p.startswith("!"):
            continue
        if any(p.endswith(sfx) or p.endswith(f"*{sfx}") for sfx in MEDIA_SUFFIXES):
            return True
    return False


def test_the_parser_actually_found_the_uploads():
    """A hand-rolled parser that quietly returns nothing would pass every test.

    This is the guard for that. It is not hypothetical: the first version of
    this parser failed to close each step block, so every block ran to end of
    file and the last retention-days in the workflow won every lookup.
    """
    for name in HEAVY_PROOFS:
        ups = list(_upload_steps(WORKFLOWS / name))
        check(len(ups) == 2,
              f"{name}: exactly the evidence and media uploads were parsed "
              f"({len(ups)} found)")
        for up in ups:
            check(up["name"] and up["paths"],
                  f"{name}: '{up['step']}' parsed a name and at least one path")
            check(up["step"] != "upload-artifact",
                  f"{name}: the step's own name was parsed, so failures name it")


def test_every_upload_declares_a_retention():
    """An upload with no retention inherits the account default and hoards."""
    for name in HEAVY_PROOFS:
        for up in _upload_steps(WORKFLOWS / name):
            check(up["retention"] is not None,
                  f"{name}: '{up['step']}' states its own retention-days")


def test_rendered_video_is_short_lived():
    found = 0
    for name in HEAVY_PROOFS:
        for up in _upload_steps(WORKFLOWS / name):
            if not _mentions_media(up["paths"]):
                continue
            found += 1
            check(int(up["retention"]) <= MAX_MEDIA_RETENTION_DAYS,
                  f"{name}: '{up['step']}' keeps rendered media for "
                  f"{up['retention']} days (max {MAX_MEDIA_RETENTION_DAYS}) -- "
                  f"at ~25 MB a push this is what filled a 0.5 GB allowance in a day")
    check(found >= 2,
          f"both heavy proofs upload their media in a bounded artifact ({found})")


def test_the_evidence_artifact_carries_no_video():
    """The long-lived half must stay small, or the split achieves nothing."""
    for name in HEAVY_PROOFS:
        for up in _upload_steps(WORKFLOWS / name):
            if up["retention"] is None or int(up["retention"]) <= MAX_MEDIA_RETENTION_DAYS:
                continue
            check(not _mentions_media(up["paths"]),
                  f"{name}: '{up['step']}' is long-lived, so it must not include "
                  f"rendered media (paths: {up['paths']})")


def test_the_audit_trail_outlives_the_video():
    """The counterweight: shortening EVERYTHING would pass a naive size check.

    The measured reports are what a later reviewer reads, and they cost
    essentially nothing to keep. If they expired with the video, this change
    would have traded the audit trail for disk.
    """
    for name in HEAVY_PROOFS:
        longest = max((int(u["retention"]) for u in _upload_steps(WORKFLOWS / name)
                       if u["retention"] is not None), default=0)
        check(longest >= MIN_EVIDENCE_RETENTION_DAYS,
              f"{name}: measured evidence is kept at least "
              f"{MIN_EVIDENCE_RETENTION_DAYS} days (longest is {longest})")


def test_every_heavy_proof_actually_splits():
    for name in HEAVY_PROOFS:
        ups = list(_upload_steps(WORKFLOWS / name))
        media = [u for u in ups if _mentions_media(u["paths"])]
        evidence = [u for u in ups
                    if u["retention"] is not None
                    and int(u["retention"]) > MAX_MEDIA_RETENTION_DAYS]
        check(media and evidence,
              f"{name}: uploads are split into media and evidence "
              f"({len(media)} media, {len(evidence)} evidence)")
        names = [u["name"] for u in ups]
        check(len(set(names)) == len(names),
              f"{name}: the two artifacts have distinct names ({names})")


def test_mastering_scratch_never_lands_in_the_uploaded_directory():
    """The measured master writes WAVs; they must not go where evidence goes.

    Found by weighing the artifact after the split, not by reading the diff:
    the factory "evidence" half came back at 11.5 MB where the realism half was
    0.117 MB. `out/master_work/` held eight 1.54 MB stage WAVs -- 12.3 MB of
    intermediates that nobody reads, since every measurement they carry is
    already in the master report. It had been inflating every factory-proof
    artifact since the mastering rewrite shipped.

    Behaviour, not text: _mix_final is called with `run` and the master stubbed,
    and the filesystem is then checked for anything left beside `dest`.
    """
    import tempfile
    import quality_downstream_factory_proof as QDF
    import delivery_master as DM

    saved = (QDF.run, QDF.legacy._ensure_music_bed, QDF.legacy._apply_vibe,
             DM._run, DM._measure)
    QDF.run = lambda cmd: None
    QDF.legacy._ensure_music_bed = lambda duration: ""
    QDF.legacy._apply_vibe = lambda vibe: None
    DM._run = lambda cmd: None
    DM._measure = lambda path: (-20.0, -2.5)
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out, work = root / "out", root / "work"
            out.mkdir(); work.mkdir()
            QDF._mix_final(out / "captioned.mp4", out / "final.mp4", 16.0, work_dir=work)
            strays = sorted(q.name for q in out.iterdir() if q.is_dir())
            check(not strays,
                  f"no scratch directory is created inside the uploaded out/ ({strays})")
            check(any(work.iterdir()),
                  "and the scratch went to the work directory it was handed")
    finally:
        (QDF.run, QDF.legacy._ensure_music_bed, QDF.legacy._apply_vibe,
         DM._run, DM._measure) = saved


if __name__ == "__main__":
    test_the_parser_actually_found_the_uploads()
    test_every_upload_declares_a_retention()
    test_rendered_video_is_short_lived()
    test_the_evidence_artifact_carries_no_video()
    test_the_audit_trail_outlives_the_video()
    test_every_heavy_proof_actually_splits()
    test_mastering_scratch_never_lands_in_the_uploaded_directory()
    print("actions storage budget tests: PASS")
