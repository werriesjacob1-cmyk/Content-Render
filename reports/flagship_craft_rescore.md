# Retrospective craft rescore — flagships 02-07

Metric fixed in `reports/CRAFT_METRIC_PREREGISTRATION.md` **before** any
delta below was computed. Deterministic, zero LLM, zero network.

## Identity

```
{
  "code_sha": "f4221de8bb5ca9cfd6c4a047282fa015b4555235",
  "fixture_sha256_16": {
    "flagship_02_2dbad04.json": "6a8c21fc4c358d21",
    "flagship_03_4b7584c.json": "58403b12674bd3e3",
    "flagship_04_39275e3.json": "839b2c2f28d15adc",
    "flagship_05_240bdc1.json": "cec5c2ae14aa173b",
    "flagship_06_fed4b0f.json": "b4c87fd27b7cb673",
    "flagship_07_greenland_shark_age.json": "4659b4b19161bed3"
  },
  "scorer_sha256_16": {
    "writer_v21_editorial_diagnostics.py": "5626a4303911620e",
    "writer_v21_story_shape.py": "12a3782aba2e9055",
    "writer_v21_hook_payoff.py": "abbbdbf7d79a2fcb"
  },
  "components": [
    "generic_ai_moralizing",
    "generic_payoff_hits",
    "unique_function_count",
    "repeated_primary_runs",
    "resolution_cue_present"
  ],
  "provider_calls": 0,
  "network_calls": 0
}
```

## Headline

- parent->child pairs: **36**
- **craft-measurable pairs: 36 of 36 (100%)** — was **1 of 36 (2.8%)** with `score.overall`
- pairs with factual/mechanical improvement: **24**

## The north-star question

| population | IMPROVED | FLAT | DEGRADED |
|---|---|---|---|
| all pairs (N=36) | 11 | 12 | 13 |
| **mechanical improvement (N=24)** | **10** | **5** | **9** |

- pairs introducing a NEW violation: **8** (craft: {'IMPROVED': 3, 'FLAT': 4, 'DEGRADED': 1})

## Per-component totals (raw magnitudes, not signs)

| component | mean delta, all | mean delta, mech-improved | worsened | improved |
|---|---|---|---|---|
| `generic_ai_moralizing` (lower better) | -0.08 | -0.12 | 0 | 3 |
| `generic_payoff_hits` (lower better) | +0.00 | +0.00 | 0 | 0 |
| `unique_function_count` (higher better) | -0.17 | -0.04 | 11 | 7 |
| `repeated_primary_runs` (lower better) | +0.25 | +0.29 | 8 | 6 |
| `resolution_cue_present` (higher better) | +0.00 | +0.00 | 0 | 0 |

## By repair type

| repair_type | N | IMPROVED | FLAT | DEGRADED |
|---|---|---|---|---|
| PROVENANCE | 32 | 11 | 8 | 13 |
| STRUCTURAL | 3 | 0 | 3 | 0 |
| HOOK | 1 | 0 | 1 | 0 |

## By flagship (N per cell is tiny — descriptive only)

| flagship | topic | N | IMPROVED | FLAT | DEGRADED |
|---|---|---|---|---|---|
| 02 | greenland_shark | 4 | 0 | 2 | 2 |
| 03 | venus_day | 6 | 3 | 1 | 2 |
| 04 | venus_day | 8 | 1 | 4 | 3 |
| 05 | greenland_shark | 6 | 2 | 2 | 2 |
| 06 | greenland_shark_age | 6 | 2 | 2 | 2 |
| 07 | greenland_shark_age | 6 | 3 | 1 | 2 |

## Every pair

