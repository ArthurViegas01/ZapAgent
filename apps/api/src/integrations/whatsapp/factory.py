"""Factory: pick the WhatsApp provider based on settings.

Caching is per-process. Tests that need a fresh stub provider should call
``reset_provider()`` (or just instantiate ``StubProvider`` directly).
"""

from __future__ import annotations

from functools import lru_cache

from src.core.config import get_settings
from src.core.logging import get_logger

from .base import WhatsAppProvider
from .evolution import EvolutionProvider
from .stub import StubProvider

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_whatsapp_provider() -> WhatsAppProvider:
    """Return the configured provider singleton."""
    name = get_settings().whatsapp_provider
    if name == "stub":
        logger.info("whatsapp.provider_selected", provider="stub")
        return StubProvider()
    if name == "evolution":
        logger.info("whatsapp.provider_selected", provider="evolution")
        return EvolutionProvider()
    raise ValueError(f"Unknown WHATSAPP_PROVIDER: {name!r}")


def reset_provider() -> None:
    """Clear the cached provider (used by tests after switching settings)."""
    get_whatsapp_provider.cache_clear()
