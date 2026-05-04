"""
Resilient HTTP clients for SearXNG + Firecrawl (Atulya Cortex internet capability).

Designed for flaky networks, cold containers, and slow first scrapes: bounded retries
with exponential backoff on transient HTTP failures and transport errors.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_SEARXNG = "http://127.0.0.1:18080"
_DEFAULT_FIRECRAWL = "http://127.0.0.1:3002"
# Self-hosted Firecrawl with USE_DB_AUTHENTICATION=false accepts any UUID-shaped Bearer.
_DEFAULT_FIRECRAWL_API_KEY = "11111111-1111-4111-8111-111111111111"

_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


def _is_transient_exc(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)):
        return True
    return False


@dataclass(frozen=True)
class InternetConnectorConfig:
    searxng_base_url: str
    firecrawl_base_url: str
    firecrawl_api_key: str
    search_timeout: float = 60.0
    scrape_timeout: float = 180.0
    max_attempts: int = 4
    base_backoff_s: float = 0.6
    max_backoff_s: float = 8.0

    @classmethod
    def from_env(cls) -> InternetConnectorConfig:
        return cls(
            searxng_base_url=os.getenv(
                "ATULYA_API_CORTEX_SEARXNG_BASE_URL",
                _DEFAULT_SEARXNG,
            ).rstrip("/"),
            firecrawl_base_url=os.getenv(
                "ATULYA_API_CORTEX_FIRECRAWL_API_URL",
                _DEFAULT_FIRECRAWL,
            ).rstrip("/"),
            firecrawl_api_key=os.getenv(
                "ATULYA_API_CORTEX_FIRECRAWL_API_KEY",
                _DEFAULT_FIRECRAWL_API_KEY,
            ),
        )


@dataclass
class InternetResearchReport:
    """Outcome of a composite search → pick URL → scrape pipeline."""

    query: str
    search_ok: bool
    search_result_count: int = 0
    candidate_urls: list[str] = field(default_factory=list)
    chosen_url: str | None = None
    scrape_ok: bool = False
    markdown_excerpt: str | None = None
    errors: list[str] = field(default_factory=list)
    attempts: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return self.search_ok and self.scrape_ok and bool((self.markdown_excerpt or "").strip())


@dataclass
class InternetStackClient:
    """Async client with retries for SearXNG JSON search and Firecrawl v0 scrape."""

    config: InternetConnectorConfig

    def _backoff(self, attempt: int) -> float:
        raw = min(
            self.config.max_backoff_s,
            self.config.base_backoff_s * (2**attempt),
        )
        # small jitter avoids synchronized retries across workers
        return raw * (0.85 + 0.3 * random.random())

    async def _retry_http(
        self,
        label: str,
        do_request: Any,
    ) -> httpx.Response:
        last_exc: BaseException | None = None
        for attempt in range(self.config.max_attempts):
            try:
                resp = await do_request()
                if resp.status_code in _TRANSIENT_STATUSES or resp.status_code >= 520:
                    msg = f"{label} attempt {attempt + 1}/{self.config.max_attempts} HTTP {resp.status_code}"
                    logger.warning(msg)
                    last_exc = RuntimeError(msg)
                else:
                    return resp
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code in _TRANSIENT_STATUSES:
                    msg = f"{label} attempt {attempt + 1}/{self.config.max_attempts} HTTP {e.response.status_code}"
                    logger.warning(msg)
                    last_exc = e
                else:
                    raise
            except BaseException as e:
                if _is_transient_exc(e):
                    msg = f"{label} attempt {attempt + 1}/{self.config.max_attempts} transport: {e!r}"
                    logger.warning(msg)
                    last_exc = e
                else:
                    raise
            if attempt + 1 < self.config.max_attempts:
                await asyncio.sleep(self._backoff(attempt))
        assert last_exc is not None
        raise last_exc

    async def searxng_health(self, client: httpx.AsyncClient) -> bool:
        try:
            r = await client.get(
                f"{self.config.searxng_base_url}/",
                timeout=min(10.0, self.config.search_timeout),
            )
            return r.status_code < 500
        except httpx.HTTPError:
            return False

    async def firecrawl_liveness(self, client: httpx.AsyncClient) -> bool:
        try:
            r = await client.get(
                f"{self.config.firecrawl_base_url}/v0/health/liveness",
                timeout=min(15.0, self.config.scrape_timeout),
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def searxng_search_json(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        categories: str | None = None,
    ) -> dict[str, Any]:
        q = quote_plus(query)
        extra = f"&categories={quote_plus(categories)}" if categories else ""

        async def _do() -> httpx.Response:
            return await client.get(
                f"{self.config.searxng_base_url}/search?q={q}&format=json{extra}",
                timeout=self.config.search_timeout,
                headers={"Accept": "application/json"},
            )

        resp = await self._retry_http("searxng_search", _do)
        resp.raise_for_status()
        return resp.json()

    async def firecrawl_scrape_markdown(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.config.firecrawl_api_key}",
            "Content-Type": "application/json",
        }
        body = {"url": url, "formats": ["markdown"]}

        async def _do() -> httpx.Response:
            return await client.post(
                f"{self.config.firecrawl_base_url}/v0/scrape",
                json=body,
                headers=headers,
                timeout=self.config.scrape_timeout,
            )

        resp = await self._retry_http("firecrawl_scrape", _do)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"firecrawl scrape failed: {data!r}")
        inner = data.get("data") or {}
        md = inner.get("markdown") or inner.get("content") or ""
        if not isinstance(md, str):
            raise RuntimeError("firecrawl returned no markdown string")
        return md

    @staticmethod
    def _urls_from_searx_results(payload: dict[str, Any], *, limit: int = 12) -> list[str]:
        out: list[str] = []
        for row in payload.get("results") or []:
            u = row.get("url")
            if isinstance(u, str) and u.startswith(("http://", "https://")):
                out.append(u)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _looks_scrapeable(url: str) -> bool:
        if "example.com" in url and "iana.org" not in url:
            return False
        if re.match(r"^https?://(localhost|127\.0\.0\.1)([:/]|$)", url):
            return False
        return True

    async def research_search_then_scrape(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> InternetResearchReport:
        """
        Hard-path orchestration: metasearch → pick ranked HTTPS URLs → scrape with fallbacks.

        Tuned for “difficult” tasks where the first hit may be paywalled or blocked: try
        several SearXNG results before giving up.
        """
        report = InternetResearchReport(query=query, search_ok=False)
        try:
            payload = await self.searxng_search_json(client, query)
        except BaseException as e:
            report.errors.append(f"searxng_search:{e!r}")
            report.attempts.append("search_failed")
            return report

        report.search_ok = True
        urls = self._urls_from_searx_results(payload)
        report.search_result_count = len(payload.get("results") or [])
        report.candidate_urls = urls

        scrape_candidates = [u for u in urls if self._looks_scrapeable(u)]
        if not scrape_candidates:
            scrape_candidates = urls

        for idx, target in enumerate(scrape_candidates[:6]):
            report.attempts.append(f"scrape_try_{idx + 1}:{target}")
            try:
                md = await self.firecrawl_scrape_markdown(client, target)
                report.chosen_url = target
                report.scrape_ok = True
                report.markdown_excerpt = (md or "")[:4000]
                return report
            except BaseException as e:
                report.errors.append(f"scrape_fail:{target}:{e!r}")
                await asyncio.sleep(self._backoff(idx))

        report.attempts.append("scrape_exhausted_candidates")
        return report

    @staticmethod
    def truncate_for_tool(text: str, max_chars: int) -> tuple[str, bool]:
        """Collapse vertical whitespace and trim to a hard char cap (tool_result budget)."""

        t = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
        if len(t) <= max_chars:
            return t, False
        return t[: max_chars - 22].rstrip() + "\n…[truncated]", True

    async def tool_web_search_compact(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        max_hits: int = 5,
        title_max: int = 72,
        snippet_max: int = 140,
    ) -> dict[str, Any]:
        """SearXNG results as a dense digest for LLM tool channels (token-efficient)."""

        payload = await self.searxng_search_json(client, query.strip())
        rows = (payload.get("results") or [])[: max(1, min(int(max_hits), 12))]
        lines: list[str] = []
        for i, r in enumerate(rows, 1):
            title = str(r.get("title") or "").replace("\n", " ")[:title_max]
            url = str(r.get("url") or "")
            snip = str(r.get("content") or "").replace("\n", " ")[:snippet_max]
            if url:
                lines.append(f"{i}. {title} | {url}")
                if snip:
                    lines.append(f"   {snip}")
        digest = "\n".join(lines) if lines else "(no hits)"
        digest, truncated = self.truncate_for_tool(digest, 1100)
        return {
            "query": query.strip(),
            "n": len(rows),
            "digest": digest,
            "truncated": truncated,
        }

    async def tool_web_extract_compact(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        max_chars: int = 1200,
    ) -> dict[str, Any]:
        """Firecrawl markdown trimmed for tool_result / small-model context."""

        u = str(url).strip()
        if not u.startswith(("http://", "https://")):
            raise ValueError("web_extract: url must be http(s)")
        md = await self.firecrawl_scrape_markdown(client, u)
        body, truncated = self.truncate_for_tool(md, int(max_chars))
        return {"url": u, "markdown": body, "truncated": truncated}
