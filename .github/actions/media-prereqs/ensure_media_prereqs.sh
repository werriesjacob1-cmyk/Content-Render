#!/usr/bin/env bash
# Install the Ubuntu media packages a render needs, and refuse to be broken by an
# apt repository this project does not use.
#
# THE INCIDENT THIS EXISTS FOR (2026-09-09, main @ 024b0b8)
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
# source fails, and `set -e` did the rest. Re-running on fresh runners in
# different regions did not clear it.
#
# So a third-party repository that ships on GitHub's runner image, and that we
# never install from, had a veto over every render, every proof, and the private
# flagship certification -- all of which run this same block.
#
# THE FIX, AND ITS LIMIT
#
# The update below reads ONLY Ubuntu's own sources, via apt options pointed at a
# temporary directory. The runner's real apt configuration is never modified, so
# there is nothing to restore and nothing to leak into later steps.
#
# This removes an irrelevant failure path. It does NOT make missing packages
# survivable: if no Ubuntu source can be found, or the update fails, or the
# install fails, or the tools are not runnable afterwards, this script exits
# non-zero. Fail closed, loudly, on anything that actually matters.
set -euo pipefail

UBUNTU_HOSTS='archive\.ubuntu\.com|security\.ubuntu\.com|ports\.ubuntu\.com|azure\.archive\.ubuntu\.com|[a-z0-9.-]*\.archive\.ubuntu\.com'

log() { printf '[prereq] %s\n' "$*"; }

media_present() {
  command -v ffmpeg >/dev/null 2>&1 || return 1
  command -v ffprobe >/dev/null 2>&1 || return 1
  case "$(fc-match -f '%{family}' 'DejaVu Sans' 2>/dev/null || true)" in
    *DejaVu*) return 0 ;;
    *) return 1 ;;
  esac
}

collect_ubuntu_sources() {
  # Copy only source definitions that point at Ubuntu's own archives. Both the
  # legacy one-line .list format and 24.04's deb822 .sources format are handled,
  # because the runner image uses .sources for Ubuntu and .list for the
  # third-party repositories.
  local dest="$1" found=0 f
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*; do
    [ -f "$f" ] || continue
    case "$f" in *.list|*.sources|/etc/apt/sources.list) ;; *) continue ;; esac
    if grep -qsE "$UBUNTU_HOSTS" "$f"; then
      cp "$f" "$dest/$(basename "$f")"
      found=$((found + 1))
      log "using Ubuntu source $(basename "$f")"
    else
      log "ignoring non-Ubuntu source $(basename "$f")"
    fi
  done
  [ "$found" -gt 0 ] || return 1
}

if media_present; then
  log "ffmpeg, ffprobe and DejaVu already present; no apt needed"
else
  src_dir="$(mktemp -d)"
  empty_list="$(mktemp)"
  trap 'rm -rf "$src_dir" "$empty_list"' EXIT

  if ! collect_ubuntu_sources "$src_dir"; then
    echo "[prereq] FATAL: no Ubuntu apt source found on this runner." >&2
    echo "[prereq] Refusing to guess -- a render must not proceed without ffmpeg." >&2
    exit 1
  fi

  # A bounded retry for a genuinely transient Ubuntu mirror hiccup. This is not
  # a way to tolerate a broken index: after the last attempt the failure stands.
  updated=0
  for attempt in 1 2 3; do
    if sudo apt-get update -qq \
        -o Dir::Etc::sourcelist="$empty_list" \
        -o Dir::Etc::sourceparts="$src_dir"; then
      updated=1
      break
    fi
    log "apt-get update attempt ${attempt} failed against Ubuntu sources; retrying"
    sleep $((attempt * 5))
  done
  if [ "$updated" -ne 1 ]; then
    echo "[prereq] FATAL: apt-get update failed against Ubuntu's own sources." >&2
    exit 1
  fi

  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends ffmpeg fonts-dejavu-core
fi

# Verify what was actually installed, not what was requested. Every consumer of
# this action needs all three, so all three are checked everywhere.
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
