"""Permanent Writer V2.1 known-bad torture corpus.

These are not random examples.  Each case is a real failure class already
observed in Content Render.  The corpus exists so future writer/critic/repair
changes must re-confront the same mistakes instead of rediscovering them during
paid live runs.

Some failures are deterministic (numbers/units/style/repair regression).  Others
require the semantic-support critic because the bad assertion contains no number
or proper noun.  The corpus therefore records the EXPECTED GUARD rather than
pretending every case can be proven with string matching.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import writer_v21_editorial_diagnostics as E
import writer_v21_repair_regression as R


@dataclass(frozen=True)
class TortureCase:
    case_id: str
    failure_class: str
    expected_guard: str
    source_claim: str
    bad_hook: str
    bad_beats: tuple[str, ...]
    bad_payoff: str
    expected_outcome: str
    notes: str = ""
    repaired_hook: str = ""
    repaired_beats: tuple[str, ...] = ()
    repaired_payoff: str = ""

    def spoken(self) -> tuple[str, tuple[str, ...], str]:
        return self.bad_hook, self.bad_beats, self.bad_payoff


CASES: tuple[TortureCase, ...] = (
    TortureCase(
        case_id="mantis_shrimp_blender",
        failure_class="unsupported_comparison",
        expected_guard="semantic_support",
        source_claim="A mantis shrimp strike is extraordinarily fast and creates cavitation bubbles.",
        bad_hook="Your kitchen blender can't match a mantis shrimp's punch.",
        bad_beats=(
            "Its club accelerates through the water before the shell can react.",
            "The strike creates a cavitation bubble beside the target.",
            "That bubble collapses and adds a second shock.",
        ),
        bad_payoff="Even the smallest hunters can wield sun-like power, reminding us that danger often hides in plain sight.",
        expected_outcome="reject",
        notes="Blender comparison is unsupported; payoff is generic moralizing and sun-like flourish is unsupported.",
    ),
    TortureCase(
        case_id="neutron_star_invented_mechanism",
        failure_class="unsupported_mechanism",
        expected_guard="semantic_support",
        source_claim="A teaspoon of neutron-star material would have an enormous mass on Earth.",
        bad_hook="A spoonful of neutron-star matter would outweigh a mountain.",
        bad_beats=(
            "Scientists once assumed it was ultra-dense metal that would simply sink.",
            "Its gravity packs matter far beyond ordinary atoms.",
            "The same idea could one day power ultra-compact energy devices.",
        ),
        bad_payoff="A tiny volume can hide an impossible amount of mass.",
        expected_outcome="reject",
        notes="Observed live: invented history/mechanism/future application can evade number/proper-noun checks.",
    ),
    TortureCase(
        case_id="mauna_kea_invented_framing",
        failure_class="unsupported_authority_framing",
        expected_guard="semantic_support",
        source_claim="Measured from its base on the ocean floor, Mauna Kea is taller than Everest measured from sea level.",
        bad_hook="Mauna Kea dwarfs Everest when measured from its true base.",
        bad_beats=(
            "Geologists note that maps and records must reflect the mountain's true height.",
            "Its underwater base changes the comparison completely.",
            "The definition of tallest depends on where measurement begins.",
        ),
        bad_payoff="Height is a matter of where you start measuring, not just what you see.",
        expected_outcome="reject",
        notes="The authority/records framing was repeatedly invented during live repairs.",
    ),
    TortureCase(
        case_id="lightning_duration_inflation",
        failure_class="quantitative_inflation",
        expected_guard="hard_traceability",
        source_claim="The energy is roughly enough to power a house for one day.",
        bad_hook="One lightning bolt could power your house for months.",
        bad_beats=(
            "A single strike releases a huge burst of energy.",
            "That is enough electricity for about three months in a house.",
            "Most of it arrives too quickly to store efficiently.",
        ),
        bad_payoff="The sky throws away months of household power in an instant.",
        expected_outcome="reject",
        notes="Permanent regression for one-day -> three-month magnitude inflation.",
    ),
    TortureCase(
        case_id="chess_magnitude_only",
        failure_class="magnitude_without_idea",
        expected_guard="editorial_quality",
        source_claim="The number of possible chess games is enormously larger than common physical-count comparisons.",
        bad_hook="The chessboard has more possible games than atoms in the observable universe.",
        bad_beats=(
            "The branching number of legal moves grows extremely quickly.",
            "There are too many possible sequences to list physically.",
            "Thus chess contains more distinct sequences than there are particles in the observable universe.",
        ),
        bad_payoff="A simple game can hide complexity that surpasses the scale of reality itself.",
        expected_outcome="hold_or_repair",
        notes="Facts may be supported, but the script is magnitude-only and ends in generic AI grandeur.",
    ),
    TortureCase(
        case_id="stomach_clinical_repair",
        failure_class="repair_craft_regression",
        expected_guard="repair_regression_pairwise",
        source_claim="The stomach lining is renewed frequently and protects the wall from strong acid.",
        bad_hook="Daily, your stomach walls dissolve in acid you eat.",
        bad_beats=(
            "Your stomach is a relentless acid bath.",
            "A protective lining keeps rebuilding before the damage spreads.",
            "If that barrier fails, acid can injure the tissue underneath.",
        ),
        bad_payoff="Your meals depend on a constant truce between acid and living tissue.",
        repaired_hook="Your stomach lining is constantly bathed in strong acid that could digest it if it didn't rebuild every few days.",
        repaired_beats=(
            "Your stomach contains strong acid used during digestion.",
            "Protective cells continuously renew the lining.",
            "This renewal helps prevent the stomach wall from being damaged.",
        ),
        repaired_payoff="The stomach survives because its protective lining is continuously renewed.",
        expected_outcome="prefer_pre_repair_craft_if_both_factually_safe",
        notes="Observed failure class: factual repair becomes longer, clinical, flatter, and less memorable.",
    ),
)


def cases_by_guard() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for case in CASES:
        out.setdefault(case.expected_guard, []).append(case.case_id)
    return {k: sorted(v) for k, v in sorted(out.items())}


def case_index() -> dict[str, TortureCase]:
    return {case.case_id: case for case in CASES}


def deterministic_editorial_probe(case: TortureCase) -> Mapping[str, Any]:
    """Run only diagnostics that are legitimately deterministic for this case."""
    hook, beats, payoff = case.spoken()
    return E.editorial_diagnostics(hook=hook, beats=beats, payoff=payoff, scenes=[])


def repair_regression_probe(case: TortureCase) -> Mapping[str, Any] | None:
    if not case.repaired_hook:
        return None
    before = {
        "round": 0,
        "hook": case.bad_hook,
        "beats": list(case.bad_beats),
        "payoff": case.bad_payoff,
        "repair_plan": {"repair_type": "PROVENANCE", "target_beats": [0, 1, 2, 3, 4]},
    }
    after = {
        "round": 1,
        "hook": case.repaired_hook,
        "beats": list(case.repaired_beats),
        "payoff": case.repaired_payoff,
    }
    return R.compare_rounds(before, after)


def live_semantic_cases() -> list[dict[str, Any]]:
    """Exact no-network payloads for the next semantic-critic torture run."""
    out: list[dict[str, Any]] = []
    for case in CASES:
        if case.expected_guard != "semantic_support":
            continue
        out.append({
            "case_id": case.case_id,
            "source_claim": case.source_claim,
            "hook": case.bad_hook,
            "beats": list(case.bad_beats),
            "payoff": case.bad_payoff,
            "expected_outcome": case.expected_outcome,
        })
    return out
