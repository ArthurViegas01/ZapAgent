"""retrieve_context — embed with voyage-3-lite, query pgvector, fetch history.

Production path (requires db_pool in LangGraph config + VOYAGE_API_KEY):
  1. Embed state["user_message"] with voyage-3-lite (512-dim).
  2. Query faq_items via pgvector cosine distance operator (<=>).
  3. Fetch the last 10 messages of the conversation in chronological order.

Offline / test path (no pool or no key): returns empty stubs so that
downstream nodes can still run without any network calls.

DB pool is passed through the LangGraph config dict so that nodes remain
pure functions and the pool is created once at startup:

    await graph.ainvoke(state, config={
        "configurable": {
            "thread_id": "...",
            "db_pool": pool,  # asyncpg.Pool
        }
    })
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from ...core.config import get_settings
from ...core.logging import get_logger
from ..state import AgentState, FaqMatch

logger = get_logger(__name__)


def _vec_literal(embedding: list[float]) -> str:
    """Serialize a float list to the pgvector string format [x,y,z,...]."""
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


async def _embed(text: str) -> list[float]:
    """Embed a single text with the configured voyage model.

    Import is deferred to avoid startup cost when no key is set.
    """
    import voyageai

    settings = get_settings()
    client = voyageai.AsyncClient(api_key=settings.voyage_api_key)
    # output_dimension=1024 must match faq_items.embedding VECTOR(1024).
    # voyage-3-lite defaults to 512; passing it explicitly keeps the schema
    # contract whether voyage_model is voyage-3-lite, voyage-3, or future variants.
    result = await client.embed(texts=[text], model=settings.voyage_model, output_dimension=1024)
    return result.embeddings[0]  # type: ignore[no-any-return]


async def _query_faq(
    pool: Any,
    tenant_id: str,
    vec_lit: str,
    top_k: int,
) -> list[FaqMatch]:
    """Run the pgvector similarity search inside an explicit transaction.

    SET LOCAL app.tenant_id satisfies the RLS policy defined in the
    migration (current_tenant_id() reads from that GUC).
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
        rows = await conn.fetch(
            "SELECT id::text, question, answer,"
            " (1 - (embedding <=> $1::vector))::float AS score"
            " FROM faq_items"
            " WHERE tenant_id = $2::uuid AND is_active"
            " ORDER BY embedding <=> $1::vector"
            " LIMIT $3",
            vec_lit,
            tenant_id,
            top_k,
        )
    return [
        FaqMatch(
            id=row["id"],
            question=row["question"],
            answer=row["answer"],
            score=float(row["score"]),
        )
        for row in rows
    ]


async def _query_history(
    pool: Any,
    tenant_id: str,
    conversation_id: str,
) -> list[dict[str, Any]]:
    """Fetch the last 10 messages, returned in chronological order."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            # MISS-001: scope by tenant_id, not by conversation id alone.
            "SELECT role, content FROM messages"
            " WHERE conversation_id = $1::uuid"
            "   AND tenant_id = $2::uuid"
            " ORDER BY created_at DESC LIMIT 10",
            conversation_id,
            tenant_id,
        )
    # Rows arrive newest-first; reverse to oldest-first for the LLM prompt.
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


async def retrieve_context(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, object]:
    """Pull FAQ matches and recent history for the conversation.

    Args:
        state: must carry tenant_id, conversation_id, user_message.
        config: LangGraph config dict; expects config["configurable"]["db_pool"]
            to be an asyncpg.Pool. When absent the node returns empty stubs.

    Returns:
        Partial state with faq_matches (list[FaqMatch]) and
        history (list[{role, content}]).
    """
    settings = get_settings()
    top_k = settings.agent_rag_top_k

    # LangGraph's `configurable` slot drops our `db_pool` key (filtered by
    # the framework before the node is invoked, observed empirically on
    # 2026-05-24). Read the pool from a task-scoped contextvar instead;
    # see src/agent/context.py for the rationale.
    from ..context import get_db_pool

    pool: Any | None = get_db_pool()
    # Backwards-compat: still honor a pool passed via LangGraph config
    # if a future framework version re-enables it.
    if pool is None:
        configurable: dict[str, Any] = (config or {}).get("configurable", {})  # type: ignore[assignment]
        pool = configurable.get("db_pool")

    if pool is None or not settings.voyage_api_key:
        reason = "no_pool" if pool is None else "no_voyage_key"
        logger.debug(
            "retrieve_context.stub",
            tenant_id=state.get("tenant_id"),
            reason=reason,
        )
        return {"faq_matches": [], "history": []}

    message = state.get("user_message", "")
    tenant_id = state.get("tenant_id", "")
    conversation_id = state.get("conversation_id", "")

    embedding = await _embed(message)
    vec_lit = _vec_literal(embedding)

    matches = await _query_faq(pool, tenant_id, vec_lit, top_k)
    history = await _query_history(pool, tenant_id, conversation_id)

    logger.info(
        "retrieve_context.done",
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        match_count=len(matches),
        history_count=len(history),
        top_k=top_k,
    )
    return {"faq_matches": matches, "history": history}
