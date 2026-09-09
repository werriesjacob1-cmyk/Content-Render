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
import sys

import yaml

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
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            uses = str(step.get("uses") or "")
            if uses.startswith("actions/upload-artifact"):
                w = step.get("with") or {}
                paths = [p.strip() for p in str(w.get("path") or "").splitlines() if p.strip()]
                yield {
                    "name": str(w.get("name") or ""),
                    "paths": paths,
                    "retention": w.get("retention-days"),
                    "step": str(step.get("name") or uses),
                }


def _mentions_media(paths) -> bool:
    for p in paths:
        if p.startswith("!"):
            continue
        if any(p.endswith(sfx) or p.endswith(f"*{sfx}") for sfx in MEDIA_SUFFIXES):
            return True
    return False


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


if __name__ == "__main__":
    test_every_upload_declares_a_retention()
    test_rendered_video_is_short_lived()
    test_the_evidence_artifact_carries_no_video()
    test_the_audit_trail_outlives_the_video()
    test_every_heavy_proof_actually_splits()
    print("actions storage budget tests: PASS")
