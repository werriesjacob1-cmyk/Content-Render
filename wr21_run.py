#!/usr/bin/env python3
"""Entry point for the canonical Writer V2.1 takeover bakeoff.

The canonical ``writer_v2.assemble_manifest_v2`` contract now owns spoken
hook + beats + payoff assembly directly, so no runtime monkeypatch layer is
required. No render or publishing code is called.
"""
import sys

import wr21_takeover_bakeoff as B
import writer_v21_orchestrator as O

B.O = O

if __name__ == "__main__":
    sys.exit(B.main())
