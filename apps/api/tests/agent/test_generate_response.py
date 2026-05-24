"""Unit tests for the generate_response node."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import src.agent.nodes  # noqa: F401

_gr_mod = sys.modules["src.agent.nodes.generate_response"]

from src.agent.nodes.generate_response import _FALLBACK_REPLY, _GREETING_REPLY, generate_response
from src.agent.state import AgentState, Intent
from src.core.config import get_settings


def _make_mock_client(reply_text: str, input_tokens: int = 15, output_tokens: int = 30):
    # SimpleNamespace does NOT auto-create attributes; getattr with default works correctly.
    mock_usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    mock_content = MagicMock(text=reply_text)
    mock_response = MagicMock(content=[mock_content], usage=mock_usage)
    mock_create = AsyncMock(return_value=mock_response)
    mock_client = MagicMock(messages=MagicMock(create=mock_create))
    return mock_client, mock_create


# ---------------------------------------------------------------------------
# Offline fallback path (anthropic_api_key = "")
# ---------------------------------------------------------------------------


async def test_generate_response_returns_expected_keys(base_state: AgentState) -> None:
    base_state["faq_matches"] = []
    diff = await generate_response(base_state)
    assert isinstance(diff["response"], str)
    assert len(diff["response"]) > 0
    assert set(diff["token_usage"].keys()) == {"input", "output", "cached"}
    assert all(isinstance(v, int) for v in diff["token_usage"].values())


async def test_generate_response_greeting_offline(base_state: AgentState) -> None:
    base_state["intent"] = Intent.GREETING
    base_state["faq_matches"] = []
    diff = await generate_response(base_state)
    assert "Olá" in diff["response"]
    assert diff["response"] == _GREETING_REPLY


async def test_generate_response_faq_fallback_uses_top_match(
    state_with_match: AgentState,
) -> None:
    diff = await generate_response(state_with_match)
    assert diff["response"] == state_with_match["faq_matches"][0]["answer"]


async def test_generate_response_no_match_no_greeting(base_state: AgentState) -> None:
    base_state["intent"] = Intent.OTHER
    base_state["faq_matches"] = []
    diff = await generate_response(base_state)
    assert "atendente humano" in diff["response"]
    assert diff["response"] == _FALLBACK_REPLY


async def test_generate_response_offline_token_usage_zeros(base_state: AgentState) -> None:
    diff = await generate_response(base_state)
    assert diff["token_usage"] == {"input": 0, "output": 0, "cached": 0}


async def test_generate_response_returns_only_expected_keys(base_state: AgentState) -> None:
    diff = await generate_response(base_state)
    assert set(diff.keys()) == {"response", "token_usage"}


# ---------------------------------------------------------------------------
# LLM path — monkey-patch AsyncAnthropic on the real module object
# ---------------------------------------------------------------------------


async def test_generate_response_llm_path_calls_anthropic(
    base_state: AgentState,
) -> None:
    settings = get_settings()
    original_key = settings.anthropic_api_key
    settings.anthropic_api_key = "sk-ant-test-key"

    mock_client, mock_create = _make_mock_client(
        reply_text="Posso agendar para amanha!",
        input_tokens=42,
        output_tokens=8,
    )
    original_cls = _gr_mod.AsyncAnthropic
    _gr_mod.AsyncAnthropic = MagicMock(return_value=mock_client)
    try:
        diff = await generate_response(base_state)
    finally:
        _gr_mod.AsyncAnthropic = original_cls
        settings.anthropic_api_key = original_key

    assert diff["response"] == "Posso agendar para amanha!"
    assert diff["token_usage"] == {"input": 42, "output": 8, "cached": 0}
    mock_create.assert_awaited_once()


async def test_generate_response_llm_includes_faq_context(
    state_with_match: AgentState,
) -> None:
    settings = get_settings()
    original_key = settings.anthropic_api_key
    settings.anthropic_api_key = "sk-ant-test-key"

    captured: list = []

    async def _capture(**kwargs):
        captured.append(kwargs.get("messages", []))
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        return MagicMock(content=[MagicMock(text="Ok")], usage=usage)

    mock_client = MagicMock(messages=MagicMock(create=AsyncMock(side_effect=_capture)))
    original_cls = _gr_mod.AsyncAnthropic
    _gr_mod.AsyncAnthropic = MagicMock(return_value=mock_client)
    try:
        await generate_response(state_with_match)
    finally:
        _gr_mod.AsyncAnthropic = original_cls
        settings.anthropic_api_key = original_key

    assert captured, "create() was never called"
    user_turn = captured[0][-1]
    assert user_turn["role"] == "user"
    assert "Informações relevantes" in user_turn["content"]


async def test_generate_response_llm_includes_history(base_state: AgentState) -> None:
    base_state["history"] = [
        {"role": "user", "content": "Oi!"},
        {"role": "assistant", "content": "Ola!"},
    ]
    base_state["faq_matches"] = []

    settings = get_settings()
    original_key = settings.anthropic_api_key
    settings.anthropic_api_key = "sk-ant-test-key"

    captured: list = []

    async def _capture(**kwargs):
        captured.append(kwargs.get("messages", []))
        usage = SimpleNamespace(input_tokens=20, output_tokens=10)
        return MagicMock(content=[MagicMock(text="Ok!")], usage=usage)

    mock_client = MagicMock(messages=MagicMock(create=AsyncMock(side_effect=_capture)))
    original_cls = _gr_mod.AsyncAnthropic
    _gr_mod.AsyncAnthropic = MagicMock(return_value=mock_client)
    try:
        await generate_response(base_state)
    finally:
        _gr_mod.AsyncAnthropic = original_cls
        settings.anthropic_api_key = original_key

    assert captured
    msgs = captured[0]
    assert len(msgs) >= 3
    assert msgs[0] == {"role": "user", "content": "Oi!"}
    assert msgs[1] == {"role": "assistant", "content": "Ola!"}
