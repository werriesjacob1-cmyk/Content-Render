#!/usr/bin/env python3
"""Entry point for the corrected Writer V2.1 takeover bakeoff.

Uses the established verbose torture-panel reporter but swaps its candidate
engine to ``writer_v21_runtime`` so the live panel simultaneously exercises:
- semantic fail-closed orchestration;
- bounded semantic retry;
- quality-floor enforcement;
- spoken hook + middle beats + payoff render manifest.

No render or publishing code is called.
"""
import sys

import wr21_takeover_bakeoff as B
import writer_v21_runtime as RT

B.O = RT

if __name__ == "__main__":
    sys.exit(B.main())
