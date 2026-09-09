#!/usr/bin/env python3
"""One JSON boundary for every certification/proof evidence file.

The zero-provider factory proof died in CI with::

    TypeError: Object of type PosixPath is not JSON serializable

Patching the one offending field would have left the same landmine at the nine
other places that serialize evidence (proof report, repair execution, asset
lineage, visual bible, audio QA, scene timeline, targeted repair plan...). Any
of them can acquire a Path, an Enum or a dataclass at any time, and the failure
only shows up in a real render -- the most expensive place to discover it.

So the BOUNDARY is fixed, not the field:

- ``json_safe`` converts the value types evidence legitimately carries
  (Path -> str, Enum -> value, dataclass -> dict, Mapping/sequence recursed).
- Anything else raises ``UnserializableEvidence`` rather than being coerced.
  Silently ``str()``-ing an unknown object would write ``"<Foo object at
  0x7f...>"`` into an evidence file -- corrupt evidence that still looks like a
  successful run, which is strictly worse than a loud failure.
- Numbers are passed through untouched, including NaN/inf. Those carry real
  meaning in audio QA (an unmeasurable loudness), and rewriting them here would
  be altering scientific content to satisfy a serializer.
"""
from __future__ import annotations

import dataclasses
import enum
import json
from collections.abc import Mapping, Sequence, Set
from pathlib import Path, PurePath
from typing import Any


class UnserializableEvidence(TypeError):
    """Raised when evidence holds a value this boundary refuses to guess about."""


_PASSTHROUGH = (str, int, float, bool)


def json_safe(value: Any, _where: str = "$") -> Any:
    """Recursively convert evidence into JSON-safe primitives, or fail closed."""
    if value is None or isinstance(value, _PASSTHROUGH):
        return value
    if isinstance(value, (Path, PurePath)):
        return str(value)
    if isinstance(value, enum.Enum):
        return json_safe(value.value, f"{_where}(enum)")
    if isinstance(value, bytes):
        raise UnserializableEvidence(
            f"{_where}: raw bytes cannot be evidence -- store a path, hash or decoded text"
        )
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json_safe(dataclasses.asdict(value), f"{_where}(dataclass)")
    if isinstance(value, Mapping):
        return {str(k): json_safe(v, f"{_where}.{k}") for k, v in value.items()}
    if isinstance(value, (Set, frozenset, set)):
        items = [json_safe(v, f"{_where}[]") for v in value]
        # Sets have no inherent order; sort when possible so evidence files are
        # reproducible across runs and diffable.
        try:
            return sorted(items)
        except TypeError:
            return items
    if isinstance(value, Sequence):  # list/tuple; str already handled above
        return [json_safe(v, f"{_where}[{i}]") for i, v in enumerate(value)]
    raise UnserializableEvidence(
        f"{_where}: {type(value).__name__} is not valid evidence content; convert it "
        f"explicitly (a path, hash, id or plain value) rather than letting it be guessed"
    )


def dumps(payload: Any, **kwargs: Any) -> str:
    kwargs.setdefault("indent", 2)
    return json.dumps(json_safe(payload), **kwargs)


def write_json(path: str | Path, payload: Any, **kwargs: Any) -> Path:
    """Sanitize then write one evidence file, creating parent dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dumps(payload, **kwargs), encoding="utf-8")
    return p
