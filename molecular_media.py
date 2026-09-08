#!/usr/bin/env python3
"""Authentic molecular-media adapter for RCSB PDB.

This module gives Content Render a reality-first structure lane for molecular
and biochemical stories. It retrieves experimental PDB metadata and coordinate
files instead of inventing generic glowing molecules.

RCSB/wwPDB usage verified 2026-09-03:
- PDB archive data: CC0 1.0
- RCSB programmatic API core PDB data: CC0 1.0
- attribution to structure authors/RCSB is encouraged
- externally integrated annotations may carry separate licenses, so this module
  deliberately restricts its license claim to core PDB entry/coordinate data.

No production route is enabled by importing this module. Search results remain
candidates until the story/Visual Director selects and QA verifies them.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Mapping, Sequence

RCSB_DATA = "https://data.rcsb.org/rest/v1/core/entry"
RCSB_SEARCH = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_FILES = "https://files.rcsb.org/download"
RCSB_STRUCTURE = "https://www.rcsb.org/structure"
RCSB_3D = "https://www.rcsb.org/3d-view"
LICENSE_NAME = "CC0-1.0"
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
VERIFIED_ON = "2026-09-03"
PDB_ID_RE = re.compile(r"^[0-9][A-Za-z0-9]{3}$")


class MolecularMediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class PDBSearchHit:
    pdb_id: str
    score: float


@dataclass(frozen=True)
class PDBEntry:
    pdb_id: str
    title: str
    experimental_methods: tuple[str, ...]
    primary_citation_title: str
    primary_citation_authors: tuple[str, ...]
    primary_citation_year: int | None
    primary_citation_doi: str
    pdb_doi: str
    latest_revision_date: str
    structure_url: str
    view3d_url: str
    coordinate_url: str
    license_name: str = LICENSE_NAME
    license_url: str = LICENSE_URL
    public_domain: bool = True
    production_eligible: bool = False

    def attribution(self) -> str:
        authors = ", ".join(self.primary_citation_authors[:4])
        if len(self.primary_citation_authors) > 4:
            authors += " et al."
        base = f"RCSB PDB {self.pdb_id}"
        if authors: base += f"; {authors}"
        if self.primary_citation_year: base += f" ({self.primary_citation_year})"
        if self.primary_citation_doi: base += f"; DOI {self.primary_citation_doi}"
        return base

    def render_recipe(self) -> Mapping[str, Any]:
        """Provider-neutral recipe for a future Mol*/structure renderer."""
        return {
            "kind": "rcsb_pdb_structure",
            "pdb_id": self.pdb_id,
            "coordinate_url": self.coordinate_url,
            "structure_page": self.structure_url,
            "viewer": "molstar_preferred",
            "representation": "cartoon",
            "assembly": "1",
            "background": "transparent_or_dark",
            "labels": [],
            "license": {"name": self.license_name, "url": self.license_url},
            "attribution": self.attribution(),
            "vision_qa_required": True,
            "production_eligible": False,
        }


def normalize_pdb_id(value: str) -> str:
    pdb_id = str(value or "").strip().upper()
    if not PDB_ID_RE.fullmatch(pdb_id):
        raise ValueError(f"invalid current PDB ID {value!r}")
    return pdb_id


def _json_request(url: str, payload: Mapping[str, Any] | None = None, timeout: int = 30) -> Mapping[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Accept":"application/json","Content-Type":"application/json","User-Agent":"content-render/rcsb-media"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as exc:
        detail=""
        try: detail=exc.read().decode("utf-8","replace")[:500]
        except Exception: pass
        raise MolecularMediaError(f"RCSB HTTP {exc.code}: {detail}") from exc
    try:
        obj=json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MolecularMediaError("RCSB returned invalid JSON") from exc
    if not isinstance(obj,Mapping): raise MolecularMediaError("RCSB JSON was not an object")
    return obj


def search_rcsb(query: str, max_results: int = 5) -> tuple[PDBSearchHit, ...]:
    query=re.sub(r"\s+"," ",str(query or "")).strip()
    if not query: raise ValueError("RCSB search query required")
    if not (1 <= int(max_results) <= 20): raise ValueError("max_results must be 1..20")
    payload={
        "query":{"type":"terminal","service":"full_text","parameters":{"value":query}},
        "return_type":"entry",
        "request_options":{
            "results_content_type":["experimental"],
            "paginate":{"start":0,"rows":int(max_results)},
            "sort":[{"sort_by":"score","direction":"desc"}],
            "scoring_strategy":"combined",
        },
    }
    obj=_json_request(RCSB_SEARCH,payload)
    rows=obj.get("result_set")
    if not isinstance(rows,Sequence) or isinstance(rows,(str,bytes)): return ()
    out=[]
    for row in rows:
        if not isinstance(row,Mapping): continue
        try: pid=normalize_pdb_id(str(row.get("identifier") or "")); score=float(row.get("score") or 0)
        except (ValueError,TypeError): continue
        out.append(PDBSearchHit(pid,score))
    return tuple(out)


def parse_entry(payload: Mapping[str, Any], expected_id: str) -> PDBEntry:
    pdb_id=normalize_pdb_id(expected_id)
    entry=payload.get("entry") if isinstance(payload.get("entry"),Mapping) else {}
    actual=str(entry.get("id") or "").upper()
    if actual and actual != pdb_id: raise MolecularMediaError(f"entry ID mismatch: expected {pdb_id}, got {actual}")

    struct=payload.get("struct") if isinstance(payload.get("struct"),Mapping) else {}
    title=str(struct.get("title") or "").strip()

    citations=payload.get("citation") if isinstance(payload.get("citation"),Sequence) else []
    primary={}
    for c in citations:
        if isinstance(c,Mapping) and (str(c.get("rcsb_is_primary") or "").upper()=="Y" or str(c.get("id") or "").lower()=="primary"):
            primary=c; break
    if not title: title=str(primary.get("title") or "").strip()
    authors_raw=primary.get("rcsb_authors") if isinstance(primary,Mapping) else []
    authors=tuple(str(x).strip() for x in authors_raw if str(x).strip()) if isinstance(authors_raw,Sequence) and not isinstance(authors_raw,(str,bytes)) else ()
    year=None
    try:
        if primary.get("year") is not None: year=int(primary.get("year"))
    except (TypeError,ValueError): pass
    citation_doi=str(primary.get("pdbx_database_id_DOI") or "").strip()

    methods=[]
    exptl=payload.get("exptl")
    if isinstance(exptl,Sequence) and not isinstance(exptl,(str,bytes)):
        for row in exptl:
            if isinstance(row,Mapping):
                m=str(row.get("method") or "").strip()
                if m and m not in methods: methods.append(m)

    pdb_doi=""
    db2=payload.get("database_2")
    if isinstance(db2,Sequence) and not isinstance(db2,(str,bytes)):
        for row in db2:
            if isinstance(row,Mapping) and str(row.get("database_id") or "").upper()=="PDB":
                pdb_doi=str(row.get("pdbx_DOI") or "").strip(); break

    latest=""
    history=payload.get("pdbx_audit_revision_history")
    if isinstance(history,Sequence) and not isinstance(history,(str,bytes)):
        dates=[str(x.get("revision_date") or "") for x in history if isinstance(x,Mapping) and x.get("revision_date")]
        if dates: latest=max(dates)

    return PDBEntry(
        pdb_id=pdb_id,
        title=title or f"PDB structure {pdb_id}",
        experimental_methods=tuple(methods),
        primary_citation_title=str(primary.get("title") or "").strip(),
        primary_citation_authors=authors,
        primary_citation_year=year,
        primary_citation_doi=citation_doi,
        pdb_doi=pdb_doi,
        latest_revision_date=latest,
        structure_url=f"{RCSB_STRUCTURE}/{pdb_id}",
        view3d_url=f"{RCSB_3D}/{pdb_id}",
        coordinate_url=f"{RCSB_FILES}/{pdb_id}.cif",
    )


def fetch_entry(pdb_id: str) -> PDBEntry:
    pid=normalize_pdb_id(pdb_id)
    return parse_entry(_json_request(f"{RCSB_DATA}/{pid}"),pid)


def download_coordinates(entry: PDBEntry, dest: str, timeout: int = 60) -> str:
    req=urllib.request.Request(entry.coordinate_url,headers={"User-Agent":"content-render/rcsb-media"})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r: data=r.read()
    except urllib.error.HTTPError as exc:
        raise MolecularMediaError(f"coordinate download HTTP {exc.code}") from exc
    if len(data)<500: raise MolecularMediaError("coordinate file implausibly small")
    head=data[:4096].decode("utf-8","replace").lower()
    if f"data_{entry.pdb_id.lower()}" not in head: raise MolecularMediaError("coordinate file did not identify expected PDB entry")
    if "_atom_site." not in data.decode("utf-8","replace").lower(): raise MolecularMediaError("coordinate file contains no atom_site data")
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".",exist_ok=True)
    with open(dest,"wb") as f: f.write(data)
    return dest


def discover_candidates(subject: str, max_results: int = 5) -> tuple[PDBEntry, ...]:
    """Return authentic experimental candidates; never auto-promote one."""
    hits=search_rcsb(subject,max_results=max_results)
    out=[]
    for hit in hits:
        try: out.append(fetch_entry(hit.pdb_id))
        except MolecularMediaError: continue
    return tuple(out)
