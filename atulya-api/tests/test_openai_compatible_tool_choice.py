"""
Tests for provider-specific tool_choice normalization in OpenAI-compatible provider.
"""

from atulya_api.engine.providers.openai_compatible_llm import OpenAICompatibleLLM


def _sample_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_mental_models",
                "description": "Search mental models",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_observations",
                "description": "Search observations",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]


def _sample_messages() -> list[dict]:
    return [
        {"role": "system", "content": "You are a tool-using assistant."},
        {"role": "user", "content": "Find evidence."},
    ]


def test_lmstudio_named_tool_choice_is_normalized_to_required_and_constrained():
    provider = OpenAICompatibleLLM(
        provider="lmstudio",
        api_key="local",
        base_url="http://localhost:1234/v1",
        model="openai/gpt-oss-20b",
    )

    messages, tools, tool_choice = provider._normalize_tool_choice_for_provider(
        messages=_sample_messages(),
        tools=_sample_tools(),
        tool_choice={"type": "function", "function": {"name": "search_observations"}},
    )

    assert messages == _sample_messages()
    assert tool_choice == "required"
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "search_observations"


def test_lmstudio_named_tool_choice_missing_tool_falls_back_to_required_without_constraining():
    provider = OpenAICompatibleLLM(
        provider="lmstudio",
        api_key="local",
        base_url="http://localhost:1234/v1",
        model="openai/gpt-oss-20b",
    )
    original_tools = _sample_tools()

    messages, tools, tool_choice = provider._normalize_tool_choice_for_provider(
        messages=_sample_messages(),
        tools=original_tools,
        tool_choice={"type": "function", "function": {"name": "recall"}},
    )

    assert messages == _sample_messages()
    assert tool_choice == "required"
    assert tools == original_tools


def test_openai_keeps_named_tool_choice_unchanged():
    provider = OpenAICompatibleLLM(
        provider="openai",
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )
    tool_choice_obj = {"type": "function", "function": {"name": "search_observations"}}

    messages, tools, tool_choice = provider._normalize_tool_choice_for_provider(
        messages=_sample_messages(),
        tools=_sample_tools(),
        tool_choice=tool_choice_obj,
    )

    assert messages == _sample_messages()
    assert len(tools) == 2
    assert tool_choice == tool_choice_obj
