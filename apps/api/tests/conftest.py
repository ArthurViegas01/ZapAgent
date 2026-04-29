"""Shared pytest fixtures.

Anything that touches settings or external services should go through a
fixture here so individual tests stay short and consistent.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.agent.state import AgentState, Intent
from src.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _override_settings() -> None:
    """Force test environment for every test.

    `get_settings` is `lru_cache`d, so we mutate the cached instance in place
    instead of trying to clear the cache (which races with parallel tests).
    """
    settings = get_settings()
    settings.environment = "test"
    settings.log_level = "WARNING"
    settings.agent_confidence_threshold = 0.65
    # Clear API keys so offline fallback paths run in CI / local tests.
    # Individual tests that need a real (or mock) key set it themselves.
    settings.anthropic_api_key = ""
    settings.voyage_api_key = ""


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def base_state() -> AgentState:
    """A minimal state suitable for feeding any node's first call."""
    return AgentState(
        tenant_id="00000000-0000-0000-0000-000000000001",
        conversation_id="11111111-1111-1111-1111-111111111111",
        contact_phone="5511999999999",
        user_message="Quero agendar um horário para amanhã às 10h",
    )


@pytest.fixture
def state_with_match(base_state: AgentState) -> AgentState:
    """State pre-loaded with a high-scoring FAQ match."""
    base_state["faq_matches"] = [
        {
            "id": "faq_1",
            "question": "Qual é o horário de funcionamento?",
            "answer": "Atendemos de segunda a sábado, das 9h às 19h.",
            "score": 0.92,
        }
    ]
    base_state["intent"] = Intent.INFORMATION
    return base_state


def assert_partial_state(diff: dict[str, Any], required_keys: set[str]) -> None:
    """Helper: nodes return *partial* state. Assert all required keys are present."""
    missing = required_keys - diff.keys()
    assert not missing, f"node output missing keys: {sorted(missing)}"
