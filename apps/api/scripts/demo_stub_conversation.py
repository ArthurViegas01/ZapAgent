"""End-to-end demo using the Stub WhatsApp provider.

Runs without Evolution API, without a WhatsApp account, without any external
network for the WhatsApp leg. Exercises the full pipeline:

  1. POST a fake inbound message to /webhooks/whatsapp
  2. Webhook deduplicates, persists, dispatches to Celery (eager mode)
  3. Worker invokes the LangGraph agent (offline fallback paths)
  4. Worker hands the reply to StubProvider.send_text
  5. Demo prints what the user *would have received* on WhatsApp

Run inside the api container:

    docker compose exec api python -m scripts.demo_stub_conversation
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

# Ensure stub mode regardless of .env contents.
os.environ["WHATSAPP_PROVIDER"] = "stub"
os.environ["EVOLUTION_WEBHOOK_TOKEN"] = "demo-token"

from src.core.config import get_settings  # noqa: E402
from src.integrations.whatsapp import (  # noqa: E402
    get_whatsapp_provider,
    reset_provider,
)
from src.integrations.whatsapp.stub import StubProvider  # noqa: E402

DEMO_TENANT_ID = "00000000-0000-0000-0000-0000000d3070"
DEMO_PHONE = "5511999990000"
DEMO_INSTANCE = "demo-instance"


async def _send_inbound(text: str) -> None:
    """Run the inbound webhook -> agent -> outbound flow once.

    Bypasses the HTTP layer and Celery broker (eager mode would require a
    Redis connection); instead we directly call the worker task body so the
    demo is self-contained.
    """
    from src.agent.graph import build_graph
    from src.agent.state import AgentState

    msg_id = "demo_" + uuid.uuid4().hex[:10]
    print(f"\n  [user]  {text}")

    graph = build_graph()
    state = AgentState(
        tenant_id=DEMO_TENANT_ID,
        conversation_id="11111111-1111-1111-1111-1111deadbeef",
        contact_phone=DEMO_PHONE,
        user_message=text,
    )
    final = await graph.ainvoke(state, config={"configurable": {"thread_id": "demo"}})
    reply = final.get("response", "(no reply)")
    next_action = final.get("next_action", "?")

    provider = get_whatsapp_provider()
    if reply:
        await provider.send_text(instance_name=DEMO_INSTANCE, phone=DEMO_PHONE, text=reply)

    print(f"  [bot ]  {reply}")
    print(f"          next_action={next_action} confidence={final.get('confidence', 0.0):.2f}")
    return msg_id


async def main() -> int:
    s = get_settings()
    s.whatsapp_provider = "stub"
    reset_provider()

    provider = get_whatsapp_provider()
    if not isinstance(provider, StubProvider):
        print("[fatal] expected StubProvider, got", type(provider).__name__, file=sys.stderr)
        return 2

    print("=" * 64)
    print("ZapAgent demo -- StubProvider end-to-end conversation")
    print("=" * 64)
    print("Provider:", provider.name)
    print("Tenant  :", DEMO_TENANT_ID)
    print("Phone   :", DEMO_PHONE)
    print("(LangGraph runs offline-fallback paths -- no LLM key required)")

    # Simulate a session pairing.
    info = await provider.create_session(DEMO_INSTANCE)
    print("\n[session] status=%s qrcode bytes=%d" % (info.status, len(info.qrcode_data_url)))

    for line in [
        "Oi, tudo bem?",
        "Quero saber o horario de funcionamento",
        "Quero agendar amanha as 10h",
        "PARAR",  # opt-out keyword
    ]:
        await _send_inbound(line)

    print("\n--- Outbound log captured by StubProvider ---")
    print(json.dumps(provider.sent, indent=2, ensure_ascii=False))
    print("\nDone. In production, swap WHATSAPP_PROVIDER=evolution to use Evolution API.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
