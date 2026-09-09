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


def test_the_update_reads_only_ubuntu_sources():
    """The third-party repositories are excluded, not merely tolerated."""
    s = _script()
    check("Dir::Etc::sourceparts" in s and "Dir::Etc::sourcelist" in s,
          "the update is pointed at a filtered source directory")
    check("archive.ubuntu.com" in s.replace("\\", ""),
          "which is built from Ubuntu's own archives")
    check("/etc/apt/sources.list.d" in s,
          "read from the runner's real source directory rather than invented")
    # The runner image is never mutated: a step that moved files aside would
    # leave the job's later steps in whatever state a mid-step failure left.
    check(not re.search(r"\bmv\b.*sources\.list", s) and "rm -f /etc/apt" not in s,
          "and the runner's apt configuration is never modified, so there is "
          "nothing to restore if this step dies partway")


def test_the_action_still_fails_closed():
    """The counterweight: this must not become 'ignore apt errors'."""
    s = _script()
    check("set -euo pipefail" in s, "the script still runs under set -e")
    # An install that fails must not be swallowed.
    install = [ln for ln in s.splitlines() if "apt-get install" in ln]
    check(len(install) == 1, f"there is exactly one install invocation ({len(install)})")
    check("|| true" not in install[0] and "||" not in install[0],
          "and its failure is not swallowed")
    check(s.count("exit 1") >= 3,
          "missing Ubuntu sources, a failed update and a missing font each abort")
    for tool in ("ffmpeg -version", "ffprobe -version"):
        check(tool in s, f"{tool} is verified after install, not assumed")
    check("DejaVu" in s and "fc-match" in s,
          "and the caption font is verified rather than assumed present")


def test_the_retry_is_bounded_and_not_a_way_to_ignore_failure():
    s = _script()
    check("for attempt in 1 2 3" in s, "the update retry is bounded at three attempts")
    body = s.split("for attempt in 1 2 3", 1)[1].split("fi", 1)[0]
    check("updated=1" in body, "a success is recorded rather than assumed")
    check('if [ "$updated" -ne 1 ]' in s,
          "and exhausting the retries is a hard failure, not a shrug")


if __name__ == "__main__":
    test_the_shared_action_exists_and_is_wired_in()
    test_no_workflow_runs_a_bare_apt_update_again()
    test_the_update_reads_only_ubuntu_sources()
    test_the_action_still_fails_closed()
    test_the_retry_is_bounded_and_not_a_way_to_ignore_failure()
    print("workflow media prerequisite tests: PASS")
