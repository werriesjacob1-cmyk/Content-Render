#!/usr/bin/env python3
"""Manual API audit. The relevance score is title-token overlap, never a vision score."""
import argparse
import json
from pathlib import Path
from statistics import median
import sys
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from footage_sources import FootageSources
from scientific_media import svs_candidates


def fixtures():
    root = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "legacy_controls"
    for path in sorted(root.glob("science_*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        yield from (scene["search_query"] for scene in manifest["scenes"])
    yield from ("chess game tree branching", "ancient Roman harbor excavation",
                "deep sea hydrothermal vent", "microscopic tardigrade")


def run_source(name, lookup, queries):
    hits = licensed = candidates = errors = 0
    relevance = []
    for query in queries:
        try:
            rows = list(lookup(query))
        except HTTPError as exc:
            errors += 1
            print(f"{name}: HTTP {exc.code}; stopping this source", file=sys.stderr)
            break
        except (OSError, ValueError, KeyError) as exc:
            errors += 1
            print(f"{name}: {type(exc).__name__}; stopping this source", file=sys.stderr)
            break
        words = main._relevance_words(query)
        scores = []
        for row in rows:
            candidates += 1
            if row.get("license") and row.get("source_url"):
                licensed += 1
            if words:
                scores.append(len(words & main._relevance_words(row.get("desc", ""))) / len(words))
        if scores:
            hits += 1
            relevance.append(max(scores))
    return {
        "source": name, "requested_queries": len(queries), "hits": hits, "errors": errors,
        "hit_rate": hits / len(queries) if not errors else None,
        "median_best_title_overlap": median(relevance) if relevance else None,
        "candidate_count": candidates,
        "license_pass_rate_of_returned_candidates": licensed / candidates if candidates else None,
    }


def cli():
    sources = FootageSources(main._http_json)
    lookups = {
        "commons": sources.commons, "congress": sources.congress,
        "svs": lambda query: svs_candidates(query, limit=2, timeout=4, strict_rights=True),
        "pexels": main._pexels_candidates,
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=lookups, action="append")
    parser.add_argument("--limit", type=int, help="Use only the first N queries for a smoke test.")
    args = parser.parse_args()
    queries = list(dict.fromkeys(fixtures()))[:args.limit]
    if not queries:
        parser.error("no queries selected")
    names = args.source or ["commons", "congress", "svs"]
    if "pexels" in names and not main.PEXELS_KEY:
        parser.error("Pexels evaluation requires an existing Pexels key")
    print(json.dumps([run_source(name, lookups[name], queries) for name in names], indent=2))


if __name__ == "__main__":
    cli()
