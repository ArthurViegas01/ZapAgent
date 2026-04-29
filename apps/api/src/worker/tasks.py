"""Celery task definitions.

Each task corresponds to an async operation triggered by the webhook receiver
or other external events. Heavy work (graph invocation, Evolution API calls)
happens here so the HTTP request/response cycle stays fast.
"""

from __future__ import annotations

from src.core.logging import get_logger

from .celery_app import app

logger = get_logger(__name__)


@app.task(bind=True, max_retries=3, default_retry_delay=5)
def process_whatsapp_message(
    self,
    tenant_id: str,
    conversation_id: str,
    contact_phone: str,
    user_message: str,
) -> dict:
    """Run the LangGraph agent for an inbound WhatsApp message.

    This is a placeholder — the real implementation will:
    1. Acquire a DB pool connection.
    2. Call graph.ainvoke() inside asyncio.run().
    3. Send the response back via the Evolution API.
    4. Persist the conversation turn.
    """
    logger.info(
        "worker.process_whatsapp_message.received",
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    # TODO: implement full graph invocation (Etapa 2).
    return {"status": "queued", "conversation_id": conversation_id}
