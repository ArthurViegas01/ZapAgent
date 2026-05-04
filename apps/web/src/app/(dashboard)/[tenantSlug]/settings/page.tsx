import { requireTenant } from "@/lib/tenant";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";
import SettingsClient from "./SettingsClient";

export default async function SettingsPage({
  params,
}: {
  params: { tenantSlug: string };
}) {
  const tenant = await requireTenant(params.tenantSlug);
  const supabase = createServiceClient();

  const { data: row } = await supabase
    .from("tenants")
    .select("name, settings")
    .eq("id", tenant.tenantId)
    .single();

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Configurações</h1>
        <p className="text-sm text-slate-500">
          Personalize o comportamento do agente e dados da empresa.
        </p>
      </header>
      <SettingsClient
        tenantSlug={params.tenantSlug}
        tenantName={row?.name ?? tenant.tenantName}
        settings={row?.settings ?? {}}
      />
    </div>
  );
}
