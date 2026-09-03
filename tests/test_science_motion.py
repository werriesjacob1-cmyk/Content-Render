#!/usr/bin/env python3
"""Zero-network tests for science_motion.py."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from science_motion import (  # noqa: E402
    FlowStep,
    LayerItem,
    MotionKind,
    ScaleItem,
    ScienceMotionSpec,
    TimelineMarker,
    compile_filtergraph,
    enforce_budget if False else None,
    ffmpeg_command,
    provenance_manifest,
    render_science_motion,
)


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_scale_provenance_and_log_label():
    spec = ScienceMotionSpec(
        kind=MotionKind.SCALE_COMPARE,
        title="THE SCALE DIFFERENCE",
        subtitle="Same unit, very different size",
        duration=4.0,
        source_claim_ids=("claim_scale",),
        scale_items=(
            ScaleItem("Object A", 1.0, "1 unit", "claim_a"),
            ScaleItem("Object B", 1000.0, "1,000 units", "claim_b"),
        ),
    )
    check(not spec.validate(), "valid scale comparison passes")
    check(spec.all_claim_ids() == ("claim_scale", "claim_a", "claim_b"),
          "all quantitative source claims are preserved")
    graph = compile_filtergraph(spec)
    check("LOG SCALE" in graph, "extreme ratio is explicitly labeled log scale")
    check("1\,000 units" in graph, "display value is escaped for FFmpeg safely")
    manifest = provenance_manifest(spec)
    check(manifest["deterministic"] is True and manifest["ai_generation"] is False,
          "science motion declares deterministic/no-AI provenance")
    check(manifest["source_claim_ids"] == ["claim_scale", "claim_a", "claim_b"],
          "render provenance carries every source claim")


def test_quantities_fail_closed_without_sources():
    bad = ScienceMotionSpec(
        kind=MotionKind.SCALE_COMPARE,
        title="BAD",
        duration=3,
        source_claim_ids=("claim_scene",),
        scale_items=(
            ScaleItem("A", 1, "1", ""),
            ScaleItem("B", 2, "2", "claim_b"),
        ),
    )
    errors = bad.validate()
    check(any("source_claim_id" in e for e in errors),
          "scale number without source claim is rejected")


def test_timeline_never_infers_dates():
    good = ScienceMotionSpec(
        kind=MotionKind.TIMELINE,
        title="WHAT CHANGED",
        duration=4,
        source_claim_ids=("claim_timeline",),
        timeline_markers=(
            TimelineMarker(0.0, "Start", "4.5 billion years ago", "claim_start"),
            TimelineMarker(0.7, "Transition", "2.4 billion years ago", "claim_mid"),
            TimelineMarker(1.0, "Now", "Today", "claim_now"),
        ),
    )
    check(not good.validate(), "explicit timeline passes")
    graph = compile_filtergraph(good)
    check("4.5 billion years ago" in graph and "Today" in graph,
          "timeline only renders supplied display times")

    reversed_spec = ScienceMotionSpec(
        kind=MotionKind.TIMELINE,
        title="BROKEN",
        duration=4,
        source_claim_ids=("claim_timeline",),
        timeline_markers=(
            TimelineMarker(0.8, "Later", "Later", "c1"),
            TimelineMarker(0.2, "Earlier", "Earlier", "c2"),
        ),
    )
    check(any("monotonic" in e for e in reversed_spec.validate()),
          "caller must supply monotonic timeline positions")


def test_flow_and_layers_require_claims():
    flow = ScienceMotionSpec(
        kind=MotionKind.PROCESS_FLOW,
        title="HOW IT HAPPENS",
        duration=4,
        source_claim_ids=("process",),
        flow_steps=(
            FlowStep("Pressure builds", ("p1",)),
            FlowStep("Material deforms", ("p2",)),
            FlowStep("Energy releases", ("p3",)),
        ),
    )
    check(not flow.validate(), "source-backed process flow passes")
    graph = compile_filtergraph(flow)
    check("Pressure builds" in graph and "Energy releases" in graph,
          "process labels enter deterministic filtergraph")

    layers = ScienceMotionSpec(
        kind=MotionKind.LAYER_STACK,
        title="INSIDE THE SYSTEM",
        duration=4,
        source_claim_ids=("layers",),
        layers=(
            LayerItem("Outer layer", ("l1",)),
            LayerItem("Middle layer", ("l2",)),
            LayerItem("Core", ("l3",)),
        ),
    )
    check(not layers.validate(), "source-backed layered mechanism passes")
    check("Core" in compile_filtergraph(layers), "layer labels render")


def test_ffmpeg_command_is_local_and_vertical():
    spec = ScienceMotionSpec(
        kind=MotionKind.PROCESS_FLOW,
        title="LOCAL RENDER",
        duration=2,
        source_claim_ids=("c0",),
        flow_steps=(
            FlowStep("Step one", ("c1",)),
            FlowStep("Step two", ("c2",)),
        ),
    )
    cmd = ffmpeg_command(spec, "out.mp4")
    joined = " ".join(cmd)
    check(cmd[0] == "ffmpeg", "renderer uses existing FFmpeg stack")
    check("1080x1920" in joined, "renderer is native 9:16 vertical")
    check("http://" not in joined and "https://" not in joined,
          "deterministic science render requires no network")
    check("libx264" in cmd and "yuv420p" in cmd, "output matches production-compatible video codec")


def test_real_ffmpeg_smoke():
    if not shutil.which("ffmpeg"):
        print("PASS ffmpeg smoke skipped: ffmpeg unavailable on this runner")
        return
    spec = ScienceMotionSpec(
        kind=MotionKind.PROCESS_FLOW,
        title="SCIENCE MOTION",
        duration=1.2,
        source_claim_ids=("smoke",),
        flow_steps=(
            FlowStep("Observe", ("smoke1",)),
            FlowStep("Explain", ("smoke2",)),
        ),
    )
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "science.mp4")
        render_science_motion(spec, out)
        check(os.path.exists(out) and os.path.getsize(out) > 1000,
              "real FFmpeg science motion produces a usable MP4")


if __name__ == "__main__":
    test_scale_provenance_and_log_label()
    test_quantities_fail_closed_without_sources()
    test_timeline_never_infers_dates()
    test_flow_and_layers_require_claims()
    test_ffmpeg_command_is_local_and_vertical()
    test_real_ffmpeg_smoke()
    print("science_motion tests: PASS")
