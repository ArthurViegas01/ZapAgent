import { requireTenant } from "@/lib/tenant";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";
import FaqClient from "./FaqClient";

export default async function FaqPage({ params }: { params: { tenantSlug: string } }) {
  const tenant = await requireTenant(params.tenantSlug);
  const supabase = createServiceClient();

  const { data: items } = await supabase
    .from("faq_items")
    .select("id, question, answer, is_active, created_at")
    .eq("tenant_id", tenant.tenantId)
    .order("created_at", { ascending: false });

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Base de conhecimento (FAQ)</h1>
        <p className="text-sm text-slate-500">
          Perguntas e respostas que o agente usa para responder seus clientes.
          {(items?.length ?? 0) === 0 && " Adicione pelo menos uma para o agente funcionar."}
        </p>
      </header>
      <FaqClient
        tenantSlug={params.tenantSlug}
        initialItems={items ?? []}
      />
    </div>
  );
}
