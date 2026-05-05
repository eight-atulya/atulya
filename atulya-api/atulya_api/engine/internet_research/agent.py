"""Agentic loop for live-web research (mirrors reflect agent tool-calling pattern)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, Field

from atulya_api.cortex.internet_connectors import InternetStackClient
from atulya_api.engine.reflect.agent import (
    _clean_done_answer,
    _is_done_tool,
    _normalize_tool_name,
    _tool_call_to_dict,
)
from atulya_api.engine.reflect.models import LLMCall, TokenUsageSummary, ToolCall

from .tools_schema import get_internet_research_tools

if TYPE_CHECKING:
    from atulya_api.engine.llm_wrapper import LLMProvider

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 8

SYSTEM_PROMPT = """You answer using the live public web only. The memory bank is not available and is not queried.
Rules:
- Start with web_search unless you already have tool results in the conversation.
- Use web_extract for at most one URL when you need page detail beyond the search digest.
- Finish with done({answer, source_urls}) when you can answer; keep the answer factual and cite URLs you used.
- Never invent URLs; only use URLs returned by web_search or passed to web_extract.
"""


_LEAKED_CHANNEL_TOKEN = re.compile(r"<\|channel\>[^ \n]*|<channel\|>|<\|[^|]+\|>")


def _clean_internet_text(text: str) -> str:
    cleaned = _clean_done_answer(text or "")
    cleaned = _LEAKED_CHANNEL_TOKEN.sub("", cleaned).strip()
    return cleaned


class InternetResearchAgentResult(BaseModel):
    text: str
    source_urls: list[str] = Field(default_factory=list)
    iterations: int = 0
    tools_called: int = 0
    tool_trace: list[ToolCall] = Field(default_factory=list)
    llm_trace: list[LLMCall] = Field(default_factory=list)
    usage: TokenUsageSummary = Field(default_factory=TokenUsageSummary)


def _output_has_evidence(tool_name: str, output: dict[str, Any]) -> bool:
    name = _normalize_tool_name(tool_name)
    if not isinstance(output, dict) or output.get("error"):
        return False
    if name == "web_search":
        n = int(output.get("n") or 0)
        digest = str(output.get("digest") or "")
        return n > 0 and "(no hits)" not in digest
    if name == "web_extract":
        return bool(str(output.get("markdown") or "").strip())
    return False


async def _exec_internet_tool(
    stack: InternetStackClient,
    http: httpx.AsyncClient,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    name = _normalize_tool_name(tool_name)
    if name == "web_search":
        q = args.get("query")
        if not q or not str(q).strip():
            return {"error": "web_search requires a non-empty query"}
        max_hits = max(1, min(int(args.get("max_hits") or 5), 12))
        try:
            return await stack.tool_web_search_compact(http, str(q), max_hits=max_hits)
        except BaseException as e:
            logger.warning("web_search failed: %s", e)
            return {"error": str(e)}
    if name == "web_extract":
        url = args.get("url")
        if not url:
            return {"error": "web_extract requires url"}
        max_chars = max(400, min(int(args.get("max_chars") or 1200), 4000))
        try:
            return await stack.tool_web_extract_compact(http, str(url), max_chars=max_chars)
        except BaseException as e:
            logger.warning("web_extract failed: %s", e)
            return {"error": str(e)}
    return {"error": f"Unknown tool: {tool_name}"}


async def run_internet_research_agent(
    llm_config: "LLMProvider",
    *,
    query: str,
    stack: InternetStackClient,
    http_client: httpx.AsyncClient,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_completion_tokens: int | None = None,
) -> InternetResearchAgentResult:
    """Run web_search / web_extract / done loop. Does not read or write the memory graph."""
    run_id = f"inet-{int(time.time() * 1000) % 100000}"
    tools = get_internet_research_tools()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query.strip()},
    ]
    tool_trace: list[ToolCall] = []
    llm_trace: list[LLMCall] = []
    total_input = 0
    total_output = 0
    total_tools = 0
    has_evidence = False

    def _usage() -> TokenUsageSummary:
        return TokenUsageSummary(
            input_tokens=total_input,
            output_tokens=total_output,
            total_tokens=total_input + total_output,
        )

    for iteration in range(max_iterations):
        llm_start = time.time()
        iter_tool_choice: str | dict[str, Any] = (
            {"type": "function", "function": {"name": "web_search"}}
            if iteration == 0
            else "auto"
        )
        try:
            result = await llm_config.call_with_tools(
                messages=messages,
                tools=tools,
                scope="internet_research",
                tool_choice=iter_tool_choice,
                max_completion_tokens=max_completion_tokens,
            )
        except Exception as e:
            logger.warning("[%s] LLM error iter %s: %s", run_id, iteration + 1, e)
            llm_trace.append(
                LLMCall(scope=f"internet_{iteration + 1}_err", duration_ms=int((time.time() - llm_start) * 1000))
            )
            return InternetResearchAgentResult(
                text=f"Internet research failed: {e}",
                iterations=iteration + 1,
                tools_called=total_tools,
                tool_trace=tool_trace,
                llm_trace=llm_trace,
                usage=_usage(),
            )

        llm_duration = int((time.time() - llm_start) * 1000)
        total_input += result.input_tokens
        total_output += result.output_tokens
        llm_trace.append(
            LLMCall(
                scope=f"internet_{iteration + 1}",
                duration_ms=llm_duration,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        )

        if not result.tool_calls:
            text = (result.content or "").strip()
            if text:
                text = _clean_internet_text(text)
                return InternetResearchAgentResult(
                    text=text,
                    iterations=iteration + 1,
                    tools_called=total_tools,
                    tool_trace=tool_trace,
                    llm_trace=llm_trace,
                    usage=_usage(),
                )
            return InternetResearchAgentResult(
                text="No tool calls and empty model output.",
                iterations=iteration + 1,
                tools_called=total_tools,
                tool_trace=tool_trace,
                llm_trace=llm_trace,
                usage=_usage(),
            )

        done_call = next((tc for tc in result.tool_calls if _is_done_tool(tc.name)), None)
        if done_call:
            if not has_evidence and iteration < max_iterations - 1:
                messages.append({"role": "assistant", "tool_calls": [_tool_call_to_dict(done_call)]})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": done_call.id,
                        "name": done_call.name,
                        "content": json.dumps(
                            {
                                "error": "Call web_search first and use its results before done().",
                            }
                        ),
                    }
                )
                continue

            raw = str(done_call.arguments.get("answer") or "").strip()
            answer = _clean_done_answer(raw) if raw else "No answer provided."
            urls = done_call.arguments.get("source_urls") or []
            source_urls = [str(u) for u in urls if isinstance(u, str) and u.startswith("http")]
            return InternetResearchAgentResult(
                text=answer,
                source_urls=source_urls,
                iterations=iteration + 1,
                tools_called=total_tools,
                tool_trace=tool_trace,
                llm_trace=llm_trace,
                usage=_usage(),
            )

        other = [tc for tc in result.tool_calls if not _is_done_tool(tc.name)]
        if not other:
            continue

        messages.append({"role": "assistant", "tool_calls": [_tool_call_to_dict(tc) for tc in other]})

        async def _one(tc: Any) -> tuple[dict[str, Any], int]:
            t0 = time.time()
            out = await _exec_internet_tool(stack, http_client, tc.name, tc.arguments)
            return out, int((time.time() - t0) * 1000)

        results = await asyncio.gather(*[_one(tc) for tc in other], return_exceptions=True)
        total_tools += len(other)

        for tc, res in zip(other, results):
            if isinstance(res, Exception):
                output: dict[str, Any] = {"error": str(res)}
                duration_ms = 0
            else:
                output, duration_ms = res

            nname = _normalize_tool_name(tc.name)
            if _output_has_evidence(nname, output):
                has_evidence = True

            tool_trace.append(
                ToolCall(
                    tool=nname,
                    reason=tc.arguments.get("reason"),
                    input={"tool": tc.name, **tc.arguments},
                    output=output if isinstance(output, dict) else {"result": output},
                    duration_ms=duration_ms,
                    iteration=iteration + 1,
                )
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": json.dumps(output, default=str),
                }
            )

    # Graceful fallback: synthesize from gathered tool evidence instead of returning a generic error.
    if has_evidence:
        fallback_prompt = (
            "You reached iteration limit. Using ONLY the collected tool outputs in this conversation, "
            "write a concise markdown answer with key findings and a short source list."
        )
        final_start = time.time()
        final_text, final_usage = await llm_config.call(
            messages=messages + [{"role": "user", "content": fallback_prompt}],
            scope="internet_research_final",
            return_usage=True,
        )
        llm_trace.append(
            LLMCall(
                scope="internet_research_final",
                duration_ms=int((time.time() - final_start) * 1000),
                input_tokens=final_usage.input_tokens,
                output_tokens=final_usage.output_tokens,
            )
        )
        total_input += final_usage.input_tokens
        total_output += final_usage.output_tokens
        final_answer = _clean_internet_text((final_text or "").strip())
        if not final_answer:
            final_answer = "I gathered web evidence but could not finalize a strong answer."
        return InternetResearchAgentResult(
            text=final_answer,
            iterations=max_iterations,
            tools_called=total_tools,
            tool_trace=tool_trace,
            llm_trace=llm_trace,
            usage=_usage(),
        )

    return InternetResearchAgentResult(
        text="Could not complete internet research within the iteration limit.",
        iterations=max_iterations,
        tools_called=total_tools,
        tool_trace=tool_trace,
        llm_trace=llm_trace,
        usage=_usage(),
    )
