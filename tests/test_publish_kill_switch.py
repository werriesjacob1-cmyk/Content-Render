#!/usr/bin/env python3
"""Zero-network regression tests for the master social-publishing kill switch."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import publish_publer as P


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_publer_credentials_cannot_bypass_master_switch():
    old = {k: os.environ.get(k) for k in (
        "AUTO_PUBLISH_ENABLED", "PUBLER_API_KEY", "PUBLER_WORKSPACE_ID"
    )}
    calls = {"n": 0}
    original_upload = P.upload_media
    P.upload_media = lambda path: calls.__setitem__("n", calls["n"] + 1) or "media"
    try:
        os.environ.pop("AUTO_PUBLISH_ENABLED", None)
        os.environ["PUBLER_API_KEY"] = "present"
        os.environ["PUBLER_WORKSPACE_ID"] = "present"
        check(P.main() == 0, "unset master switch is a clean no-op")
        check(calls["n"] == 0, "credentials alone cannot reach Publer upload")

        os.environ["AUTO_PUBLISH_ENABLED"] = "false"
        check(P.main() == 0, "explicit false master switch is a clean no-op")
        check(calls["n"] == 0, "false master switch cannot reach Publer upload")
    finally:
        P.upload_media = original_upload
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_workflow_gates_every_publish_surface():
    text = (ROOT / ".github/workflows/render.yml").read_text(encoding="utf-8")
    required = "vars.AUTO_PUBLISH_ENABLED == 'true'"
    release_anchor = "- name: Publish video as a GitHub Release"
    publer_anchor = "- name: Push to Publer"
    check(release_anchor in text and publer_anchor in text,
          "expected GitHub Release and direct Publer publish surfaces exist")

    release = text[text.index(release_anchor):text.index(publer_anchor)]
    publer = text[text.index(publer_anchor):]
    check(required in release, "public GitHub Release is behind master switch")
    check(required in publer, "direct Publer call is behind master switch")
    check("github.event.inputs.certification_only != 'true'" in release,
          "manual certification remains an independent release block")
    check("github.event.inputs.certification_only != 'true'" in publer,
          "manual certification remains an independent Publer block")


def test_exact_lowercase_true_is_required_inside_publer_module():
    # The module gate must agree EXACTLY with the workflow condition
    # (AUTO_PUBLISH_ENABLED == 'true'). Case-folding here would let TRUE/True
    # open the module gate while the workflow kept it shut.
    old = os.environ.get("AUTO_PUBLISH_ENABLED")
    try:
        disabled = (None, "", "0", "1", "false", "yes", "TRUE-ish",
                    "TRUE", "True", "tRuE", "true1", "truthy")
        for value in disabled:
            if value is None:
                os.environ.pop("AUTO_PUBLISH_ENABLED", None)
            else:
                os.environ["AUTO_PUBLISH_ENABLED"] = value
            check(not P._autopublish_enabled(), f"{value!r} does not enable publishing")
        os.environ["AUTO_PUBLISH_ENABLED"] = "true"
        check(P._autopublish_enabled(), "exact lowercase true enables the internal gate")
        os.environ["AUTO_PUBLISH_ENABLED"] = "  true  "
        check(P._autopublish_enabled(),
              "surrounding whitespace is trimmed, but the value itself stays exact")
    finally:
        if old is None:
            os.environ.pop("AUTO_PUBLISH_ENABLED", None)
        else:
            os.environ["AUTO_PUBLISH_ENABLED"] = old


def test_module_gate_and_workflow_gate_agree_on_one_contract():
    text = (ROOT / ".github/workflows/render.yml").read_text(encoding="utf-8")
    check("vars.AUTO_PUBLISH_ENABLED == 'true'" in text,
          "workflow independently requires the exact lowercase literal 'true'")
    source = (ROOT / "publish_publer.py").read_text(encoding="utf-8")
    check('.strip().lower() == "true"' not in source,
          "module gate does not case-fold, so it cannot be looser than the workflow")
    check('.strip() == "true"' in source,
          "module gate compares the trimmed value against exact lowercase true")


def test_disabled_publishing_is_reported_without_implying_the_guard_is_off():
    text = (ROOT / ".github/workflows/render.yml").read_text(encoding="utf-8")
    report = text.split("- name: Report publishing switch", 1)[1].split("- name:", 1)[0]
    check("HARD PUBLISHING KILL SWITCH IS OFF" not in report,
          "disabled state is not described as the safety mechanism being off")
    check("PUBLISHING DISABLED" in report and "PUBLISHING ENABLED" in report,
          "both publishing states are reported in terms of publishing, not the guard")
    source = (ROOT / "publish_publer.py").read_text(encoding="utf-8")
    check("hard publishing kill switch is OFF" not in source,
          "module no-op message does not claim the kill switch is off")
    check("PUBLISHING DISABLED" in source,
          "module states plainly that publishing is disabled")


if __name__ == "__main__":
    test_publer_credentials_cannot_bypass_master_switch()
    test_workflow_gates_every_publish_surface()
    test_exact_lowercase_true_is_required_inside_publer_module()
    test_module_gate_and_workflow_gate_agree_on_one_contract()
    test_disabled_publishing_is_reported_without_implying_the_guard_is_off()
    print("publishing kill-switch tests: PASS")
