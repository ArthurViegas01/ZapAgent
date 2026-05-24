"""Subscription gate — does this tenant get to use the agent right now?

Today this is a hand-rolled trial timer + on/off switch. Tomorrow (when
Asaas integration lands in P2) the same shape will be driven by webhook
state changes (`subscription.updated` → `subscription_status`,
`payment.overdue` → `past_due`, repeated misses → `suspended`).

Contract
--------
Callers ask one question — "should I serve this turn?" — and get back a
fully-formed ``GateResult`` they can act on:

    decision = await check_subscription(pool, tenant_id)
    if not decision.allowed:
        # respond with decision.reply_to_customer; do NOT enqueue agent
        ...

Why a dataclass instead of a bool
---------------------------------
The pilot needs to TELL the customer why we stopped replying — silent
drop is the worst UX and turns into "the bot is broken" tickets. The
result carries a pre-localized pt-BR message so the webhook handler
doesn't need to know billing terminology.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from .logging import get_logger

logger = get_logger(__name__)

SubscriptionStatus = Literal["trialing", "active", "past_due", "suspended", "unknown"]


@dataclass(frozen=True)
class GateResult:
    """Outcome of a subscription check.

    ``allowed=True``  → serve the turn normally.
    ``allowed=False`` → reply to the customer with ``reply_to_customer``
                        and skip the agent. The reason is logged so we
                        can audit drop rates per status.
    """

    allowed: bool
    status: SubscriptionStatus
    days_left: int | None  # only meaningful for trialing
    reply_to_customer: str  # empty when allowed=True
    reason: str  # short tag for logs/metrics


# pt-BR customer-facing copies. Kept here (not in a localization file)
# because they are the SLA we're committing to — changing them is a
# product decision, not a translation chore.
_MSG_TRIAL_EXPIRED = (
    "Olá! Seu período de teste do atendimento automático terminou. "
    "Para reativar, fale com nosso time pelo contato cadastrado. "
    "Obrigado pelo interesse!"
)
_MSG_SUSPENDED = (
    "Olá! O atendimento automático está temporariamente pausado. "
    "Vamos retornar assim que regularizarmos o seu acesso. "
    "Pedimos desculpas pelo inconveniente."
)
_MSG_UNKNOWN_TENANT = "Olá! Esta conta ainda não está configurada para atendimento automático."


async def check_subscription(pool: Any, tenant_id: str) -> GateResult:
    """Decide whether ``tenant_id`` is allowed to run the agent right now.

    Decision matrix:
      * ``active``    → allowed, no message.
      * ``trialing``  → allowed iff ``trial_ends_at`` is in the future;
                        days_left counts down to expiry.
      * ``past_due``  → still allowed (grace period); operations alert
                        the operator, but the customer keeps service.
                        Switch to ``suspended`` manually or via webhook
                        when the grace period runs out.
      * ``suspended`` → blocked, customer-facing pause message.
      * tenant missing → blocked, neutral "not configured" message.

    Args:
        pool: asyncpg.Pool. We do not set ``app.tenant_id`` here because
            the gate runs BEFORE the request enters a tenant-scoped
            transaction, and the read is single-row keyed by primary key
            — no RLS surface is exposed.
        tenant_id: UUID string.

    Returns:
        GateResult. Never raises for routine billing states; only
        infrastructure errors (DB unreachable) bubble up — the caller
        decides whether to fail-open or fail-closed.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT subscription_status, trial_ends_at FROM tenants WHERE id = $1::uuid LIMIT 1",
            tenant_id,
        )

    if row is None:
        logger.warning("billing_gate.tenant_missing", tenant_id=tenant_id)
        return GateResult(
            allowed=False,
            status="unknown",
            days_left=None,
            reply_to_customer=_MSG_UNKNOWN_TENANT,
            reason="tenant_not_found",
        )

    status: SubscriptionStatus = row["subscription_status"]
    trial_ends_at: datetime | None = row["trial_ends_at"]

    if status == "active":
        return GateResult(
            allowed=True,
            status=status,
            days_left=None,
            reply_to_customer="",
            reason="active",
        )

    if status == "past_due":
        # Grace period: keep serving the customer; the operator gets
        # alerted through a separate channel (dashboard banner, email).
        return GateResult(
            allowed=True,
            status=status,
            days_left=None,
            reply_to_customer="",
            reason="past_due_grace",
        )

    if status == "suspended":
        logger.info("billing_gate.blocked", tenant_id=tenant_id, status=status)
        return GateResult(
            allowed=False,
            status=status,
            days_left=None,
            reply_to_customer=_MSG_SUSPENDED,
            reason="suspended",
        )

    # status == "trialing" (or any unforeseen value falls through here).
    if trial_ends_at is None:
        # Misconfigured tenant: trialing without an end date. Allow but
        # log loudly so we catch the gap before a customer hits it.
        logger.warning(
            "billing_gate.trialing_without_end_date",
            tenant_id=tenant_id,
        )
        return GateResult(
            allowed=True,
            status=status,
            days_left=None,
            reply_to_customer="",
            reason="trialing_no_end",
        )

    now = datetime.now(tz=UTC)
    remaining = trial_ends_at - now
    days_left = max(0, remaining.days)

    if remaining.total_seconds() <= 0:
        logger.info(
            "billing_gate.blocked",
            tenant_id=tenant_id,
            status=status,
            reason="trial_expired",
        )
        return GateResult(
            allowed=False,
            status=status,
            days_left=0,
            reply_to_customer=_MSG_TRIAL_EXPIRED,
            reason="trial_expired",
        )

    return GateResult(
        allowed=True,
        status=status,
        days_left=days_left,
        reply_to_customer="",
        reason="trialing",
    )
