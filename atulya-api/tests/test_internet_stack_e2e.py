"""
E2E against the internet-search docker compose (SearXNG + Firecrawl).

Prerequisites:
  docker compose -f docker/docker-compose/internet-search/docker-compose.yaml up -d

If the stack is not reachable, tests are skipped (no failure in CI without the stack).

Run without xdist workers (project addopts use -n 8):
  cd atulya-api && uv run pytest tests/test_internet_stack_e2e.py -o addopts='--timeout 600 -v'
"""

from __future__ import annotations

import os

import httpx
import pytest

from atulya_api.cortex.internet_connectors import InternetConnectorConfig, InternetStackClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.internet_stack,
    pytest.mark.xdist_group("internet_stack"),
]


def _stack_reachable() -> bool:
    cfg = InternetConnectorConfig.from_env()
    try:
        with httpx.Client(follow_redirects=True, timeout=15.0) as c:
            s = c.get(f"{cfg.searxng_base_url}/")
            f = c.get(f"{cfg.firecrawl_base_url}/v0/health/liveness")
        return s.status_code < 500 and f.status_code == 200
    except (OSError, httpx.HTTPError):
        return False


@pytest.fixture(scope="module")
def require_internet_stack() -> None:
    if os.getenv("ATULYA_INTERNET_STACK_E2E") == "0":
        pytest.skip("ATULYA_INTERNET_STACK_E2E=0")
    if not _stack_reachable():
        pytest.skip(
            "Internet stack not reachable. Start: "
            "docker compose -f docker/docker-compose/internet-search/docker-compose.yaml up -d"
        )


@pytest.mark.asyncio
async def test_searxng_json_search_returns_results(require_internet_stack: None) -> None:
    cfg = InternetConnectorConfig.from_env()
    stack = InternetStackClient(cfg)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        data = await stack.searxng_search_json(client, "Python httpx library documentation")
    results = data.get("results") or []
    assert len(results) >= 1
    first = results[0]
    assert "url" in first and str(first["url"]).startswith("http")


@pytest.mark.asyncio
async def test_firecrawl_scrape_example_com(require_internet_stack: None) -> None:
    cfg = InternetConnectorConfig.from_env()
    stack = InternetStackClient(cfg)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        md = await stack.firecrawl_scrape_markdown(client, "https://example.com")
    assert "Example Domain" in md or "example" in md.lower()


@pytest.mark.asyncio
async def test_hard_research_pipeline_prefers_stable_targets(require_internet_stack: None) -> None:
    """Composite task: metasearch → ranked URLs → scrape with per-URL fallback."""
    cfg = InternetConnectorConfig.from_env()
    stack = InternetStackClient(cfg)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        report = await stack.research_search_then_scrape(
            client,
            "IANA example domain official description",
        )
    assert report.search_ok
    assert report.search_result_count >= 1
    assert report.scrape_ok
    assert report.chosen_url
    assert report.markdown_excerpt
    lowered = report.markdown_excerpt.lower()
    assert "example" in lowered or "domain" in lowered or "iana" in lowered
