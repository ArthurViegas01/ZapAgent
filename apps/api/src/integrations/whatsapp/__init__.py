"""WhatsApp provider port and adapters.

Public API:

  from src.integrations.whatsapp import get_whatsapp_provider

  provider = get_whatsapp_provider()
  await provider.send_text(instance_name=..., phone=..., text=...)
"""

from .base import (
    ConnectionUpdate,
    EventType,
    InboundMessage,
    SessionInfo,
    WhatsAppProvider,
)
from .factory import get_whatsapp_provider, reset_provider

__all__ = [
    "ConnectionUpdate",
    "EventType",
    "InboundMessage",
    "SessionInfo",
    "WhatsAppProvider",
    "get_whatsapp_provider",
    "reset_provider",
]
