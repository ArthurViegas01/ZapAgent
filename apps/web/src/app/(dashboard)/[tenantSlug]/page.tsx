import { requireTenant } from "@/lib/tenant";

export default async function TenantOverviewPage({
  params,
}: {
  params: { tenantSlug: string };
}) {
  const tenant = await requireTenant(params.tenantSlug);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Visão geral</h1>
        <p className="text-sm text-slate-600">
          Resumo do que aconteceu com o seu atendente nas últimas 24 horas.
        </p>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <MetricCard label="Conversas ativas" value="—" />
        <MetricCard label="Mensagens respondidas" value="—" />
        <MetricCard label="Agendamentos criados" value="—" />
      </section>

      <p className="text-xs text-slate-500">
        Tenant id <code>{tenant.tenantId}</code> · papel{" "}
        <code>{tenant.role}</code>
      </p>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  );
}
