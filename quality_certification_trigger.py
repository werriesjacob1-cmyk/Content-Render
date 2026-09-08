#!/usr/bin/env python3
"""Resolve the topic for the trusted private flagship-certification workflow.

The GitHub connector cannot POST workflow_dispatch, so Content Render also has a
trusted-main push bridge driven by ``.github/quality-certification-trigger``.
Historically that marker already carried ``topic=<id>``, but the workflow ignored
it and hard-coded ``venus_day``.  This helper makes the marker an actual control
surface while remaining fail-closed: malformed/duplicate/missing topic fields are
rejected before any provider-backed certification work starts.

This module performs no network or provider calls.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

_TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


class TriggerError(ValueError):
    pass


def parse_marker(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise TriggerError(f"marker line {lineno} is not key=value")
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or not value:
            raise TriggerError(f"marker line {lineno} has empty key/value")
        if key in values:
            raise TriggerError(f"duplicate marker key: {key}")
        values[key] = value
    return values


def _validate_topic(topic: str) -> str:
    topic = str(topic or "").strip()
    if topic == "auto":
        return topic
    if not _TOPIC_RE.fullmatch(topic):
        raise TriggerError("topic must be a simple topic_bank id or 'auto'")
    return topic


def resolve_topic(event_name: str, dispatch_topic: str, marker_text: str) -> str:
    event = str(event_name or "").strip()
    if event == "workflow_dispatch":
        return _validate_topic(dispatch_topic or "auto")
    if event == "push":
        marker = parse_marker(marker_text)
        if "topic" not in marker:
            raise TriggerError("trusted trigger marker is missing topic=<id>")
        return _validate_topic(marker["topic"])
    raise TriggerError(f"unsupported certification event: {event or '<empty>'}")


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--event-name", required=True)
    p.add_argument("--dispatch-topic", default="")
    p.add_argument("--marker", default=".github/quality-certification-trigger")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        marker_text = Path(args.marker).read_text(encoding="utf-8") if args.event_name == "push" else ""
        topic = resolve_topic(args.event_name, args.dispatch_topic, marker_text)
    except Exception as exc:
        print(f"CERTIFICATION TOPIC RESOLUTION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(topic)
    return 0


if __name__ == "__main__":
    sys.exit(main())
