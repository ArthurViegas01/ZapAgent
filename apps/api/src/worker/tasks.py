"""Celery task definitions."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from src.core.config import get_settings
from src.core.logging import get_logger

from .celery_app import app

logger = get_logger(__name__)
settings = get_settings()


async def _load_tenant_settings(pool: Any, tenant_id: str) -> dict[str, Any]:
    """Fetch and normalize tenant settings for the agent."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name, settings FROM tenants WHERE id = $1::uuid LIMIT 1",
                tenant_id,
            )
        if not row:
            return {}
        raw = row["settings"] or {}
        # asyncpg returns json columns as strings; jsonb columns come back as dicts.
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                raw = {}
        s: dict[str, Any] = raw if isinstance(raw, dict) else {}
        hours = s.get("business_hours")
        if hours:
            bh = f"Segunda a sexta, {hours.get('open','09:00')} as {hours.get('close','18:00')}."
        else:
            bh = "Segunda a sexta, 9h as 18h."
        return {
            "name": row["name"] or s.get("name", "Assistente Virtual"),
            "persona": s.get("agent_persona", "Atendente educado e prestativo."),
            "business_hours": bh,
            "phone": s.get("owner_phone", "nao disponivel"),
            "confidence_threshold": s.get("confidence_threshold", settings.agent_confidence_threshold),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("worker.load_settings_failed", tenant_id=tenant_id, error=str(exc))
        return {}



async def _check_opted_out(pool: Any, tenant_id: str, contact_phone: str) -> bool:
    """Return True if this contact has previously opted out."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT opted_out FROM conversations "
                "WHERE tenant_id = $1::uuid AND contact_phone = $2 LIMIT 1",
                tenant_id,
                contact_phone,
            )
        return bool(row and row["opted_out"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("worker.opted_out_check_failed", error=str(exc))
        return False


async def _mark_opted_out(pool: Any, tenant_id: str, conversation_id: str) -> None:
    """Set opted_out = TRUE and status = closed on the conversation."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE conversations SET opted_out = TRUE, status = 'closed' "
                "WHERE id = $1::uuid AND tenant_id = $2::uuid",
                conversation_id,
                tenant_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("worker.mark_opted_out_failed", error=str(exc))


async def _run_agent(
    tenant_id: str,
    conversation_id: str,
    contact_phone: str,
    user_message: str,
    tenant_settings: dict[str, Any],
    pool: Any,
) -> dict:
    from src.agent.checkpointer import async_postgres_saver_scope  # noqa: PLC0415
    from src.agent.context import set_db_pool  # noqa: PLC0415
    from src.agent.graph import build_graph  # noqa: PLC0415
    from src.agent.state import AgentState  # noqa: PLC0415

    # Thread the pool to retrieve_context via a task-scoped contextvar.
    # LangGraph's `configurable` slot filters out our db_pool key, so
    # passing it through `config={"configurable": {...}}` no longer reaches
    # the node (verified empirically). See src/agent/context.py.
    set_db_pool(pool)

    state = AgentState(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_phone=contact_phone,
        user_message=user_message,
        tenant_settings=tenant_settings,  # type: ignore[typeddict-item]
    )
    config = {
        "configurable": {
            "thread_id": f"{tenant_id}:{conversation_id}",
        }
    }

    # Durable checkpointer per ARCHITECTURE.md §2.5 — survives worker
    # restarts so a mid-conversation customer doesn't lose context.
    # Saver is opened per task (the loop owns its pool) — see
    # checkpointer.py docstring for why process-singletons crashed.
    # If init fails (e.g. checkpoint tables can't be created on a read-
    # only replica), fall back to MemorySaver so the turn still
    # completes; next process restart re-attempts setup.
    try:
        async with async_postgres_saver_scope() as checkpointer:
            graph = build_graph(checkpointer=checkpointer)
            return await graph.ainvoke(state, config=config)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "worker.checkpointer_fallback_to_memory",
            error=str(exc),
            tenant_id=tenant_id,
        )
        graph = build_graph(checkpointer=None)
        return await graph.ainvoke(state, config=config)


async def _send_whatsapp_reply(instance_name: str, contact_phone: str, text: str) -> None:
    """Sends an outbound WhatsApp text via the configured provider.

    Provider is resolved from ``settings.whatsapp_provider`` (evolution | stub).
    Stub mode short-circuits the network call and writes to a debug log so
    end-to-end tests can run without an Evolution / WPP / Cloud API account.
    """
    from src.integrations.whatsapp.factory import get_whatsapp_provider  # noqa: PLC0415

    provider = get_whatsapp_provider()
    await provider.send_text(instance_name=instance_name, phone=contact_phone, text=text)
    logger.info(
        "worker.reply_sent",
        instance=instance_name,
        phone=contact_phone,
        provider=provider.name,
    )


