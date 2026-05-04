import Link from "next/link";
import { requireTenant } from "@/lib/tenant";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";

const STATUS_LABELS: Record<string, { label: string; classes: string }> = {
  active:  { label: "Ativo",    classes: "bg-emerald-100 text-emerald-700" },
  handoff: { label: "Humano",   classes: "bg-amber-100 text-amber-700" },
  closed:  { label: "Encerrado", classes: "bg-slate-100 text-slate-500" },
};

function formatDate(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffH = diffMs / 1000 / 3600;
  if (diffH < 24) {
    return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

export default async function ConversationsPage({
  params,
}: {
  params: { tenantSlug: string };
}) {
  const tenant = await requireTenant(params.tenantSlug);
  const supabase = createServiceClient();

  const { data: conversations } = await supabase
    .from("conversations")
    .select("id, contact_phone, contact_name, status, opted_out, last_message_at, created_at")
    .eq("tenant_id", tenant.tenantId)
    .order("last_message_at", { ascending: false, nullsFirst: false })
    .limit(100);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Conversas</h1>
        <p className="text-sm text-slate-500">
          Histórico de conversas com seus clientes via WhatsApp.
        </p>
      </header>

      {!conversations || conversations.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 py-16 text-center">
          <p className="text-sm text-slate-500">
            Nenhuma conversa ainda. Conecte seu WhatsApp na aba{" "}
            <Link
              href={`/${params.tenantSlug}/integrations`}
              className="text-brand-600 underline hover:no-underline"
            >
              Integrações
            </Link>
            .
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 bg-slate-50 text-left">
              <tr>
                <th className="px-4 py-3 font-medium text-slate-500">Contato</th>
                <th className="px-4 py-3 font-medium text-slate-500">Status</th>
                <th className="px-4 py-3 font-medium text-slate-500">Última mensagem</th>
                <th className="px-4 py-3 font-medium text-slate-500"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {conversations.map((conv) => {
                const st = STATUS_LABELS[conv.status] ?? STATUS_LABELS.active;
                const name = conv.contact_name ?? conv.contact_phone;
                return (
                  <tr key={conv.id} className="hover:bg-slate-50 transition">
                    <td className="px-4 py-3">
                      <p className="font-medium text-slate-900">{name}</p>
                      {conv.contact_name && (
                        <p className="text-xs text-slate-400">{conv.contact_phone}</p>
                      )}
                      {conv.opted_out && (
                        <span className="text-xs text-red-500">Opt-out</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${st.classes}`}>
                        {st.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {formatDate(conv.last_message_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/${params.tenantSlug}/conversations/${conv.id}`}
                        className="rounded-md px-3 py-1.5 text-xs font-medium text-brand-600 hover:bg-brand-50"
                      >
                        Ver →
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
