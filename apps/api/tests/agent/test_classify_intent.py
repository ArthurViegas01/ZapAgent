"""Unit tests for the classify_intent node.

All tests run with ANTHROPIC_API_KEY="" (forced by conftest._override_settings)
so the offline / keyword-heuristic path is always exercised here.
"""

from __future__ import annotations

import pytest

from src.agent.nodes.classify_intent import classify_intent
from src.agent.state import AgentState, Intent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Quero agendar um horario para amanha", Intent.SCHEDULING),
        ("Marcar consulta as 15h", Intent.SCHEDULING),
        ("Qual o preco do corte?", Intent.PRICING),
        ("Quanto custa a consulta?", Intent.PRICING),
        ("Bom dia!", Intent.GREETING),
        ("Ola, tudo bem?", Intent.GREETING),
        ("Qual e o endereco?", Intent.INFORMATION),
        ("PARAR", Intent.OPT_OUT),
        ("quero cancelar inscricao", Intent.OPT_OUT),
        ("blablabla aleatorio", Intent.OTHER),
    ],
)
async def test_classify_intent_keyword_routing(
    base_state: AgentState, message: str, expected: Intent
) -> None:
    base_state["user_message"] = message
    diff = await classify_intent(base_state)
    assert diff["intent"] == expected


@pytest.mark.asyncio
async def test_classify_intent_empty_message_returns_other(base_state: AgentState) -> None:
    base_state["user_message"] = ""
    diff = await classify_intent(base_state)
    assert diff["intent"] == Intent.OTHER


@pytest.mark.asyncio
async def test_classify_intent_opt_out_fast_path(base_state: AgentState) -> None:
    base_state["user_message"] = "nao quero mais receber mensagens"
    diff = await classify_intent(base_state)
    assert diff["intent"] == Intent.OPT_OUT


@pytest.mark.asyncio
async def test_classify_intent_returns_intent_key(base_state: AgentState) -> None:
    diff = await classify_intent(base_state)
    assert "intent" in diff
