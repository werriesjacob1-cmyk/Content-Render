#!/usr/bin/env python3
"""An apt repository we never install from must not be able to stop a render.

THE INCIDENT (2026-09-09, main @ 024b0b8, run 34383772981)

The factory proof failed before rendering a frame:

    E: Failed to fetch https://dl.google.com/linux/chrome-stable/deb/dists/
       stable/main/binary-amd64/Packages.gz  Hash Sum mismatch
    E: Some index files failed to download. They have been ignored, or old
       ones used instead.

apt had already ignored the bad index and used the Ubuntu ones. The job died
only because ``apt-get update`` exits non-zero when ANY source fails and the
step ran under ``set -e``. Re-running on fresh runners in three Azure regions
did not clear it -- it was not transient.

Four workflows carried their own near-identical copy of that block, including
``quality_certification_render.yml``, the PRIVATE FLAGSHIP. So a Google Chrome
repository shipped on GitHub's runner image held a veto over the one run this
project most needs to succeed.

Two things are asserted here, and they pull in opposite directions on purpose:

  1. no workflow may run a bare ``apt-get update`` again, and every media
     workflow must go through the ONE shared action -- four copies of subtle
     apt logic is the same drift that made a shared audio constant inert;
  2. the shared action must still FAIL CLOSED. Removing an irrelevant failure
     path is the goal; tolerating a missing ffmpeg is not. A fix that made
     ``apt-get update || true`` the answer would pass assertion 1 and ship a
     render with no encoder, so assertion 2 exists to reject it.

Zero network, zero providers: the workflow and script sources are read.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION_DIR = ROOT / ".github" / "actions" / "media-prereqs"
ACTION_REF = "./.github/actions/media-prereqs"

# Every workflow that renders or probes media, and therefore needs ffmpeg. The
# flagship is in this list deliberately: it is the run that must not be lost.
MEDIA_WORKFLOWS = (
    "tests.yml",
    "production_realism_proof.yml",
    "quality_certification_render.yml",
    "render.yml",
)


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def _script() -> str:
    return (ACTION_DIR / "ensure_media_prereqs.sh").read_text(encoding="utf-8")


def _code() -> str:
    """The script's executable lines only.

    The comment block quotes the failing apt commands verbatim -- deliberately,
    since the next reader needs the incident in front of them -- so a naive
    substring check counts prose as code. A test in this repo has matched its
    own explanatory comment before; that is why this helper exists.
    """
    return "\n".join(ln for ln in _script().splitlines()
                     if not ln.lstrip().startswith("#"))


def test_the_shared_action_exists_and_is_wired_in():
    check((ACTION_DIR / "action.yml").is_file(),
          "the shared media-prerequisite action exists")
    check((ACTION_DIR / "ensure_media_prereqs.sh").is_file(),
          "and carries the script it runs")
    for name in MEDIA_WORKFLOWS:
        src = (WORKFLOWS / name).read_text(encoding="utf-8")
        check(ACTION_REF in src,
              f"{name}: takes media prerequisites from the shared action")


def test_no_workflow_runs_a_bare_apt_update_again():
    """The exact shape of the outage: an unscoped update over every source."""
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "apt-get update" in line:
                offenders.append(f"{path.name}:{i}")
    check(not offenders,
          f"no workflow runs apt-get update directly any more (offenders: {offenders})")


def test_the_update_exit_code_is_not_the_verdict():
    """An unused repository failing must not decide whether a render happens.

    This assertion is about BEHAVIOUR, not mechanism, and that is a correction.
    The first version of this test asserted the implementation -- that the
    script filtered apt sources down to an allowlist of Ubuntu mirror hostnames.
    It passed locally and the action failed on its first CI run, because the
    runner's own ubuntu.sources did not match the allowlist. A test that pins
    HOW something is done cannot notice that the how is wrong.
    """
    s = _code()
    # Invocations, not mentions: the script also LOGS about apt-get update, and
    # counting those would make this assertion meaningless.
    updates = [ln for ln in s.splitlines() if "sudo apt-get update" in ln]
    check(len(updates) == 1, f"there is exactly one update invocation ({len(updates)})")
    check("if sudo apt-get update" in s,
          "its exit code is examined rather than allowed to abort the step")
    # No hostname knowledge anywhere: mirror names are exactly the kind of fact
    # that rots, and did.
    check("archive.ubuntu.com" not in s and "sources.list.d" not in s,
          "the executable script encodes no guess about apt mirror hostnames "
          "or source-file layout")
    check("dl.google.com" in _script(),
          "the incident it defends against is named where the next reader "
          "will see it, rather than the behaviour looking arbitrary")


def test_the_action_still_fails_closed():
    """The counterweight: this must not become 'ignore apt errors'."""
    s = _code()
    check("set -euo pipefail" in s, "the script still runs under set -e")
    # An install that fails must not be swallowed.
    install = [ln for ln in s.splitlines() if "sudo env" in ln and "apt-get install" in ln]
    check(len(install) == 1, f"there is exactly one install invocation ({len(install)})")
    check("|| true" not in install[0] and "||" not in install[0],
          "and its failure is not swallowed")
    check("exit 1" in s, "a missing caption font aborts the step")
    # Narrowly about apt. `fc-match ... || true` is legitimate elsewhere: it
    # captures a font name whose ABSENCE the case statement then rejects, which
    # is the opposite of swallowing a failure.
    apt_lines = [ln for ln in s.splitlines() if "apt-get" in ln and "log " not in ln]
    swallowed = [ln.strip() for ln in apt_lines if "|| true" in ln or "|| :" in ln]
    check(not swallowed,
          f"no apt command has its failure swallowed outright ({swallowed})")
    for tool in ("ffmpeg -version", "ffprobe -version"):
        check(tool in s, f"{tool} is verified after install, not assumed")
    check("DejaVu" in s and "fc-match" in s,
          "and the caption font is verified rather than assumed present")


def test_the_retry_is_bounded_and_not_a_way_to_ignore_failure():
    s = _code()
    check("for attempt in 1 2 3" in s, "the update retry is bounded at three attempts")
    # Exhausting the retries does not abort, deliberately -- but the install
    # immediately after does, so a genuinely broken Ubuntu index still stops the
    # render. That is the line this design walks, so it is pinned here.
    install_at = s.index("apt-get install")
    retry_at = s.index("for attempt in 1 2 3")
    check(retry_at < install_at,
          "the install runs after the retries and decides the outcome")
    check("sleep" in s, "and the attempts are spaced rather than hammering")


if __name__ == "__main__":
    test_the_shared_action_exists_and_is_wired_in()
    test_no_workflow_runs_a_bare_apt_update_again()
    test_the_update_exit_code_is_not_the_verdict()
    test_the_action_still_fails_closed()
    test_the_retry_is_bounded_and_not_a_way_to_ignore_failure()
    print("workflow media prerequisite tests: PASS")
