"""Grounded research adapters for Content Render.

This module is deliberately provider-neutral and fail-closed.  It converts
retrieval output into evidence objects that downstream writers can cite
mechanically.  Citation-looking prose is not enough: source URLs and supporting
excerpts/tool evidence must exist in the provider response.

No provider is enabled automatically by importing this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
import re
from typing import Any, Iterable, Mapping, Sequence
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse


YOU_ANSWER_URL = "https://api.you.com/v1/answer"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_TIMEOUT_S = 30


@dataclass(frozen=True)
class EvidenceSource:
    source_id: str
    url: str
    title: str = ""
    excerpts: tuple[str, ...] = ()
    published_at: str = ""
    provider: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def is_verifiable(self) -> bool:
        try:
            parsed = urlparse(self.url)
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and bool(self.excerpts)
        except Exception:
            return False


@dataclass(frozen=True)
class GroundedClaim:
    claim_id: str
    text: str
    source_ids: tuple[str, ...]
    provider: str
    confidence: str = "provider-grounded"

    def is_load_bearing(self, sources: Mapping[str, EvidenceSource]) -> bool:
        return bool(self.text.strip() and self.source_ids and all(
            sid in sources and sources[sid].is_verifiable() for sid in self.source_ids
        ))


@dataclass(frozen=True)
class ResearchBundle:
    provider: str
    query: str
    answer: str
    claims: tuple[GroundedClaim, ...]
    sources: tuple[EvidenceSource, ...]
    grounded: bool
    grounding_reason: str
    raw_tool_evidence_present: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def source_map(self) -> dict[str, EvidenceSource]:
        return {s.source_id: s for s in self.sources}

    def load_bearing_claims(self) -> tuple[GroundedClaim, ...]:
        smap = self.source_map()
        if not self.grounded:
            return ()
        return tuple(c for c in self.claims if c.is_load_bearing(smap))


class ResearchError(RuntimeError):
    pass


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(_norm(p).lower() for p in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def _json_request(url: str, payload: Mapping[str, Any], headers: Mapping[str, str], timeout_s: int) -> Mapping[str, Any]:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **dict(headers)},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - fixed HTTPS provider URLs
            raw = resp.read()
            if not raw:
                raise ResearchError(f"{url}: empty response")
            obj = json.loads(raw.decode("utf-8"))
            if not isinstance(obj, Mapping):
                raise ResearchError(f"{url}: response was not a JSON object")
            return obj
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        raise ResearchError(f"{url}: HTTP {e.code}: {body}") from e
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        raise ResearchError(f"{url}: {type(e).__name__}: {e}") from e


_CITE = re.compile(r"\[\[([0-9,\s]+)\]\]")


def _citation_indexes(marker: str) -> tuple[int, ...]:
    out: list[int] = []
    for piece in marker.split(","):
        piece = piece.strip()
        if piece.isdigit():
            idx = int(piece)
            if idx > 0 and idx not in out:
                out.append(idx)
    return tuple(out)


def _extract_you_sources(payload: Mapping[str, Any]) -> tuple[EvidenceSource, ...]:
    citations = payload.get("citations")
    if not isinstance(citations, Sequence) or isinstance(citations, (str, bytes)):
        return ()

    web_meta: dict[str, Mapping[str, Any]] = {}
    results = payload.get("results")
    if isinstance(results, Mapping):
        web = results.get("web")
        if isinstance(web, Sequence) and not isinstance(web, (str, bytes)):
            for row in web:
                if isinstance(row, Mapping):
                    url = str(row.get("url") or "").strip()
                    if url:
                        web_meta[url] = row

    out: list[EvidenceSource] = []
    for index, row in enumerate(citations, 1):
        # Preserve provider citation positions exactly.  If an entry is
        # malformed we keep an unverifiable placeholder instead of dropping it;
        # otherwise [[3]] could accidentally become the original citation #4.
        if not isinstance(row, Mapping):
            out.append(EvidenceSource(
                source_id=f"src_invalid_{index}",
                url="",
                provider="you_answer",
                metadata={"citation_index": index, "malformed": True},
            ))
            continue
        url = str(row.get("source") or "").strip()
        excerpts_raw = row.get("excerpts")
        excerpts: tuple[str, ...] = ()
        if isinstance(excerpts_raw, Sequence) and not isinstance(excerpts_raw, (str, bytes)):
            excerpts = tuple(_norm(str(x)) for x in excerpts_raw if _norm(str(x)))
        meta = web_meta.get(url, {})
        title = str(meta.get("title") or "").strip()
        published = str(meta.get("page_age") or "").strip()
        sid = _stable_id("src", url) if url else f"src_invalid_{index}"
        out.append(EvidenceSource(
            source_id=sid,
            url=url,
            title=title,
            excerpts=excerpts,
            published_at=published,
            provider="you_answer",
            metadata={
                "description": meta.get("description", "") if meta else "",
                "citation_index": index,
            },
        ))
    return tuple(out)


def _extract_you_claims(answer: str, sources: Sequence[EvidenceSource]) -> tuple[GroundedClaim, ...]:
    """Extract only text spans that carry explicit You citation markers.

    The parser intentionally does not promote uncited prose into evidence.
    """

    if not answer or not sources:
        return ()
    out: list[GroundedClaim] = []
    cursor = 0
    for match in _CITE.finditer(answer):
        prefix = answer[cursor:match.start()]
        # A provider may group multiple sentences under one marker. Keep the
        # complete local block, but strip markdown headings/bullets.
        text = _norm(re.sub(r"(?m)^\s*(?:#{1,6}|[-*])\s*", "", prefix))
        idxs = _citation_indexes(match.group(1))
        source_ids = tuple(sources[i - 1].source_id for i in idxs if 1 <= i <= len(sources))
        if text and source_ids:
            cid = _stable_id("claim", text, *source_ids)
            out.append(GroundedClaim(cid, text, source_ids, "you_answer"))
        cursor = match.end()
    return tuple(out)


def parse_you_answer(payload: Mapping[str, Any], query: str) -> ResearchBundle:
    answer = str(payload.get("answer") or "")
    sources = _extract_you_sources(payload)
    claims = _extract_you_claims(answer, sources)
    smap = {s.source_id: s for s in sources}
    valid = tuple(c for c in claims if c.is_load_bearing(smap))
    grounded = bool(valid)
    reason = (
        f"{len(valid)} cited claim block(s) backed by verbatim source excerpts"
        if grounded else
        "no claim had both an inline citation and verifiable supporting excerpts"
    )
    return ResearchBundle(
        provider="you_answer",
        query=query,
        answer=answer,
        claims=valid,
        sources=sources,
        grounded=grounded,
        grounding_reason=reason,
        raw_tool_evidence_present=bool(sources),
        metadata={"citation_count": len(sources)},
    )


def _walk_urls(obj: Any) -> Iterable[tuple[str, Mapping[str, Any]]]:
    """Conservatively surface HTTP(S) URLs found inside executed_tools."""

    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if isinstance(value, str) and key.lower() in {"url", "source", "link"}:
                u = value.strip()
                parsed = urlparse(u)
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    yield u, obj
            yield from _walk_urls(value)
    elif isinstance(obj, Sequence) and not isinstance(obj, (str, bytes)):
        for value in obj:
            yield from _walk_urls(value)


def _extract_compound_tool_sources(executed_tools: Any) -> tuple[EvidenceSource, ...]:
    if not isinstance(executed_tools, Sequence) or isinstance(executed_tools, (str, bytes)) or not executed_tools:
        return ()
    by_url: dict[str, EvidenceSource] = {}
    for url, container in _walk_urls(executed_tools):
        excerpts: list[str] = []
        for key in ("content", "snippet", "text", "result", "description"):
            value = container.get(key) if isinstance(container, Mapping) else None
            if isinstance(value, str) and _norm(value):
                excerpts.append(_norm(value)[:4000])
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                excerpts.extend(_norm(str(x))[:4000] for x in value if _norm(str(x)))
        # Executed tool existence alone proves a tool ran; a load-bearing source
        # still needs supporting text so that downstream validators can inspect
        # what the source actually said.
        excerpts = list(dict.fromkeys(excerpts))
        if not excerpts:
            continue
        sid = _stable_id("src", url)
        title = str(container.get("title") or "") if isinstance(container, Mapping) else ""
        by_url[url] = EvidenceSource(
            source_id=sid,
            url=url,
            title=_norm(title),
            excerpts=tuple(excerpts),
            provider="groq_compound_mini",
        )
    return tuple(by_url.values())


def parse_compound_response(payload: Mapping[str, Any], query: str) -> ResearchBundle:
    choices = payload.get("choices")
    message: Mapping[str, Any] = {}
    if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes)) and choices:
        first = choices[0]
        if isinstance(first, Mapping) and isinstance(first.get("message"), Mapping):
            message = first["message"]

    answer = str(message.get("content") or "")
    executed = message.get("executed_tools")
    tool_present = isinstance(executed, Sequence) and not isinstance(executed, (str, bytes)) and bool(executed)
    sources = _extract_compound_tool_sources(executed)

    # We deliberately do not infer sentence->source attribution from model prose.
    # Compound becomes "grounded enough for review" only when executed_tools has
    # inspectable sources.  It emits no load-bearing claims until a future parser
    # can bind exact answer spans to those sources mechanically.
    grounded = bool(tool_present and sources)
    reason = (
        "executed_tools present with inspectable source URLs/excerpts; answer retained for review but claims are not auto-promoted"
        if grounded else
        "missing mechanically inspectable executed_tools source evidence"
    )
    return ResearchBundle(
        provider="groq_compound_mini",
        query=query,
        answer=answer,
        claims=(),
        sources=sources,
        grounded=grounded,
        grounding_reason=reason,
        raw_tool_evidence_present=tool_present,
        metadata={"executed_tool_count": len(executed) if tool_present else 0},
    )


class YouAnswerProvider:
    name = "you_answer"

    def __init__(self, api_key: str | None = None, timeout_s: int = DEFAULT_TIMEOUT_S):
        self.api_key = api_key if api_key is not None else os.getenv("YOU_API_KEY", "")
        self.timeout_s = int(timeout_s)

    def available(self) -> bool:
        return bool(self.api_key)

    def research(
        self,
        query: str,
        *,
        freshness: str = "",
        include_domains: Sequence[str] = (),
        boost_domains: Sequence[str] = (),
        country: str = "US",
        language: str = "EN",
    ) -> ResearchBundle:
        query = _norm(query)
        if not query:
            raise ValueError("query is required")
        if len(query) > 400:
            raise ValueError("You Answer API query must be <= 400 characters")
        if include_domains and boost_domains:
            raise ValueError("include_domains and boost_domains cannot be combined")
        if not self.api_key:
            raise ResearchError("YOU_API_KEY is not configured")

        payload: dict[str, Any] = {
            "query": query,
            "country": country,
            "language": language,
            "safesearch": "strict",
        }
        if freshness:
            payload["freshness"] = freshness
        if include_domains:
            payload["include_domains"] = list(dict.fromkeys(include_domains))
        elif boost_domains:
            payload["boost_domains"] = list(dict.fromkeys(boost_domains))

        raw = _json_request(
            YOU_ANSWER_URL,
            payload,
            {"X-API-Key": self.api_key},
            self.timeout_s,
        )
        return parse_you_answer(raw, query)


class GroqCompoundMiniProvider:
    name = "groq_compound_mini"

    def __init__(self, api_key: str | None = None, timeout_s: int = DEFAULT_TIMEOUT_S):
        self.api_key = api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")
        self.timeout_s = int(timeout_s)

    def available(self) -> bool:
        return bool(self.api_key)

    def research(self, query: str) -> ResearchBundle:
        query = _norm(query)
        if not query:
            raise ValueError("query is required")
        if not self.api_key:
            raise ResearchError("GROQ_API_KEY is not configured")

        prompt = (
            "Research the scientific question below using web search when needed. "
            "Prefer primary scientific, government, university, or major reference sources. "
            "Do not invent citations. Keep the answer compact and factual.\n\n"
            f"QUESTION: {query}"
        )
        raw = _json_request(
            GROQ_CHAT_URL,
            {
                "model": "groq/compound-mini",
                "messages": [{"role": "user", "content": prompt}],
                "citation_options": "enabled",
                "temperature": 0.1,
            },
            {"Authorization": f"Bearer {self.api_key}"},
            self.timeout_s,
        )
        return parse_compound_response(raw, query)


TRUSTED_SCIENCE_DOMAINS: tuple[str, ...] = (
    "nasa.gov",
    "noaa.gov",
    "usgs.gov",
    "nih.gov",
    "ncbi.nlm.nih.gov",
    "cdc.gov",
    "nist.gov",
    "nsf.gov",
    "si.edu",
    "pdb.org",
    "rcsb.org",
    "nature.com",
    "science.org",
    "pnas.org",
)


def research_with_fallback(
    query: str,
    providers: Sequence[Any],
) -> ResearchBundle | None:
    """Return first mechanically grounded bundle; never silently downgrade."""

    errors: list[str] = []
    for provider in providers:
        if hasattr(provider, "available") and not provider.available():
            errors.append(f"{getattr(provider, 'name', type(provider).__name__)} unavailable")
            continue
        try:
            result = provider.research(query)
        except Exception as e:  # provider boundary: fail-soft, recorded
            errors.append(f"{getattr(provider, 'name', type(provider).__name__)}: {type(e).__name__}: {e}")
            continue
        if result.grounded:
            return result
        errors.append(f"{result.provider}: {result.grounding_reason}")
    return None
