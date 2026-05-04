import Link from "next/link";
import { notFound } from "next/navigation";
import { requireTenant } from "@/lib/tenant";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";

const ROLE_LABEL: Record<string, string> = {
  user:      "Cliente",
  assistant: "Agente",
  operator:  "Operador",
  system:    "Sistema",
};

function formatTime(iso: string) {
  return new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default async function ConversationDetailPage({
  params,
}: {
  params: { tenantSlug: string; conversationId: string };
}) {
  const tenant = await requireTenant(params.tenantSlug);
  const supabase = createServiceClient();

  // Fetch conversation
  const { data: conv } = await supabase
    .from("conversations")
    .select("id, contact_phone, contact_name, status, opted_out, created_at")
    .eq("id", params.conversationId)
    .eq("tenant_id", tenant.tenantId)
    .single();

  if (!conv) notFound();

  // Fetch messages
  const { data: messages } = await supabase
    .from("messages")
    .select("id, direction, role, content, intent, confidence, created_at")
    .eq("conversation_id", conv.id)
    .order("created_at", { ascending: true })
    .limit(200);

  const name = conv.contact_name ?? conv.contact_phone;

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <header className="flex items-center gap-4">
        <Link
          href={`/${params.tenantSlug}/conversations`}
          className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          title="Voltar"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
            <path fillRule="evenodd" d="M17 10a.75.75 0 01-.75.75H5.612l4.158 4.158a.75.75 0 11-1.06 1.06l-5.5-5.5a.75.75 0 010-1.06l5.5-5.5a.75.75 0 111.06 1.06L5.612 9.25H16.25A.75.75 0 0117 10z" clipRule="evenodd" />
          </svg>
        </Link>
        <div>
          <h1 className="text-2xl font-semibold">{name}</h1>
          <p className="text-sm text-slate-400">
            {conv.contact_phone} · {conv.status} · desde{" "}
            {new Date(conv.created_at).toLocaleDateString("pt-BR")}
            {conv.opted_out && (
              <span className="ml-2 text-red-500">Opt-out</span>
            )}
          </p>
        </div>
      </header>

      {/* Messages */}
      <div className="flex flex-col gap-3">
        {!messages || messages.length === 0 ? (
          <p className="text-sm text-slate-500">Nenhuma mensagem registrada.</p>
        ) : (
          messages.map((msg) => {
            const isUser = msg.role === "user";
            return (
              <div
                key={msg.id}
                className={`flex ${isUser ? "justify-start" : "justify-end"}`}
              >
                <div
                  className={`max-w-[70%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
                    isUser
                      ? "rounded-tl-sm bg-white border border-slate-200 text-slate-900"
                      : "rounded-tr-sm bg-brand-600 text-white"
                  }`}
                >
                  <p className="leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                  <div
                    className={`mt-1 flex items-center gap-2 text-xs ${
                      isUser ? "text-slate-400" : "text-brand-200"
                    }`}
                  >
                    <span>{ROLE_LABEL[msg.role] ?? msg.role}</span>
                    {msg.intent && (
                      <>
                        <span>·</span>
                        <span>{msg.intent}</span>
                      </>
                    )}
                    {msg.confidence != null && (
                      <span>({Math.round(Number(msg.confidence) * 100)}%)</span>
                    )}
                    <span>·</span>
                    <span>{formatTime(msg.created_at)}</span>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
