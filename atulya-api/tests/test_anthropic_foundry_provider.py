import types
from unittest.mock import MagicMock, patch


def test_anthropic_foundry_is_supported_provider():
    from atulya_api.config import PROVIDER_DEFAULT_MODELS
    from atulya_api.engine.llm_wrapper import LLMProvider
    from atulya_api.engine.providers.anthropic_llm import AnthropicLLM

    fake_anthropic = types.SimpleNamespace(AsyncAnthropic=MagicMock())

    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        provider = LLMProvider(
            provider="anthropic-foundry",
            api_key="test-key",
            base_url="https://example.services.ai.azure.com/anthropic/",
            model="claude-sonnet-4-6",
        )

    assert PROVIDER_DEFAULT_MODELS["anthropic-foundry"] == "claude-sonnet-4-6"
    assert provider.provider == "anthropic-foundry"
    assert isinstance(provider._provider_impl, AnthropicLLM)