| fx | att | pair | repair_type | mech+ | new viol | generic_ai_mor | generic_payoff | unique_functio | repeated_prima | resolution_cue | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 02 | 1 | 0->1 | PROVENANCE | - | Y | +0 | +0 | -1 | +2 | +0 | DEGRADED |
| 02 | 1 | 1->2 | PROVENANCE | Y | - | +0 | +0 | +0 | +0 | +0 | FLAT |
| 02 | 2 | 0->1 | STRUCTURAL | - | Y | +0 | +0 | +0 | +0 | +0 | FLAT |
| 02 | 2 | 1->2 | PROVENANCE | Y | - | +0 | +0 | -2 | +3 | +0 | DEGRADED |
| 03 | 1 | 0->1 | PROVENANCE | Y | - | -1 | +0 | +1 | +0 | +0 | IMPROVED |
| 03 | 1 | 1->2 | PROVENANCE | - | - | +0 | +0 | -2 | +1 | +0 | DEGRADED |
| 03 | 2 | 0->1 | PROVENANCE | Y | - | +0 | +0 | +1 | +0 | +0 | IMPROVED |
| 03 | 2 | 1->2 | PROVENANCE | Y | - | +0 | +0 | -1 | +0 | +0 | DEGRADED |
| 03 | 3 | 0->1 | PROVENANCE | Y | - | +0 | +0 | +0 | +0 | +0 | FLAT |
| 03 | 3 | 1->2 | PROVENANCE | Y | - | +0 | +0 | +1 | +0 | +0 | IMPROVED |
| 04 | 1 | 0->1 | PROVENANCE | Y | - | +0 | +0 | +0 | +0 | +0 | FLAT |
| 04 | 1 | 1->2 | STRUCTURAL | - | - | +0 | +0 | +0 | +0 | +0 | FLAT |
| 04 | 2 | 0->1 | PROVENANCE | Y | - | +0 | +0 | -1 | +3 | +0 | DEGRADED |
| 04 | 2 | 1->2 | PROVENANCE | Y | - | -1 | +0 | +0 | +0 | +0 | IMPROVED |
| 04 | 3 | 0->1 | PROVENANCE | Y | - | +0 | +0 | +0 | +0 | +0 | FLAT |
| 04 | 3 | 1->2 | PROVENANCE | Y | - | +0 | +0 | -1 | +0 | +0 | DEGRADED |
| 04 | 4 | 0->1 | PROVENANCE | Y | - | +0 | +0 | +0 | +1 | +0 | DEGRADED |
| 04 | 4 | 1->2 | PROVENANCE | Y | Y | +0 | +0 | +0 | +0 | +0 | FLAT |
| 05 | 1 | 0->1 | PROVENANCE | Y | - | +0 | +0 | +1 | -1 | +0 | IMPROVED |
| 05 | 1 | 1->2 | STRUCTURAL | - | - | +0 | +0 | +0 | +0 | +0 | FLAT |
| 05 | 2 | 0->1 | PROVENANCE | Y | - | +0 | +0 | -1 | +0 | +0 | DEGRADED |
| 05 | 2 | 1->2 | PROVENANCE | Y | Y | -1 | +0 | +0 | -1 | +0 | IMPROVED |
| 05 | 3 | 0->1 | PROVENANCE | - | - | +0 | +0 | -1 | +0 | +0 | DEGRADED |
| 05 | 3 | 1->2 | PROVENANCE | - | - | +0 | +0 | +0 | +0 | +0 | FLAT |
| 06 | 1 | 0->1 | PROVENANCE | Y | - | +0 | +0 | -1 | +1 | +0 | DEGRADED |
| 06 | 1 | 1->2 | PROVENANCE | - | - | +0 | +0 | +0 | +0 | +0 | FLAT |
| 06 | 2 | 0->1 | PROVENANCE | Y | - | +0 | +0 | +1 | +0 | +0 | IMPROVED |
| 06 | 2 | 1->2 | PROVENANCE | - | - | +0 | +0 | -1 | +0 | +0 | DEGRADED |
| 06 | 3 | 0->1 | PROVENANCE | Y | - | +0 | +0 | +0 | -1 | +0 | IMPROVED |
| 06 | 3 | 1->2 | HOOK | - | Y | +0 | +0 | +0 | +0 | +0 | FLAT |
| 07 | 1 | 0->1 | PROVENANCE | Y | - | +0 | +0 | -1 | +4 | +0 | DEGRADED |
| 07 | 1 | 1->2 | PROVENANCE | Y | - | +0 | +0 | +1 | -2 | +0 | IMPROVED |
| 07 | 2 | 0->1 | PROVENANCE | - | Y | +0 | +0 | +0 | +0 | +0 | FLAT |
| 07 | 2 | 1->2 | PROVENANCE | - | Y | +0 | +0 | +0 | -1 | +0 | IMPROVED |
| 07 | 3 | 0->1 | PROVENANCE | Y | Y | +0 | +0 | +1 | -1 | +0 | IMPROVED |
| 07 | 3 | 1->2 | PROVENANCE | Y | - | +0 | +0 | +0 | +1 | +0 | DEGRADED |

## Limits

36 pairs from 6 runs on a few topics is a convenience corpus, not a sample of
any population. No significance testing is offered and none is implied. The
five components are proxies for craft, not craft: a repair could move all five
the right way and still read worse aloud.
