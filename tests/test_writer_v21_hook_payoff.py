#!/usr/bin/env python3
"""Zero-network checks for Writer V2.1 hook-surface + payoff diagnostics."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer_v21_hook_payoff as H


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_hook_surfaces_detect_duplicate_copy():
    r = H.hook_surface_report(
        spoken_hook="Your stomach rebuilds the wall its own acid attacks.",
        cover_headline="YOUR STOMACH REBUILDS THE WALL ITS OWN ACID ATTACKS",
        on_screen_hook_text="Your stomach rebuilds the wall its own acid attacks",
        first_frame_visual="human stomach lining close up cells",
    )
    check("cover_repeats_spoken_hook" in r["warnings"], "cover duplication is visible")
    check("on_screen_text_repeats_spoken_hook" in r["warnings"], "on-screen duplication is visible")
    check(r["visual_generic_only"] is False, "specific first-frame subject is not falsely generic")
    check(r["gating"] is False, "hook surface diagnostics are non-gating")


def test_hook_surfaces_reward_complementary_jobs():
    r = H.hook_surface_report(
        spoken_hook="Your stomach rebuilds the wall its own acid attacks.",
        cover_headline="WHY YOUR STOMACH SURVIVES ITSELF",
        on_screen_hook_text="A wall that renews",
        first_frame_visual="stomach lining epithelial cells regenerating close up",
    )
    check("cover_repeats_spoken_hook" not in r["warnings"], "distinct cover copy is preserved")
    check("first_frame_visual_is_generic_or_missing" not in r["warnings"], "specific mechanism visual passes")
    check("first_frame_visual_not_anchored_to_hook_subject" not in r["warnings"], "first frame stays anchored to hook subject")


def test_generic_first_frame_is_flagged():
    r = H.hook_surface_report(
        spoken_hook="A neutron star crushes matter past anything on Earth.",
        cover_headline="MATTER AT THE LIMIT",
        first_frame_visual="science laboratory cinematic footage",
    )
    check("first_frame_visual_is_generic_or_missing" in r["warnings"], "generic lab wallpaper is rejected editorially")


def test_payoff_restatement_is_visible():
    r = H.payoff_proof_report(
        hook="Sharks are older than trees.",
        central_question="How can sharks be older than trees?",
        payoff="Sharks really are older than trees.",
    )
    check("payoff_restates_hook" in r["warnings"], "restated hook cannot masquerade as payoff")
    check(r["gating"] is False, "payoff proof remains telemetry")


def test_specific_resolution_can_pass():
    r = H.payoff_proof_report(
        hook="Your stomach rebuilds the wall its own acid attacks.",
        central_question="Why does stomach acid not digest your stomach?",
        payoff="That happens because the protective lining is constantly replaced before the acid reaches deeper tissue.",
    )
    check(r["resolution_cue_present"] is True, "explicit causal resolution cue is detected")
    check("payoff_has_no_visible_connection_to_opening" not in r["warnings"], "specific causal payoff connects to opening")
    check("generic_ai_payoff" not in r["warnings"], "specific mechanism payoff is not mislabeled AI moralizing")


def test_generic_moralizing_payoff_is_flagged():
    r = H.payoff_proof_report(
        hook="A mantis shrimp punches with extreme force.",
        payoff="Even the smallest hunters remind us that danger often hides in plain sight.",
    )
    check("generic_ai_payoff" in r["warnings"], "known generic mantis-shrimp ending remains caught")
    check(r["generic_payoff_hits"], "exact generic phrase evidence is retained")


def test_manifest_adapter_uses_actual_spoken_endpoints():
    m = {
        "hook": "Your stomach rebuilds the wall its own acid attacks.",
        "hook_headline": "WHY YOUR STOMACH SURVIVES ITSELF",
        "whatif": "Why does stomach acid not digest your stomach?",
        "scenes": [
            {"voiceover": "Your stomach rebuilds the wall its own acid attacks.", "on_screen_text": "A wall that renews", "search_query": "stomach lining epithelial cells"},
            {"voiceover": "That happens because the protective lining is constantly replaced before acid reaches deeper tissue."},
        ],
    }
    r = H.manifest_hook_payoff_report(m)
    check(r["payoff_proof"]["payoff"].startswith("That happens because"), "adapter judges actual spoken final scene")
    check(r["hook_surfaces"]["spoken_hook"].startswith("Your stomach"), "adapter judges actual spoken hook")
    check(r["gating"] is False, "manifest adapter cannot accept/reject")


if __name__ == "__main__":
    test_hook_surfaces_detect_duplicate_copy()
    test_hook_surfaces_reward_complementary_jobs()
    test_generic_first_frame_is_flagged()
    test_payoff_restatement_is_visible()
    test_specific_resolution_can_pass()
    test_generic_moralizing_payoff_is_flagged()
    test_manifest_adapter_uses_actual_spoken_endpoints()
    print("writer_v21 hook/payoff tests: PASS")
