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
    V2.1 manifests do carry it, so every certified spoken unit must be present,
    ordered, nonblank, and identity-stable before renderer narration begins.
    """
    expected = manifest.get("_v2_spoken_scene_count")
    if expected is None:
        return
    if type(expected) is not int or expected < 2:
        raise NarrationContractError("invalid _v2_spoken_scene_count")
    if not isinstance(scenes, list):
        raise NarrationContractError("V2.1 scenes must be a list")
    if len(scenes) != expected:
        raise NarrationContractError(
            f"V2.1 scene count drift: expected {expected}, found {len(scenes)}"
        )
    if any(not isinstance(scene, dict) for scene in scenes):
        raise NarrationContractError("V2.1 every scene must be an object")

    ids = [scene.get("id") for scene in scenes]
    if any(type(scene_id) is not int for scene_id in ids):
        raise NarrationContractError("V2.1 scene IDs must be integers")
    expected_ids = list(range(1, expected + 1))
    if ids != expected_ids:
        raise NarrationContractError(
            f"V2.1 scene ID drift: expected {expected_ids}, found {ids}"
        )

    for scene_id, scene in zip(ids, scenes):
        voiceover = scene.get("voiceover")
        if not isinstance(voiceover, str) or not voiceover.strip():
            raise NarrationContractError(f"V2.1 scene {scene_id} has blank or missing voiceover")

    first = scenes[0]
    last = scenes[-1]
    if first.get("_v2_role") != "hook" or last.get("_v2_role") != "payoff":
        raise NarrationContractError("V2.1 first/last scene roles are not hook/payoff")
    if any(scene.get("_v2_role") != "beat" for scene in scenes[1:-1]):
        raise NarrationContractError("V2.1 middle scene role drift: expected only beats")
    hook = (manifest.get("hook") or "").strip()
    payoff = (manifest.get("payoff") or "").strip()
    if hook != first["voiceover"].strip():
        raise NarrationContractError("top-level hook drifted from first spoken scene")
    if payoff != last["voiceover"].strip():
        raise NarrationContractError("top-level payoff drifted from final spoken scene")


def spoken_text(manifest: dict) -> str:
    """Return the one canonical text string sent to narration synthesis.

    This deliberately uses ``manifest[\"scenes\"][*][\"voiceover\"]`` and the
    exact terminal-punctuation normalization main.py used before this function
    existed. Missing structural keys continue to raise rather than silently
    inventing/falling back. V2.1 manifests additionally fail closed on scene
    count/identity/role/text drift and hook/payoff endpoint disagreement.

    ``manifest[\"script\"]`` remains derived compatibility metadata, not a
    second narration authority; renderer correctness depends only on scenes.
    """
    scenes = manifest["scenes"]
    _assert_v21_contract(manifest, scenes)
    return " ".join(_terminate(scene["voiceover"]) for scene in scenes)
