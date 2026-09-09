#!/usr/bin/env python3
"""Zero-provider unit checks for the production-realism proof harness."""
from __future__ import annotations

import os
import sys

# This file is executed directly by CI (`python tests/...py`), so Python's
# default sys.path starts at tests/.  Add the repository root explicitly rather
# than relying on a workflow-only PYTHONPATH side effect.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_production_realism_proof as P


def test_fixture_manifest_is_spoken_and_sealed():
    m = P._manifest()
    assert m["_semantic_verified"] is True
    assert m["_v2_spoken_scene_count"] == len(m["scenes"]) == 4
    assert m["hook"] == m["scenes"][0]["voiceover"]
    assert m["payoff"] == m["scenes"][-1]["voiceover"]
    assert all(s["voiceover"].strip() for s in m["scenes"])
    assert all(s["source_claim_ids"] for s in m["scenes"])


def test_realism_contract_uses_production_canvas_and_delivery_audio():
    assert (P.legacy.W, P.legacy.H) == (1080, 1920)
    assert P.AQA.DELIVERY_SAMPLE_RATE == 48000
    assert str(P.AQA.DELIVERY_AUDIO_BITRATE).endswith("k")


def test_probe_validator_rejects_nonproduction_canvas():
    bad = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 540, "height": 960},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
        ],
        "format": {"duration": "4.0", "size": "10000"},
    }
    try:
        P._assert_final_media(bad)
    except RuntimeError as e:
        assert "wrong production canvas" in str(e)
    else:
        raise AssertionError("nonproduction canvas was accepted")


def test_probe_validator_accepts_production_delivery_shape():
    good = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
        ],
        "format": {"duration": "18.25", "size": "123456"},
    }
    out = P._assert_final_media(good)
    assert out["width"] == 1080
    assert out["height"] == 1920
    assert out["audio_codec"] == "aac"
    assert out["audio_sample_rate"] == 48000
    assert out["duration_s"] == 18.25


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
