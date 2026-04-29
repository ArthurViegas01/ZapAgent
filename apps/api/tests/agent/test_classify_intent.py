"""Unit tests for the classify_intent node."""

from __future__ import annotations

import pytest

from src.agent.nodes.classify_intent import classify_intent
from src.agent.state import AgentState, Intent


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Quero agendar um horário para amanhã", Intent.SCHEDULING),
        ("Marcar consulta às 15h", Intent.SCHEDULING),
        ("Qual o preço do corte?", Intent.PRICING),
        ("Quanto custa a consulta?", Intent.PRICING),
        ("Bom dia!", Intent.GREETING),
        ("Olá, tudo bem?", Intent.GREETING),
        ("Qual é o endereço?", Intent.INFORMATION),
        ("PARAR", Intent.OPT_OUT),
        ("quero cancelar inscrição", Intent.OPT_OUT),
        ("blablabla aleatório", Intent.OTHER),
    ],
)
def test_classify_intent_keyword_routing(
    base_state: AgentState, message: str, expected: Intent
) -> None:
    base_state["user_message"] = message
    diff = classify_intent(base_state)
    assert diff == {"intent": expected}


def test_classify_intent_empty_message_returns_other(base_state: AgentState) -> None:
    base_state["user_message"] = ""
    diff = classify_intent(base_state)
    assert diff == {"intent": Intent.OTHER}


def test_classify_intent_returns_only_partial_state(base_state: AgentState) -> None:
    """Nodes must not pollute state with unrelated keys."""
    diff = classify_intent(base_state)
    assert set(diff.keys()) == {"intent"}
