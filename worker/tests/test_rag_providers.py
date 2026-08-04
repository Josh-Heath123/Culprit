"""Tests for the provider layer added on top of app/rag/llm.py:
get_llm_provider()'s selection/caching, and that both provider adapters
build their tool schema from app/rag/prompts.py's shared constants
instead of each defining their own (which is exactly the kind of drift
that would let the two providers silently diverge in what they force
the model to return).

Construction alone is tested here, never .generate() — each provider's
actual API client is built lazily inside .generate(), not __init__, so
none of this needs a real API key. That laziness is also what proves
LLM_PROVIDER=anthropic is genuinely just a config flip: selecting a
provider never touches its SDK client or credentials.
"""

import app.rag.llm as llm_module
import app.rag.providers.anthropic_provider as anthropic_provider
import app.rag.providers.gemini_provider as gemini_provider
import pytest
from app.rag.prompts import (
    ROOT_CAUSE_TOOL_DESCRIPTION,
    ROOT_CAUSE_TOOL_NAME,
    ROOT_CAUSE_TOOL_SCHEMA,
)
from app.rag.providers.anthropic_provider import AnthropicRootCauseLLM
from app.rag.providers.gemini_provider import GeminiRootCauseLLM


@pytest.fixture(autouse=True)
def _reset_provider_cache():
    """get_llm_provider() caches its choice at module scope — reset it
    around every test so one test's LLM_PROVIDER doesn't leak into the
    next via the cached singleton."""
    llm_module._provider = None
    yield
    llm_module._provider = None


def test_defaults_to_gemini_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(llm_module.get_llm_provider(), GeminiRootCauseLLM)


def test_selects_gemini_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert isinstance(llm_module.get_llm_provider(), GeminiRootCauseLLM)


def test_selects_anthropic_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert isinstance(llm_module.get_llm_provider(), AnthropicRootCauseLLM)


def test_provider_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    first = llm_module.get_llm_provider()
    second = llm_module.get_llm_provider()
    assert first is second


def test_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
        llm_module.get_llm_provider()


def test_anthropic_tool_uses_the_shared_schema() -> None:
    assert anthropic_provider._TOOL["name"] == ROOT_CAUSE_TOOL_NAME
    assert anthropic_provider._TOOL.get("description") == ROOT_CAUSE_TOOL_DESCRIPTION
    assert anthropic_provider._TOOL["input_schema"] is ROOT_CAUSE_TOOL_SCHEMA


def test_gemini_tool_uses_the_shared_schema() -> None:
    declaration = gemini_provider._FUNCTION_DECLARATION
    assert declaration.name == ROOT_CAUSE_TOOL_NAME
    assert declaration.description == ROOT_CAUSE_TOOL_DESCRIPTION
    assert declaration.parameters_json_schema is ROOT_CAUSE_TOOL_SCHEMA


def test_gemini_forces_the_single_tool() -> None:
    """The security property Phase 6 asks for: mode=ANY plus an explicit
    allow-list of exactly one function name means the model has no other
    tool to misuse and no way to answer with free text."""
    config = gemini_provider._TOOL_CONFIG.function_calling_config
    assert config is not None
    assert config.allowed_function_names == [ROOT_CAUSE_TOOL_NAME]
