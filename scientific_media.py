#!/usr/bin/env python3
"""scientific_media.py — high-fidelity scientific media adapters.

These sources are intentionally separate from generic stock:
- NASA Scientific Visualization Studio (SVS): real NASA data visualizations/movies.
- PubChem PUG REST: exact 2D/3D small-molecule structure images.

All functions are fail-soft. Network/provider trouble returns []/None so the
existing render stack can continue to Pexels/Wikimedia/AI/stat-card fallbacks.
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.parse
import urllib.request
import json

UA = "Content-Render/1.0 (+https://github.com/werriesjacob1-cmyk/Content-Render)"

_SVS_TRIGGER_RE = re.compile(
    r"\b("
    r"space|planet|moon|sun|solar|star|galaxy|nebula|black hole|supernova|"
    r"asteroid|comet|meteor|orbit|satellite|eclipse|aurora|magnetosphere|"
    r"atmosphere|climate|weather|storm|hurricane|tornado|lightning|cloud|"
    r"ocean|sea surface|current|temperature|carbon dioxide|co2|methane|"
    r"earth|volcano|earthquake|tectonic|ice sheet|glacier|wildfire|"
    r"ozone|aerosol|jet stream"
    r")\b", re.I)

_STOCK_NOISE_RE = re.compile(
    r"\b("
    r"4k|hd|vertical|portrait|cinematic|documentary|stock|footage|video|"
    r"close[- ]?up|macro|slow[- ]?motion|time[- ]?lapse|aerial|animation|"
    r"animated|visualization|simulation|background|dramatic|realistic"
    r")\b", re.I)

_CHEM_TRIGGER_RE = re.compile(
    r"\b("
    r"molecule|molecular|chemical|compound|structure|formula|acid|base|"
    r"alkaloid|hormone|neurotransmitter|vitamin|drug|medicine|element|"
    r"protein|enzyme"
    r")\b", re.I)

# Common small molecules that appear in science/body scripts but may not have a
# generic "molecule" token in the generated search query.
_COMMON_COMPOUNDS = (
    "water", "caffeine", "dopamine", "serotonin", "adrenaline", "epinephrine",
    "melatonin", "glucose", "fructose", "sucrose", "lactose", "ethanol",
    "methanol", "acetone", "aspirin", "ibuprofen", "acetaminophen", "paracetamol",
    "nicotine", "cortisol", "testosterone", "estrogen", "oestradiol", "estradiol",
    "oxytocin", "histamine", "cholesterol", "creatine", "urea", "ammonia",
    "hydrochloric acid", "sulfuric acid", "sulphuric acid", "nitric acid",
    "carbon dioxide", "methane", "oxygen", "ozone", "nitrogen", "hydrogen",
    "sodium chloride", "calcium carbonate", "atp", "adenosine triphosphate",
)

_CHEM_NOISE = {
    "molecule", "molecules", "molecular", "chemical", "chemicals", "compound",
    "compounds", "structure", "structures", "formula", "3d", "2d", "model",
    "models", "diagram", "animation", "animated", "close", "up", "macro",
    "microscopic", "inside", "human", "body", "blood", "brain", "cell", "cells",
    "stomach", "skin", "science", "medical", "medicine", "illustration",
}


def _http_json(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _http_bytes(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), (r.headers.get("Content-Type") or "")


def _clean_svs_query(query: str) -> str:
    q = _STOCK_NOISE_RE.sub(" ", query or "")
    q = re.sub(r"\s+", " ", q).strip(" -_,")
    return q[:120]


def svs_relevant(query: str) -> bool:
    """Conservative switch: only spend NASA-SVS requests on likely NASA science."""
    return bool(_SVS_TRIGGER_RE.search(query or ""))


def _media_from_item(item):
    if not isinstance(item, dict):
        return None
    for key in ("media", "instance"):
        m = item.get(key)
        if isinstance(m, dict) and m.get("media_type"):
            return m
    return None


def _page_movies(page):
    """Flatten Movie media from an SVS visualization page."""
    movies = []
    main = page.get("main_video")
    if isinstance(main, dict) and main.get("media_type") == "Movie":
        movies.append(main)
    for group in page.get("media_groups") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items") or []:
            m = _media_from_item(item)
            if isinstance(m, dict) and m.get("media_type") == "Movie":
                movies.append(m)
    # dedupe exact URLs
    seen, out = set(), []
    for m in movies:
        u = m.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(m)
    return out


def _best_svs_movie(page):
    """Pick a web-friendly MP4, preferring HD over giant 4K masters."""
    movies = [m for m in _page_movies(page)
              if str(m.get("url", "")).lower().split("?")[0].endswith(".mp4")]
    if not movies:
        return None

    def rank(m):
        w = int(m.get("width") or 0)
        h = int(m.get("height") or 0)
        px = int(m.get("pixels") or (w * h) or 0)
        # Prefer roughly 720p–1080p source files: enough for a 9:16 crop, much
        # cheaper than pulling a 4K/8K master into every CI render.
        in_hd = 1 if 1200 <= max(w, h) <= 2200 else 0
        too_small = 1 if max(w, h) and max(w, h) < 900 else 0
        filename = str(m.get("filename") or "").lower()
        webish = 1 if any(k in filename for k in ("1080", "1920", "hd", "web")) else 0
        return (in_hd, webish, -too_small, -abs(px - 1920 * 1080))

    return max(movies, key=rank)


def svs_candidates(query: str, used_ids=None, limit: int = 3, timeout: float = 8.0):
    """Return NASA SVS movie candidates in main.py's candidate shape.

    Search -> page API -> best practical MP4. IDs are namespaced strings so they
    cannot collide with numeric Pexels IDs in the shared footage history.
    """
    if not svs_relevant(query):
        return []
    used = set(used_ids or ())
    cleaned = _clean_svs_query(query)
    if not cleaned:
        return []

    out = []
    try:
        search_url = (
            "https://svs.gsfc.nasa.gov/api/search/?"
            + urllib.parse.urlencode({"search": cleaned, "limit": max(1, min(int(limit), 5))})
        )
        data = _http_json(search_url, timeout=timeout)
        for result in data.get("results") or []:
            if len(out) >= limit:
                break
            if not isinstance(result, dict):
                continue
            if str(result.get("result_type", "")).lower() != "visualization":
                continue
            page_id = result.get("id")
            if page_id is None:
                continue
            try:
                page = _http_json(f"https://svs.gsfc.nasa.gov/api/{page_id}/", timeout=timeout)
            except Exception:
                continue
            movie = _best_svs_movie(page)
            if not movie:
                continue
            media_id = movie.get("id") or page_id
            cid = f"svs:{media_id}"
            if cid in used:
                continue
            desc = " ".join(x for x in (
                str(page.get("title") or result.get("title") or ""),
                str(page.get("description") or result.get("description") or ""),
                str(movie.get("alt_text") or ""),
                " ".join(str(k) for k in (page.get("keywords") or [])),
            ) if x).strip()
            thumb = page.get("main_image") or {}
            out.append({
                "id": cid,
                "url": movie.get("url"),
                "desc": desc[:700],
                "source": "NASA SVS",
                "image": thumb.get("url") if isinstance(thumb, dict) else None,
                "scientific": True,
                "page_url": page.get("url") or result.get("url"),
            })
    except Exception:
        return []
    return out


def _normalize_chemical_text(query: str) -> str:
    q = (query or "").lower().replace("_", " ")
    q = re.sub(r"[^a-z0-9+\- ]+", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def chemical_name_candidates(query: str):
    """Return conservative PubChem name guesses, most-specific first."""
    q = _normalize_chemical_text(query)
    if not q:
        return []

    found = []
    # Exact common compounds are safest.
    for name in sorted(_COMMON_COMPOUNDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", q):
            found.append(name)

    # Named acids are usually directly resolvable (e.g. hydrochloric acid).
    for m in re.finditer(r"\b([a-z][a-z0-9+\-]*(?: [a-z][a-z0-9+\-]*){0,2} acid)\b", q):
        found.append(m.group(1))

    # Queries like "dopamine molecule" or "caffeine chemical structure".
    if _CHEM_TRIGGER_RE.search(q):
        toks = [t for t in q.split() if t not in _CHEM_NOISE]
        if toks:
            # Keep this short: PubChem names are usually concise, and passing
            # "dopamine synapse neuron" creates false matches/failure.
            found.append(" ".join(toks[:3]))

    deduped = []
    for x in found:
        x = re.sub(r"\s+", " ", x).strip()
        if x and x not in deduped and len(x) <= 64:
            deduped.append(x)
    return deduped[:4]


def pubchem_relevant(query: str) -> bool:
    q = _normalize_chemical_text(query)
    return bool(_CHEM_TRIGGER_RE.search(q) or any(
        re.search(rf"\b{re.escape(name)}\b", q) for name in _COMMON_COMPOUNDS
    ))


def pubchem_image(query: str, dest: str, timeout: float = 10.0):
    """Download an exact PubChem structure image. Returns resolved name or None.

    3D conformer is tried first because it reads more naturally in a motion video;
    2D structure is the authoritative fallback. No API key is required.
    """
    if not pubchem_relevant(query):
        return None
    for name in chemical_name_candidates(query):
        esc = urllib.parse.quote(name, safe="")
        urls = [
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{esc}/PNG"
            f"?record_type=3d&image_size=900x900",
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{esc}/PNG"
            f"?record_type=2d&image_size=900x900",
        ]
        for url in urls:
            try:
                data, ctype = _http_bytes(url, timeout=timeout)
                # PubChem should return PNG; validate the magic bytes because
                # maintenance/throttle responses can occasionally be HTML.
                if len(data) > 100 and data.startswith(b"\x89PNG\r\n\x1a\n"):
                    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(data)
                    return name
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
                continue
            except Exception:
                continue
    return None
