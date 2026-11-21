"""Bounded, rights-checked footage discovery for the legacy selector."""
from html import unescape
import os
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "ContentRender/1.0 (https://github.com/werriesjacob1-cmyk/Content-Render)"
LICENSE_URI = re.compile(
    r"https?://creativecommons\.org/(?:publicdomain/(?:zero|mark)/1\.0|licenses/by/(?:2\.0|2\.5|3\.0|4\.0))/?",
    re.IGNORECASE,
)


def _text(value):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).split())


def commons_rows(payload, used_ids=(), max_bytes=45 * 1024 * 1024):
    if "error" in payload:
        code = payload["error"].get("code", "unknown")
        raise ValueError("Commons API " + (code if code in {"maxlag", "ratelimited"} else "error"))
    pages = payload.get("query", {}).get("pages", {})
    for page in sorted(pages.values(), key=lambda row: row.get("index", 0)):
        cid = page.get("pageid")
        info = (page.get("imageinfo") or [{}])[0]
        metadata = info.get("extmetadata") or {}

        def field(name):
            return (metadata.get(name) or {}).get("value", "")

        url, source_url = info.get("url", ""), info.get("descriptionurl", "")
        license_url = str(field("LicenseUrl")).strip()
        short_name = str(field("LicenseShortName")).strip().casefold()
        size = info.get("size")
        if (not cid or cid in used_ids or not isinstance(size, int) or not 0 < size <= max_bytes
                or not info.get("mime", "").startswith(("video/", "application/ogg"))
                or urlsplit(url).netloc != "upload.wikimedia.org"
                or urlsplit(source_url).netloc != "commons.wikimedia.org"
                or not url.startswith("https://") or not source_url.startswith("https://")
                or not LICENSE_URI.fullmatch(license_url)
                or re.search(r"\b(?:nc|nd|sa|editorial|noncommercial)\b", short_name)
                or field("Restrictions")):
            continue
        attribution = _text(field("Attribution") or field("Artist"))
        if "/licenses/by/" in license_url.lower() and not attribution:
            continue
        yield {
            "id": cid, "url": url, "source": "Wikimedia", "kind": "video",
            "source_url": source_url, "license": license_url,
            "attribution": attribution, "duration": info.get("duration"),
            "width": info.get("width"), "height": info.get("height"),
            "image": info.get("thumburl"),
            "desc": _text(page.get("title", "").removeprefix("File:"))[:200],
        }


class FootageSources:
    def __init__(self, get_json, log=print):
        self.get_json = get_json
        self.log = log
        self.disabled = set()

    def search(self, name, query, lookup, *, enabled_by_default=True):
        default = "1" if enabled_by_default else "0"
        if name in self.disabled or os.getenv(f"FOOTAGE_{name.upper()}_ENABLED", default) == "0":
            return []
        try:
            return list(lookup(query))
        except HTTPError as exc:
            reason = f"HTTP {exc.code}" + (" (rate limit)" if exc.code == 429 else "")
        except (TimeoutError, ValueError, OSError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("Commons API ") else type(exc).__name__
        except Exception as exc:
            reason = type(exc).__name__
        self.disabled.add(name)
        self.log(f"  [footage] {name}: {reason}; circuit open for this render")
        return []

    def commons(self, query, used_ids=(), max_bytes=45 * 1024 * 1024):
        params = {
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"{query.strip()[:100]} filetype:video", "gsrnamespace": 6,
            "gsrlimit": 5, "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": 320, "maxlag": 5,
        }
        data = self.get_json(f"{COMMONS_API}?{urlencode(params)}", {"User-Agent": USER_AGENT}, timeout=5)
        return list(commons_rows(data, used_ids, max_bytes))

    def congress(self, query, used_ids=()):
        root = "https://www.loc.gov"
        params = urlencode({"q": query[:100], "fo": "json", "c": 3})
        headers = {"User-Agent": USER_AGENT}
        search = self.get_json(f"{root}/film-and-videos/?{params}", headers, timeout=4)
        for result in search["results"]:
            item_url = str(result.get("id", "")).replace("http://", "https://", 1)
            if not re.fullmatch(r"https://www\.loc\.gov/item/[\w.-]+/?", item_url):
                continue
            candidate = self.get_json(item_url.rstrip("/") + "/?fo=json", headers, timeout=3)
            row = congress_row(candidate, item_url)
            if row and row["id"] not in used_ids:
                yield row


def congress_row(payload, item_url):
    item = payload.get("item") or {}
    rights = item.get("rights_advisory") or []
    if isinstance(rights, str):
        rights = [rights]
    # A collection-wide free-reuse banner or "no known restrictions" is insufficient.
    if not rights or any(_text(right).lower().rstrip(".") not in {
        "public domain", "this work is in the public domain",
        "https://creativecommons.org/publicdomain/mark/1.0/",
    } for right in rights):
        return None
    for resource in payload.get("resources") or []:
        for section in resource.get("files") or []:
            for file in section:
                url = file.get("url") or ""
                host = urlsplit(url).hostname or ""
                if (file.get("mimetype") != "video/mp4" or not url.startswith("https://")
                        or not host.endswith(".loc.gov")):
                    continue
                size = str(file.get("size") or "")
                if not size.isdecimal() or not 0 < int(size) <= 45 * 1024 * 1024:
                    continue
                return {
                    "id": f"loc:{item_url.rstrip('/').rsplit('/', 1)[-1]}",
                    "url": url, "kind": "video", "source": "Library of Congress",
                    "license": "Public Domain", "source_url": item_url,
                    "attribution": "Library of Congress" + (
                        f" — {_text(item['title'])}" if item.get("title") else ""),
                    "desc": _text(item.get("title")), "duration": file.get("duration"),
                    "width": file.get("width"), "height": file.get("height"),
                }
    return None


def rcsb_still(query):
    from molecular_media import fetch_entry

    match = re.search(r"\bPDB\s+(?:ID\s+)?([0-9][A-Za-z0-9]{3})\b", query, re.I)
    if not match:
        return []
    entry = fetch_entry(match[1])
    pid = entry.pdb_id.lower()
    return [{
        "id": f"pdb:{pid}", "source": "RCSB PDB", "kind": "image",
        "url": f"https://cdn.rcsb.org/images/structures/{pid[1:3]}/{pid}/{pid}_assembly-1.jpeg",
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution": ", ".join((*entry.primary_citation_authors, "RCSB PDB")),
        "source_url": entry.structure_url, "desc": entry.title,
        "duration": None, "width": None, "height": None,
    }]


def asset_record(candidate):
    return {key: candidate.get(key) for key in ("id", "source_url", "license", "attribution")}
