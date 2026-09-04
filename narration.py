"""Canonical spoken-narration contract shared by generation and rendering.

The renderer must synthesize exactly the scene voiceovers, in scene order.  This
module is intentionally pure and has no provider/render dependencies so the
same contract can be asserted in Writer tests and used directly by ``main.py``.
"""
from __future__ import annotations


_TERMINAL_PUNCTUATION = ".!?…:"


class NarrationContractError(ValueError):
    """The manifest's certified V2.1 spoken surfaces disagree with its scenes."""


def _terminate(text: str) -> str:
    """Preserve main.py's pre-existing TTS sentence-boundary behavior exactly."""
    text = (text or "").strip()
    return text if text[-1:] in _TERMINAL_PUNCTUATION else text + "."


def _assert_v21_contract(manifest: dict, scenes: list[dict]) -> None:
    """Fail closed on drift for manifests assembled under the V2.1 contract.

    Legacy manifests intentionally do not carry ``_v2_spoken_scene_count`` and
    therefore keep their historical scene-only narration behavior unchanged.
    V2.1 manifests do carry it, so top-level hook/payoff may never silently drift
    away from the exact first/last scenes the renderer will speak.
    """
    expected = manifest.get("_v2_spoken_scene_count")
    if expected is None:
        return
    if not isinstance(expected, int) or expected < 2:
        raise NarrationContractError("invalid _v2_spoken_scene_count")
    if len(scenes) != expected:
        raise NarrationContractError(
            f"V2.1 scene count drift: expected {expected}, found {len(scenes)}"
        )
    first = scenes[0]
    last = scenes[-1]
    if first.get("_v2_role") != "hook" or last.get("_v2_role") != "payoff":
        raise NarrationContractError("V2.1 first/last scene roles are not hook/payoff")
    hook = (manifest.get("hook") or "").strip()
    payoff = (manifest.get("payoff") or "").strip()
    if hook != (first.get("voiceover") or "").strip():
        raise NarrationContractError("top-level hook drifted from first spoken scene")
    if payoff != (last.get("voiceover") or "").strip():
        raise NarrationContractError("top-level payoff drifted from final spoken scene")


def spoken_text(manifest: dict) -> str:
    """Return the one canonical text string sent to narration synthesis.

    This deliberately uses ``manifest[\"scenes\"][*][\"voiceover\"]`` and the
    exact terminal-punctuation normalization main.py used before this function
    existed. Missing structural keys continue to raise rather than silently
    inventing/falling back.  V2.1 manifests additionally fail closed if their
    certified hook/payoff surfaces have drifted from the spoken scenes.
    """
    scenes = manifest["scenes"]
    _assert_v21_contract(manifest, scenes)
    return " ".join(_terminate(scene["voiceover"]) for scene in scenes)
