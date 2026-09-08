"""Deterministic scientific motion graphics for Content Render.

The renderer creates purpose-built vertical science scenes with the FFmpeg stack
already used by main.py.  It never researches, infers, or invents quantities.
Every factual visual payload must be supplied explicitly and tied to one or more
source claim IDs.

This is intentionally a small deterministic backend, not a replacement for
authentic media.  The Visual Director should route here when a scale, timeline,
process, or layered mechanism is clearer in code than in stock/AI footage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import os
import re
import subprocess
import tempfile
from typing import Iterable, Sequence


W = 1080
H = 1920
FPS = 30


class MotionKind(str, Enum):
    SCALE_COMPARE = "scale_compare"
    TIMELINE = "timeline"
    PROCESS_FLOW = "process_flow"
    LAYER_STACK = "layer_stack"


@dataclass(frozen=True)
class ScaleItem:
    label: str
    value: float
    display_value: str
    source_claim_id: str

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.label.strip():
            errors.append("scale item label required")
        if not math.isfinite(float(self.value)) or float(self.value) <= 0:
            errors.append("scale item value must be finite and > 0")
        if not self.display_value.strip():
            errors.append("scale item display_value required")
        if not self.source_claim_id.strip():
            errors.append("scale item source_claim_id required")
        return errors


@dataclass(frozen=True)
class TimelineMarker:
    position: float  # caller supplies normalized 0..1 placement; no date inference
    label: str
    display_time: str
    source_claim_id: str

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not 0.0 <= float(self.position) <= 1.0:
            errors.append("timeline position must be 0..1")
        if not self.label.strip():
            errors.append("timeline marker label required")
        if not self.display_time.strip():
            errors.append("timeline display_time required")
        if not self.source_claim_id.strip():
            errors.append("timeline source_claim_id required")
        return errors


@dataclass(frozen=True)
class FlowStep:
    label: str
    source_claim_ids: tuple[str, ...]

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.label.strip():
            errors.append("flow step label required")
        if not self.source_claim_ids or any(not x.strip() for x in self.source_claim_ids):
            errors.append("flow step requires source_claim_ids")
        return errors


@dataclass(frozen=True)
class LayerItem:
    label: str
    source_claim_ids: tuple[str, ...]

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.label.strip():
            errors.append("layer label required")
        if not self.source_claim_ids or any(not x.strip() for x in self.source_claim_ids):
            errors.append("layer requires source_claim_ids")
        return errors


@dataclass(frozen=True)
class ScienceMotionSpec:
    kind: MotionKind
    title: str
    duration: float
    source_claim_ids: tuple[str, ...]
    scale_items: tuple[ScaleItem, ...] = ()
    timeline_markers: tuple[TimelineMarker, ...] = ()
    flow_steps: tuple[FlowStep, ...] = ()
    layers: tuple[LayerItem, ...] = ()
    subtitle: str = ""
    background: str = "0x0B1018"
    accent: str = "0xF4C542"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.title.strip():
            errors.append("title required")
        if not math.isfinite(float(self.duration)) or not (1.0 <= float(self.duration) <= 20.0):
            errors.append("duration must be 1..20 seconds")
        if not self.source_claim_ids or any(not x.strip() for x in self.source_claim_ids):
            errors.append("source_claim_ids required for every science motion scene")

        if self.kind == MotionKind.SCALE_COMPARE:
            if not (2 <= len(self.scale_items) <= 4):
                errors.append("scale_compare requires 2..4 items")
            for i, item in enumerate(self.scale_items):
                errors.extend(f"scale_items[{i}]: {e}" for e in item.validate())
        elif self.kind == MotionKind.TIMELINE:
            if not (2 <= len(self.timeline_markers) <= 5):
                errors.append("timeline requires 2..5 markers")
            for i, item in enumerate(self.timeline_markers):
                errors.extend(f"timeline_markers[{i}]: {e}" for e in item.validate())
            positions = [float(x.position) for x in self.timeline_markers]
            if positions != sorted(positions):
                errors.append("timeline marker positions must be monotonic")
        elif self.kind == MotionKind.PROCESS_FLOW:
            if not (2 <= len(self.flow_steps) <= 5):
                errors.append("process_flow requires 2..5 steps")
            for i, item in enumerate(self.flow_steps):
                errors.extend(f"flow_steps[{i}]: {e}" for e in item.validate())
        elif self.kind == MotionKind.LAYER_STACK:
            if not (2 <= len(self.layers) <= 6):
                errors.append("layer_stack requires 2..6 layers")
            for i, item in enumerate(self.layers):
                errors.extend(f"layers[{i}]: {e}" for e in item.validate())
        else:
            errors.append(f"unsupported kind: {self.kind}")
        return errors

    def all_claim_ids(self) -> tuple[str, ...]:
        out: list[str] = list(self.source_claim_ids)
        if self.kind == MotionKind.SCALE_COMPARE:
            out.extend(x.source_claim_id for x in self.scale_items)
        elif self.kind == MotionKind.TIMELINE:
            out.extend(x.source_claim_id for x in self.timeline_markers)
        elif self.kind == MotionKind.PROCESS_FLOW:
            for x in self.flow_steps:
                out.extend(x.source_claim_ids)
        elif self.kind == MotionKind.LAYER_STACK:
            for x in self.layers:
                out.extend(x.source_claim_ids)
        return tuple(dict.fromkeys(out))


def _ff_escape(value: str) -> str:
    """Escape short text for FFmpeg drawtext text=.

    We intentionally reject newlines/control characters and keep labels short;
    long-form narration remains in the normal caption system.
    """
    value = re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()
    value = re.sub(r"\s+", " ", value)[:80]
    return (
        value.replace("\\", "\\\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace("%", r"\%")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
    )


def _font_opt(font_path: str | None) -> str:
    if not font_path:
        return ""
    return f":fontfile='{_ff_escape(font_path)}'"


def _fade_alpha(start: float, fade: float = 0.25) -> str:
    start = max(0.0, float(start))
    fade = max(0.05, float(fade))
    return (
        f"if(lt(t,{start:.3f}),0,"
        f"if(lt(t,{start + fade:.3f}),(t-{start:.3f})/{fade:.3f},1))"
    )


def _base_filters(spec: ScienceMotionSpec, font_path: str | None) -> list[str]:
    font = _font_opt(font_path)
    filters = [
        "format=yuv420p",
        f"drawtext=text='{_ff_escape(spec.title)}'{font}:fontsize=74:fontcolor=white:"
        f"x=(w-tw)/2:y=150:alpha='{_fade_alpha(0.05, 0.25)}'",
        f"drawbox=x=120:y=270:w=840:h=5:color={spec.accent}@0.95:t=fill",
    ]
    if spec.subtitle.strip():
        filters.append(
            f"drawtext=text='{_ff_escape(spec.subtitle)}'{font}:fontsize=40:"
            f"fontcolor=white@0.72:x=(w-tw)/2:y=300:alpha='{_fade_alpha(0.2, 0.25)}'"
        )
    return filters


def _scale_filters(spec: ScienceMotionSpec, font_path: str | None) -> list[str]:
    font = _font_opt(font_path)
    items = spec.scale_items
    values = [float(x.value) for x in items]
    vmax = max(values)
    vmin = min(values)
    # Huge ratios become unreadable linearly. A log scale is visually honest
    # only when explicitly labeled, so we label it mechanically here.
    use_log = vmax / vmin > 40.0
    if use_log:
        transformed = [math.log10(v / vmin + 1.0) for v in values]
        denom = max(transformed)
    else:
        transformed = values
        denom = vmax

    filters = _base_filters(spec, font_path)
    y0, gap, bar_x, max_w = 520, 260, 150, 760
    if use_log:
        filters.append(
            f"drawtext=text='LOG SCALE'{font}:fontsize=30:fontcolor={spec.accent}:"
            f"x=150:y=410:alpha='{_fade_alpha(0.35)}'"
        )
    for i, (item, tv) in enumerate(zip(items, transformed)):
        y = y0 + i * gap
        width = max(28, int(max_w * tv / denom))
        reveal = 0.45 + i * 0.55
        filters.extend([
            f"drawtext=text='{_ff_escape(item.label)}'{font}:fontsize=46:fontcolor=white:"
            f"x={bar_x}:y={y-68}:alpha='{_fade_alpha(reveal)}'",
            f"drawbox=x={bar_x}:y={y}:w={width}:h=74:color={spec.accent}@0.88:t=fill:"
            f"enable='gte(t,{reveal + 0.15:.3f})'",
            f"drawtext=text='{_ff_escape(item.display_value)}'{font}:fontsize=42:fontcolor=white:"
            f"x={min(bar_x + width + 22, 850)}:y={y+12}:alpha='{_fade_alpha(reveal + 0.2)}'",
        ])
    return filters


def _timeline_filters(spec: ScienceMotionSpec, font_path: str | None) -> list[str]:
    font = _font_opt(font_path)
    filters = _base_filters(spec, font_path)
    x0, x1, y = 150, 930, 930
    filters.append(f"drawbox=x={x0}:y={y}:w={x1-x0}:h=8:color=white@0.30:t=fill")
    for i, marker in enumerate(spec.timeline_markers):
        x = int(x0 + float(marker.position) * (x1 - x0))
        reveal = 0.45 + i * 0.55
        label_y = y - 150 if i % 2 == 0 else y + 65
        time_y = label_y + 62
        filters.extend([
            f"drawbox=x={x-10}:y={y-28}:w=20:h=64:color={spec.accent}@0.95:t=fill:"
            f"enable='gte(t,{reveal:.3f})'",
            f"drawtext=text='{_ff_escape(marker.label)}'{font}:fontsize=34:fontcolor=white:"
            f"x={max(30, min(x-110, 830))}:y={label_y}:alpha='{_fade_alpha(reveal)}'",
            f"drawtext=text='{_ff_escape(marker.display_time)}'{font}:fontsize=30:"
            f"fontcolor={spec.accent}:x={max(30, min(x-110, 830))}:y={time_y}:"
            f"alpha='{_fade_alpha(reveal + 0.1)}'",
        ])
    return filters


def _flow_filters(spec: ScienceMotionSpec, font_path: str | None) -> list[str]:
    font = _font_opt(font_path)
    filters = _base_filters(spec, font_path)
    steps = spec.flow_steps
    card_w, card_h, x = 780, 150, 150
    top, gap = 470, 245
    for i, step in enumerate(steps):
        y = top + i * gap
        reveal = 0.35 + i * 0.5
        filters.extend([
            f"drawbox=x={x}:y={y}:w={card_w}:h={card_h}:color=white@0.10:t=fill:"
            f"enable='gte(t,{reveal:.3f})'",
            f"drawbox=x={x}:y={y}:w=12:h={card_h}:color={spec.accent}@0.95:t=fill:"
            f"enable='gte(t,{reveal:.3f})'",
            f"drawtext=text='{_ff_escape(str(i+1))}'{font}:fontsize=42:fontcolor={spec.accent}:"
            f"x={x+42}:y={y+48}:alpha='{_fade_alpha(reveal)}'",
            f"drawtext=text='{_ff_escape(step.label)}'{font}:fontsize=42:fontcolor=white:"
            f"x={x+105}:y={y+48}:alpha='{_fade_alpha(reveal)}'",
        ])
        if i < len(steps) - 1:
            filters.append(
                f"drawbox=x=535:y={y+card_h}:w=10:h={gap-card_h}:"
                f"color=white@0.28:t=fill:enable='gte(t,{reveal + 0.22:.3f})'"
            )
    return filters


def _layer_filters(spec: ScienceMotionSpec, font_path: str | None) -> list[str]:
    font = _font_opt(font_path)
    filters = _base_filters(spec, font_path)
    n = len(spec.layers)
    total_h = min(1050, n * 175)
    layer_h = max(120, total_h // n)
    x, w, bottom = 145, 790, 1530
    for i, layer in enumerate(spec.layers):
        # Input order is conceptually outer/top -> inner/bottom. Reveal from the
        # outside downward so the mechanism reads as a progressive cross-section.
        y = bottom - (i + 1) * layer_h
        reveal = 0.4 + i * 0.45
        alpha = min(0.18 + i * 0.08, 0.55)
        filters.extend([
            f"drawbox=x={x}:y={y}:w={w}:h={layer_h-8}:color={spec.accent}@{alpha:.2f}:"
            f"t=fill:enable='gte(t,{reveal:.3f})'",
            f"drawbox=x={x}:y={y}:w={w}:h={layer_h-8}:color=white@0.22:t=3:"
            f"enable='gte(t,{reveal:.3f})'",
            f"drawtext=text='{_ff_escape(layer.label)}'{font}:fontsize=38:fontcolor=white:"
            f"x={x+35}:y={y + layer_h//2 - 20}:alpha='{_fade_alpha(reveal)}'",
        ])
    return filters


def compile_filtergraph(spec: ScienceMotionSpec, font_path: str | None = None) -> str:
    errors = spec.validate()
    if errors:
        raise ValueError("; ".join(errors))
    if spec.kind == MotionKind.SCALE_COMPARE:
        filters = _scale_filters(spec, font_path)
    elif spec.kind == MotionKind.TIMELINE:
        filters = _timeline_filters(spec, font_path)
    elif spec.kind == MotionKind.PROCESS_FLOW:
        filters = _flow_filters(spec, font_path)
    elif spec.kind == MotionKind.LAYER_STACK:
        filters = _layer_filters(spec, font_path)
    else:
        raise ValueError(f"unsupported kind: {spec.kind}")
    return ",".join(filters)


def ffmpeg_command(
    spec: ScienceMotionSpec,
    out_path: str,
    *,
    audio_path: str | None = None,
    font_path: str | None = None,
) -> list[str]:
    """Build the production-compatible FFmpeg command without executing it."""
    graph = compile_filtergraph(spec, font_path)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"color=c={spec.background}:s={W}x{H}:d={spec.duration:.3f}:r={FPS}",
    ]
    if audio_path:
        cmd += ["-i", audio_path]
    cmd += ["-t", f"{spec.duration:.3f}", "-vf", graph]
    if audio_path:
        cmd += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-r", str(FPS), "-pix_fmt", "yuv420p", "-c:v", "libx264", out_path]
    return cmd


def render_science_motion(
    spec: ScienceMotionSpec,
    out_path: str,
    *,
    audio_path: str | None = None,
    font_path: str | None = None,
    timeout: int = 90,
) -> str:
    """Render a deterministic science scene. No network and no AI calls."""
    cmd = ffmpeg_command(
        spec, out_path, audio_path=audio_path, font_path=font_path
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg science motion failed: {proc.stderr[-1600:]}")
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        raise RuntimeError("ffmpeg science motion produced no usable output")
    return out_path


def provenance_manifest(spec: ScienceMotionSpec) -> dict:
    """Internal evidence record that travels with a rendered science scene."""
    errors = spec.validate()
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "renderer": "science_motion_ffmpeg_v1",
        "kind": spec.kind.value,
        "title": spec.title,
        "duration": spec.duration,
        "source_claim_ids": list(spec.all_claim_ids()),
        "deterministic": True,
        "network_calls": 0,
        "ai_generation": False,
    }
