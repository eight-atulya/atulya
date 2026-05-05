"""OpenAI-style tool schemas for the internet research agent (SearXNG + Firecrawl)."""

from __future__ import annotations

TOOL_WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web via SearXNG metasearch. Always call this first with a focused query. "
            "Do not fetch search-engine HTML pages directly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (keywords, not a full sentence required).",
                },
                "max_hits": {
                    "type": "integer",
                    "description": "Max results to include in the digest (1–12).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}

TOOL_WEB_EXTRACT = {
    "type": "function",
    "function": {
        "name": "web_extract",
        "description": (
            "Fetch and extract readable markdown from a single http(s) URL using the crawler. "
            "Use only when the search digest is insufficient; prefer one high-quality URL."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full http(s) URL to scrape."},
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters of markdown to return (400–4000).",
                    "default": 1200,
                },
            },
            "required": ["url"],
        },
    },
}

TOOL_DONE_INTERNET = {
    "type": "function",
    "function": {
        "name": "done",
        "description": (
            "Finish with a concise markdown answer citing what you found on the web. "
            "Do not claim bank memory facts—only live web evidence from tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "Final markdown answer for the user.",
                },
                "source_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs you relied on (from web_search or web_extract).",
                },
            },
            "required": ["answer"],
        },
    },
}


def get_internet_research_tools() -> list[dict]:
    return [TOOL_WEB_SEARCH, TOOL_WEB_EXTRACT, TOOL_DONE_INTERNET]