async def _persist_outbound(pool: Any, tenant_id: str, conversation_id: str, content: str, final_state: dict) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages "
            "(tenant_id, conversation_id, direction, role, content, intent, confidence, token_usage) "
            "VALUES ($1, $2, 'outbound', 'assistant', $3, $4, $5, $6::jsonb)",
            tenant_id,
            conversation_id,
            content,
            final_state.get("intent", {}).value if final_state.get("intent") else None,
            final_state.get("confidence"),
            json.dumps(final_state.get("token_usage", {})),
        )


@app.task(name="tasks.purge_old_messages")
def purge_old_messages() -> dict:
    """Nightly LGPD retention: delete messages older than each tenant's retention window."""
    async def _run() -> dict:
        from src.db.pool import worker_pool_scope  # noqa: PLC0415
        async with worker_pool_scope() as pool:
            async with pool.acquire() as conn:
                result = await conn.fetchrow(
                    "WITH deleted AS ("
                    " DELETE FROM messages m USING tenants t"
                    " WHERE m.tenant_id = t.id"
                    " AND t.data_retention_days IS NOT NULL"
                    " AND m.created_at < now() - (t.data_retention_days || ' days')::interval"
                    " RETURNING m.id"
                    ") SELECT count(*) AS deleted_count FROM deleted"
                )
            count = result["deleted_count"] if result else 0
            logger.info("retention.purge_done", deleted=count)
            return {"deleted": count}

    return asyncio.run(_run())


@app.task(bind=True, max_retries=3, default_retry_delay=10)
def process_whatsapp_message(
    self,
    tenant_id: str,
    conversation_id: str,
    contact_phone: str,
    user_message: str,
    instance_name: str = "",
) -> dict:
    """Run the LangGraph agent for an inbound WhatsApp message."""
    logger.info("worker.task.started", tenant_id=tenant_id, conversation_id=conversation_id, instance=instance_name)

    async def _main() -> dict:
        from src.db.pool import worker_pool_scope  # noqa: PLC0415

        # Pool is task-scoped: opens in this loop, closes when this loop
        # exits. Sharing a pool across asyncio.run() calls crashes with
        # "Event loop is closed".
        async with worker_pool_scope() as pool:
            # Skip opted-out contacts — do not run agent or reply.
            if await _check_opted_out(pool, tenant_id, contact_phone):
                logger.info("worker.opted_out_skip", tenant_id=tenant_id, contact_phone=contact_phone)
                return {"conversation_id": conversation_id, "next_action": "opted_out", "response": ""}

            tenant_settings = await _load_tenant_settings(pool, tenant_id)
            final_state = await _run_agent(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                contact_phone=contact_phone,
                user_message=user_message,
                tenant_settings=tenant_settings,
                pool=pool,
            )
            response_text: str = final_state.get("response", "")

            # Persist opt-out if the agent classified the message as OPT_OUT.
            from src.agent.state import Intent as _Intent  # noqa: PLC0415
            if final_state.get("intent") == _Intent.OPT_OUT:
                await _mark_opted_out(pool, tenant_id, conversation_id)

            if instance_name and response_text:
                try:
                    await _send_whatsapp_reply(instance_name, contact_phone, response_text)
                except Exception as exc:  # noqa: BLE001
                    logger.error("worker.reply_failed", error=str(exc))

            if response_text:
                try:
                    await _persist_outbound(pool, tenant_id, conversation_id, response_text, final_state)
                except Exception as exc:  # noqa: BLE001
                    logger.error("worker.persist_failed", error=str(exc))

            return {
                "conversation_id": conversation_id,
                "next_action": final_state.get("next_action"),
                "response": response_text,
            }

    try:
        result = asyncio.run(_main())
        logger.info("worker.task.done", conversation_id=conversation_id, next_action=result.get("next_action"))
        return result
    except Exception as exc:
        logger.error("worker.task.error", error=str(exc))
        # Don't retry permanent API errors (billing / auth) — retrying won't fix them
        # and causes cascading asyncpg connection issues in the worker.
        error_msg = str(exc).lower()
        if any(k in error_msg for k in ("credit balance", "too low", "invalid_api_key", "authentication")):
            logger.error("worker.task.permanent_error", reason="billing_or_auth", error=str(exc))
            return {"conversation_id": conversation_id, "error": str(exc), "permanent": True}
        raise self.retry(exc=exc)
