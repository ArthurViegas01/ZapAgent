import Link from "next/link";

import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";
import { requireTenant } from "@/lib/tenant";

async function fetchMetrics(tenantId: string) {
  const supabase = createServiceClient();
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

  const [{ count: activeConvs }, { count: repliedMsgs }, { count: appointments }] =
    await Promise.all([
      supabase
        .from("conversations")
        .select("id", { count: "exact", head: true })
        .eq("tenant_id", tenantId)
        .eq("status", "active"),
      supabase
        .from("messages")
        .select("id", { count: "exact", head: true })
        .eq("tenant_id", tenantId)
        .eq("direction", "outbound")
        .eq("role", "assistant")
        .gte("created_at", since),
      supabase
        .from("appointments")
        .select("id", { count: "exact", head: true })
        .eq("tenant_id", tenantId)
        .gte("created_at", since),
    ]);

  return {
    activeConvs: activeConvs ?? 0,
    repliedMsgs: repliedMsgs ?? 0,
    appointments: appointments ?? 0,
  };
}

async function fetchRecentConversations(tenantId: string) {
  const supabase = createServiceClient();
  const { data } = await supabase
    .from("conversations")
    .select("id, contact_phone, contact_name, status, last_message_at")
    .eq("tenant_id", tenantId)
    .order("last_message_at", { ascending: false })
    .limit(5);
  return data ?? [];
}

async function fetchWhatsappStatus(tenantId: string) {
  const supabase = createServiceClient();
  const { data } = await supabase
    .from("integrations")
    .select("status, external_id")
    .eq("tenant_id", tenantId)
    .eq("kind", "whatsapp")
    .single();
  return data;
}

/**
 * Read the tenant's billing snapshot — drives the trial-countdown /
 * subscription-paused banner. Mirrors the API's `GET /v1/tenants/{id}/billing`
 * shape so the same fields can be reused if/when we add a client-side
 * refresh; today the dashboard fetches at render time via the service
 * client (no JWT round-trip).
 */
async function fetchBillingStatus(tenantId: string): Promise<{
  status: string;
  days_left: number | null;
  trial_ends_at: string | null;
}> {
  const supabase = createServiceClient();
  const { data } = await supabase
    .from("tenants")
    .select("subscription_status, trial_ends_at")
    .eq("id", tenantId)
    .single();
  const status = (data?.subscription_status ?? "trialing") as string;
  const trialEnds = data?.trial_ends_at ?? null;
  let daysLeft: number | null = null;
  if (trialEnds) {
    const ms = new Date(trialEnds).getTime() - Date.now();
    daysLeft = Math.max(0, Math.floor(ms / (1000 * 60 * 60 * 24)));
  }
  return { status, days_left: daysLeft, trial_ends_at: trialEnds };
}

