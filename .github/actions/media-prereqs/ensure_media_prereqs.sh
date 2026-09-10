#!/usr/bin/env bash
# Install the Ubuntu media packages a render needs, and refuse to be broken by an
# apt repository this project does not install from.
#
# THE INCIDENT THIS EXISTS FOR (2026-09-09, main @ 024b0b8, run 34383772981)
#
# The factory proof died before rendering a single frame:
#
#   E: Failed to fetch https://dl.google.com/linux/chrome-stable/deb/dists/
#      stable/main/binary-amd64/Packages.gz  Hash Sum mismatch
#   E: Some index files failed to download. They have been ignored, or old
#      ones used instead.
#
# Read the second line: apt had ALREADY ignored the bad index and carried on
# with the Ubuntu ones. Nothing we install comes from Google Chrome. The job
# failed purely because `apt-get update` exits non-zero when ANY configured
# source fails, and `set -e` did the rest. Re-running on fresh runners in three
# Azure regions did not clear it, so it was not a transient worth waiting out.
#
# The runner image is ubuntu-24.04, which does not ship ffmpeg, so that apt path
# is on the critical path of EVERY render -- including the private flagship
# certification. A third-party repository on GitHub's runner image had a veto
# over the one run this project most needs to succeed.
#
# WHY THE EXIT CODE IS TOLERATED AND THE INSTALL IS NOT
#
# `apt-get update`'s exit code cannot distinguish "a repository we never use is
# serving bad metadata" from "Ubuntu's index is broken". So it is not used as
# the verdict. The verdict is whether the packages we actually need install and
# run:
#
#   - if Ubuntu's index really were broken, `apt-get install` below fails and
#     this script exits non-zero;
#   - if ffmpeg, ffprobe or DejaVu are not runnable afterwards, this script
#     exits non-zero.
#
# So an irrelevant repository can no longer stop a render, and a missing encoder
# still stops it dead. That distinction is the whole point: `apt-get update ||
# true` on its own would have cleared the red tick and shipped a render with no
# encoder.
#
# An earlier version of this script tried to be cleverer -- it filtered
# /etc/apt/sources.list.d down to an allowlist of Ubuntu mirror hostnames and
# updated only those. It failed on the very first CI run, because the runner's
# own ubuntu.sources did not match the allowlist and the script correctly
# refused to continue. Guessing at mirror hostnames is knowledge that rots.
# Proving the packages installed is knowledge that does not.
set -euo pipefail

log() { printf '[prereq] %s\n' "$*"; }

media_present() {
  command -v ffmpeg >/dev/null 2>&1 || return 1
  command -v ffprobe >/dev/null 2>&1 || return 1
  case "$(fc-match -f '%{family}' 'DejaVu Sans' 2>/dev/null || true)" in
    *DejaVu*) return 0 ;;
    *) return 1 ;;
  esac
}

if media_present; then
  log "ffmpeg, ffprobe and DejaVu already present; no apt needed"
else
  # Bounded retries absorb a genuinely transient mirror hiccup. A persistent
  # failure is NOT swallowed here -- it is simply not the verdict; the install
  # below is.
  for attempt in 1 2 3; do
    if sudo apt-get update -qq; then
      log "apt-get update clean (attempt ${attempt})"
      break
    fi
    log "apt-get update reported errors on attempt ${attempt}"
    if [ "$attempt" -eq 3 ]; then
      log "continuing anyway: update's exit code cannot tell an unused"
      log "third-party repository from a broken Ubuntu index, so the install"
      log "below decides. It fails closed if the packages are unavailable."
    else
      sleep $((attempt * 5))
    fi
  done

  # NOT tolerated. If the packages cannot be resolved or fetched -- including
  # the case where Ubuntu's own index is the broken one -- this fails the step.
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends ffmpeg fonts-dejavu-core
fi

# Verify what is actually on the machine, not what was requested. Every consumer
# of this action needs all three, so all three are checked everywhere -- before
# this was shared, each workflow checked a different subset.
ffmpeg -version >/dev/null
ffprobe -version >/dev/null
font_family="$(fc-match -f '%{family}' 'DejaVu Sans' 2>/dev/null || true)"
case "$font_family" in
  *DejaVu*) ;;
  *)
    echo "[prereq] FATAL: DejaVu Sans unavailable (fc-match reported '${font_family}')." >&2
    echo "[prereq] Captions would silently render in a substitute face." >&2
    exit 1
    ;;
esac
log "ffmpeg, ffprobe and DejaVu Sans verified"
