#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label)


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_render_schedule_spend_is_opt_in_during_legacy_transition():
    y = text(".github/workflows/render.yml")
    check("LEGACY_SCHEDULED_GENERATION_ENABLED == 'true'" in y, "scheduled legacy render spend requires explicit repo variable")
    check("github.event_name != 'schedule'" in y, "manual/repository dispatch remain available independently")


def test_buffer_schedule_spend_is_opt_in_and_queue_is_stamped():
    y = text(".github/workflows/buffer.yml")
    check("LEGACY_SCHEDULED_GENERATION_ENABLED == 'true'" in y, "scheduled legacy buffer spend requires explicit repo variable")
    check("quality_queue_contract.py --stamp" in y, "buffered manifests receive explicit writer/certification identity")
    check("quality_production_generate.py --enqueue" in y, "buffer uses capability-aware provider wrapper")


def test_render_dequeue_is_version_compatible_and_live_generation_guarded():
    y = text(".github/workflows/render.yml")
    check("quality_queue_contract.py" in y and "--required-writer" in y and "--required-cert" in y,
          "render can only dequeue inventory compatible with active factory contract")
    check("quality_production_generate.py manifest.json" in y, "live unattended generation uses capability-aware wrapper")


def test_render_prerequisites_use_single_combined_install_path():
    y = text(".github/workflows/render.yml")
    check("fc-match" in y, "production uses robust fc-match font probe")
    check("ffmpeg fonts-dejavu-core" in y, "ffmpeg and DejaVu install together")
    check("fc-list | grep -qi dejavu" not in y, "old SIGPIPE-prone/slow font probe removed")
    check(y.count("apt-get update") == 1, "production prerequisite step has at most one apt update")


def test_private_learning_is_cache_only_and_artifact_visible():
    y = text(".github/workflows/quality_certification_render.yml")
    check("permissions:\n  contents: read" in y, "private flagship keeps repository read-only permission")
    check("quality_learning_capture.py" in y, "private attempt is persisted into learning ledger")
    check("actions/cache/restore@v4" in y and "actions/cache/save@v4" in y, "learning survives runs without repo commits")
    check("quality_learning.jsonl" in y, "learning ledger snapshot enters private evidence package")
    check("visual_bible.json" in y and "final_asset_lineage.json" in y, "visual continuity and actual asset lineage enter artifact")


def test_publishing_kill_switch_boundaries_unchanged():
    y = text(".github/workflows/render.yml")
    check("vars.AUTO_PUBLISH_ENABLED == 'true'" in y, "Release/Publer remain exact-true gated")
    check("certification_only != 'true'" in y, "manual certification remains independently non-publishing")


def test_every_scheduled_provider_spending_lane_is_gated():
    """expand_bank.yml was the one cron that could reach paid Gemini/OpenRouter
    generation with nothing enabled -- and it auto-commits its result, so an
    unattended run spent credit AND mutated the repo with no human switch."""
    gate = "vars.LEGACY_SCHEDULED_GENERATION_ENABLED == 'true'"
    for wf in ("render.yml", "buffer.yml", "expand_bank.yml"):
        y = text(f".github/workflows/{wf}")
        if "schedule:" not in y:
            continue
        check(gate in y, f"{wf} gates its scheduled provider spend behind the transition switch")
        check("github.event_name != 'schedule'" in y,
              f"{wf} still allows explicit manual dispatch")


def test_expand_bank_validates_before_bot_commit():
    """A GitHub-token bot push may not trigger a second push workflow. The bank
    must therefore prove its zero-quota integrity checks BEFORE committing the
    generated topic_bank.json, not rely on downstream CI that may never run."""
    y = text(".github/workflows/expand_bank.yml")
    expand_i = y.index("python expand_bank.py")
    validate_i = y.index("python tests/test_pipeline.py")
    commit_i = y.index('git commit -m "auto: expand topic bank toward 500 (WTF facts)"')
    check(expand_i < validate_i < commit_i,
          "expanded bank is validated after generation and before the bot commit")
    check("Validate expanded bank before commit (zero quota)" in y,
          "pre-commit bank validation is an explicit workflow step")


def test_stamping_cannot_relabel_a_v21_manifest_as_legacy():
    """render.yml stamps the queue immediately before REQUIRING the legacy
    label, so an unstamped V2.1 manifest would otherwise be auto-blessed as
    legacy and dequeued -- the exact silent migration the contract prevents."""
    import quality_queue_contract as Q
    legacy_like = {"scenes": [{"id": 1}]}
    stamped = Q.stamp_manifest(legacy_like, writer_version="legacy_v1", cert_version="legacy_generation")
    check(stamped["_factory_contract"]["writer_version"] == "legacy_v1",
          "genuine pre-cutover inventory can still be labelled once")

    v21 = {"scenes": [{"id": 1}], "_semantic_verified": True, "_v2_spoken_scene_count": 8}
    check(Q.looks_v21_certified(v21), "V2.1 acceptance markers are recognised")
    check(not Q.looks_v21_certified(legacy_like), "legacy inventory is not mistaken for V2.1")
    try:
        Q.stamp_manifest(v21, writer_version="legacy_v1", cert_version="legacy_generation")
        raise AssertionError("a V2.1-certified manifest must not be stamped legacy")
    except ValueError as exc:
        check("refusing to stamp" in str(exc),
              "stamping a V2.1-certified manifest as legacy fails closed")


def test_factory_proof_measures_its_zero_network_claim():
    """The counters used to be hardcoded 0, so the proof's headline safety
    property held only by inspection: a new import could add an HTTP call and
    every check would still report zero."""
    src = text("quality_downstream_factory_proof.py")
    check('"network_calls_made": len(net_calls)' in src,
          "network_calls_made is a measured count, not a literal")
    check("urllib.request.urlopen = _blocked_urlopen" in src and
          "socket.socket.connect = _blocked_connect" in src,
          "the proof actively intercepts outbound HTTP and socket paths")
    check("socket.create_connection = _blocked_create_connection" in src,
          "create_connection is intercepted too, not just urlopen")
    check("network_calls_detail" in src,
          "any attempted call is named in the evidence, not just counted")
    check("_real_urlopen" in src and "socket.create_connection = _real_create_connection" in src,
          "the interception is always restored, including on failure")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]:
        fn()
    print("production transition contract tests: PASS")
