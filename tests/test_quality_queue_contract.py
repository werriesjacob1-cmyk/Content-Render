#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_queue_contract as Q


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label)


def manifest(title="x"):
    return {"title": title, "scenes": [{"id": 1, "voiceover": "x", "search_query": "x"}]}


def test_stamp_never_relabels_writer():
    m = Q.stamp_manifest(manifest(), writer_version="legacy_v1", cert_version="legacy_generation")
    check(m["_factory_contract"]["writer_version"] == "legacy_v1", "writer version stamped")
    try:
        Q.stamp_manifest(m, writer_version="writer_v2.1", cert_version="private")
    except ValueError:
        pass
    else:
        raise AssertionError("existing manifest cannot be relabeled as another Writer")


def test_dequeue_skips_incompatible_legacy_after_cutover():
    with tempfile.TemporaryDirectory() as td:
        q = Path(td) / "queue"
        q.mkdir()
        old = Q.stamp_manifest(manifest("old"), writer_version="legacy_v1", cert_version="legacy_generation")
        new = Q.stamp_manifest(manifest("new"), writer_version="writer_v2.1", cert_version="writer_v21_certified")
        (q / "001_old.json").write_text(json.dumps(old), encoding="utf-8")
        (q / "002_new.json").write_text(json.dumps(new), encoding="utf-8")
        dest = Path(td) / "manifest.json"
        rc, evidence = Q.dequeue_compatible(q, dest, required_writer="writer_v2.1")
        chosen = json.loads(dest.read_text())
        check(rc == 0 and chosen["title"] == "new", "dequeue bypasses incompatible pre-cutover manifest")
        check(evidence["rejected"][0]["file"] == "001_old.json", "incompatible inventory remains explicit evidence")
        check((q / "001_old.json").exists(), "incompatible item is not silently destroyed without quarantine policy")


def test_unversioned_queue_entry_is_never_implicitly_v21():
    ok, reason = Q.compatibility(manifest(), required_writer="writer_v2.1")
    check(not ok and "unversioned" in reason, "unversioned legacy inventory fails closed at V2.1 cutover")


def test_stamp_queue_is_idempotent():
    with tempfile.TemporaryDirectory() as td:
        q = Path(td)
        (q / "a.json").write_text(json.dumps(manifest()), encoding="utf-8")
        first = Q.stamp_queue(q, writer_version="legacy_v1", cert_version="legacy_generation")
        second = Q.stamp_queue(q, writer_version="legacy_v1", cert_version="legacy_generation")
        check(first["stamped"] == 1 and second["stamped"] == 0, "queue stamping is idempotent")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]:
        fn()
    print("quality_queue_contract tests: PASS")
