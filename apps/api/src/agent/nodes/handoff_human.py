"""handoff_human - escalate to a human operator.

Production: UPDATE conversations.status = 'handoff', notify owner via Evolution.
Offline/test (no pool): logs reason, returns standby message, no side effects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from langchain_core.runnables import RunnableConfig

from ...core.config import get_settings
from ...core.logging import get_logger
from ..state import AgentState

logger = get_logger(__name__)

_STANDBY_MESSAGE = (
    "Vou chamar um atendente humano para te ajudar com isso. "
    "Em instantes alguem retorna por aqui!"
)


async def _mark_handoff(pool: Any, tenant_id: str, conversation_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE conversations SET status = 'handoff' "
            "WHERE id = $1::uuid AND tenant_id = $2::uuid AND status != 'handoff'",
            conversation_id,
            tenant_id,
        )


async def _get_owner_info(pool: Any, tenant_id: str) -> dict[str, str]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT t.settings, i.external_id AS instance_name "
            "FROM tenants t "
            "LEFT JOIN integrations i ON i.tenant_id = t.id "
            "  AND i.kind = 'whatsapp' AND i.status = 'connected' "
            "WHERE t.id = $1::uuid LIMIT 1",
            tenant_id,
        )
    if not row:
        return {}
    s = row["settings"] or {}
    return {
        "owner_whatsapp": s.get("owner_whatsapp", ""),
        "instance_name": row["instance_name"] or "",
    }


async def _notify_owner(instance_name: str, owner_phone: str, contact_phone: str, reason: str) -> None:
    cfg = get_settings()
    if not cfg.evolution_api_key or not instance_name or not owner_phone:
        return
    text = (
        f"Encaixe - Atencao necessaria\n\n"
        f"Cliente {contact_phone} precisa de atendimento humano.\n"
        f"Motivo: {reason}\n\n"
        "Acesse o dashboard para ver a conversa."
    )
    url = f"{cfg.evolution_api_url}/message/sendText/{instance_name}"
    headers = {"apikey": cfg.evolution_api_key, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"number": owner_phone, "text": text}, headers=headers)
            resp.raise_for_status()
        logger.info("handoff_human.owner_notified", instance=instance_name, owner=owner_phone)
    except Exception as exc:  # noqa: BLE001
        logger.error("handoff_human.notify_failed", error=str(exc))


async def handoff_human(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, object]:
    """Notify operators and mark the conversation as handoff."""
    confidence = state.get("confidence", 0.0)
    intent = state.get("intent")
    cfg = get_settings()
    threshold = float(
        (state.get("tenant_settings") or {}).get(  # type: ignore[union-attr]
            "confidence_threshold", cfg.agent_confidence_threshold
        )
    )
    reason = (
        f"low_confidence:{confidence:.2f}"
        if confidence < threshold
        else f"intent:{intent.value if intent else 'unknown'}"
    )

    notified_at = datetime.now(tz=timezone.utc).isoformat()
    tenant_id = state.get("tenant_id", "")
    conversation_id = state.get("conversation_id", "")
    contact_phone = state.get("contact_phone", "")

    logger.warning(
        "handoff_human.triggered",
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        reason=reason,
    )

    configurable: dict[str, Any] = (config or {}).get("configurable", {})  # type: ignore[assignment]
    pool: Any | None = configurable.get("db_pool")

    if pool is not None:
        try:
            await _mark_handoff(pool, tenant_id, conversation_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("handoff_human.mark_failed", error=str(exc))
        try:
            owner_info = await _get_owner_info(pool, tenant_id)
            if owner_info.get("owner_whatsapp") and owner_info.get("instance_name"):
                await _notify_owner(
                    instance_name=owner_info["instance_name"],
                    owner_phone=owner_info["owner_whatsapp"],
                    contact_phone=contact_phone,
                    reason=reason,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("handoff_human.owner_info_failed", error=str(exc))

    return {
        "handoff_reason": reason,
        "handoff_notified_at": notified_at,
        "response": _STANDBY_MESSAGE,
    }