export default async function TenantOverviewPage({
  params,
}: {
  params: { tenantSlug: string };
}) {
  const tenant = await requireTenant(params.tenantSlug);

  const [metrics, recentConvs, whatsapp, billing] = await Promise.all([
    fetchMetrics(tenant.tenantId),
    fetchRecentConversations(tenant.tenantId),
    fetchWhatsappStatus(tenant.tenantId),
    fetchBillingStatus(tenant.tenantId),
  ]);

  const isConnected = whatsapp?.status === "connected";
  // Banner is shown for any non-active state worth the customer's attention.
  // "active" → silent (paying customer in good standing).
  // "trialing" → countdown.
  // "past_due" / "suspended" → urgent banner with action.
  const showBillingBanner = billing.status !== "active";

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <header>
        <h1 className="text-2xl font-semibold">Visão geral</h1>
        <p className="text-sm text-slate-500">Últimas 24 horas · {tenant.tenantName}</p>
      </header>

      {/* Billing banner (trial / past_due / suspended). Above the WhatsApp
          banner because billing is the more urgent state — a paused account
          can't reply to anyone regardless of WhatsApp status. */}
      {showBillingBanner && (
        <BillingBanner
          status={billing.status}
          daysLeft={billing.days_left}
        />
      )}

      {/* WhatsApp not connected banner */}
      {!isConnected && (
        <div className="flex items-center justify-between rounded-xl border border-amber-200 bg-amber-50 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-100">
              <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4 text-amber-600">
                <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-amber-800">WhatsApp não conectado</p>
              <p className="text-xs text-amber-600">Conecte seu número para começar a receber mensagens.</p>
            </div>
          </div>
          <Link
            href={`/${tenant.tenantSlug}/integrations`}
            className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700"
          >
            Conectar agora
          </Link>
        </div>
      )}

      {/* Metric cards */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <MetricCard
          label="Conversas ativas"
          value={String(metrics.activeConvs)}
          icon={
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5 text-brand-500">
              <path d="M3.505 2.365A41.369 41.369 0 019 2c1.863 0 3.697.124 5.495.365 1.247.167 2.173 1.08 2.435 2.21A4.486 4.486 0 0015 9c0 .73-.119 1.433-.337 2.089l-5.13 5.13a.5.5 0 01-.707 0l-4.95-4.95a.5.5 0 010-.707V5.09c0-.96.647-1.81 1.63-1.933z" />
            </svg>
          }
        />
        <MetricCard
          label="Mensagens respondidas"
          value={String(metrics.repliedMsgs)}
          icon={
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5 text-emerald-500">
              <path d="M3.505 2.365A41.369 41.369 0 019 2c1.863 0 3.697.124 5.495.365 1.247.167 2.173 1.08 2.435 2.21A4.486 4.486 0 0015 9c0 .73-.119 1.433-.337 2.089l-1.516 1.515a4.5 4.5 0 01-6.364-6.364L8 2.941V2.94l-.007-.004-.006-.003z" />
            </svg>
          }
        />
        <MetricCard
          label="Agendamentos (24h)"
          value={String(metrics.appointments)}
          icon={
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5 text-violet-500">
              <path fillRule="evenodd" d="M5.75 2a.75.75 0 01.75.75V4h7V2.75a.75.75 0 011.5 0V4h.25A2.75 2.75 0 0118 6.75v8.5A2.75 2.75 0 0115.25 18H4.75A2.75 2.75 0 012 15.25v-8.5A2.75 2.75 0 014.75 4H5V2.75A.75.75 0 015.75 2zm-1 5.5c-.69 0-1.25.56-1.25 1.25v6.5c0 .69.56 1.25 1.25 1.25h10.5c.69 0 1.25-.56 1.25-1.25v-6.5c0-.69-.56-1.25-1.25-1.25H4.75z" clipRule="evenodd" />
            </svg>
          }
        />
      </section>

      {/* Recent conversations */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">Conversas recentes</h2>
          <Link href={`/${tenant.tenantSlug}/conversations`} className="text-xs text-brand-600 hover:underline">
            Ver todas →
          </Link>
        </div>

        {recentConvs.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 py-10 text-center">
            <p className="text-sm text-slate-500">Nenhuma conversa ainda.</p>
            <p className="mt-1 text-xs text-slate-400">
              Quando o WhatsApp estiver conectado, as conversas aparecerão aqui.
            </p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            {recentConvs.map((c, i) => (
              <div
                key={c.id}
                className={`flex items-center justify-between px-4 py-3 ${i < recentConvs.length - 1 ? "border-b border-slate-100" : ""}`}
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-xs font-medium text-slate-600">
                    {(c.contact_name ?? c.contact_phone).charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-slate-900">
                      {c.contact_name ?? c.contact_phone}
                    </p>
                    <p className="text-xs text-slate-400">{c.contact_phone}</p>
                  </div>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                  c.status === "active" ? "bg-emerald-100 text-emerald-700" :
                  c.status === "handoff" ? "bg-amber-100 text-amber-700" :
                  "bg-slate-100 text-slate-600"
                }`}>
                  {c.status === "active" ? "Ativo" : c.status === "handoff" ? "Aguardando" : "Encerrado"}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function BillingBanner({
  status,
  daysLeft,
}: {
  status: string;
  daysLeft: number | null;
}) {
  // Style and copy are derived from status so we have one component for
  // every non-active state and no chance of UI drift between cases.
  const isExpired = status === "trialing" && (daysLeft ?? 0) <= 0;
  const isSuspended = status === "suspended";
  const isPastDue = status === "past_due";
  const isTrialing = status === "trialing" && !isExpired;

  const palette = isExpired || isSuspended
    ? { border: "border-red-200", bg: "bg-red-50", icon: "bg-red-100", iconTxt: "text-red-600", title: "text-red-800", body: "text-red-600" }
    : isPastDue
      ? { border: "border-orange-200", bg: "bg-orange-50", icon: "bg-orange-100", iconTxt: "text-orange-600", title: "text-orange-800", body: "text-orange-600" }
      : { border: "border-blue-200", bg: "bg-blue-50", icon: "bg-blue-100", iconTxt: "text-blue-600", title: "text-blue-800", body: "text-blue-600" };

  const title = isExpired
    ? "Período de teste encerrado"
    : isSuspended
      ? "Assinatura pausada"
      : isPastDue
        ? "Pagamento em atraso"
        : `Período de teste — ${daysLeft} ${daysLeft === 1 ? "dia restante" : "dias restantes"}`;

  const subtitle = isExpired
    ? "O atendimento automático foi pausado. Entre em contato para reativar."
    : isSuspended
      ? "O agente parou de responder os seus clientes. Regularize para retomar."
      : isPastDue
        ? "Seu agente continua respondendo, mas o pagamento pendente precisa ser regularizado em breve."
        : "Após o término, será necessário ativar a assinatura para continuar respondendo seus clientes.";

  return (
    <div className={`flex items-center justify-between rounded-xl border ${palette.border} ${palette.bg} px-5 py-4`}>
      <div className="flex items-center gap-3">
        <div className={`flex h-8 w-8 items-center justify-center rounded-full ${palette.icon}`}>
          <svg viewBox="0 0 20 20" fill="currentColor" className={`h-4 w-4 ${palette.iconTxt}`}>
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
          </svg>
        </div>
        <div>
          <p className={`text-sm font-medium ${palette.title}`}>{title}</p>
          <p className={`text-xs ${palette.body}`}>{subtitle}</p>
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-5">
      <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-50">
        {icon}
      </div>
      <div>
        <p className="text-xs text-slate-500">{label}</p>
        <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
      </div>
    </div>
  );
}
