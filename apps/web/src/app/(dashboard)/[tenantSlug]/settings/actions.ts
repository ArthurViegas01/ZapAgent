"use server";

import { revalidatePath } from "next/cache";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export interface SettingsState {
  ok: boolean;
  error: string;
}

function serviceClient() {
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { cookies: { getAll: () => [], setAll: () => {} } }
  );
}

function userClient() {
  const cookieStore = cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll: (toSet) => {
          try { toSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options)); } catch {}
        },
      },
    }
  );
}

async function resolveTenant(slug: string) {
  const sb = userClient();
  const { data: { user } } = await sb.auth.getUser();
  if (!user) return null;

  // Use service client for data lookups to bypass RLS GUC requirement
  const svc = serviceClient();

  const { data: tenant } = await svc
    .from("tenants")
    .select("id")
    .eq("slug", slug)
    .single();
  if (!tenant) return null;

  const { data: membership } = await svc
    .from("users")
    .select("role")
    .eq("auth_user_id", user.id)
    .eq("tenant_id", tenant.id)
    .single();
  if (!membership || !["owner", "admin"].includes(membership.role)) return null;

  return { tenantId: tenant.id as string };
}

export async function updateSettings(
  tenantSlug: string,
  _prev: SettingsState | null,
  formData: FormData
): Promise<SettingsState> {
  const name = (formData.get("name") as string ?? "").trim();
  const persona = (formData.get("persona") as string ?? "").trim();
  const confidenceRaw = formData.get("confidence_threshold") as string;
  const confidence = parseFloat(confidenceRaw);
  const businessHoursOpen = (formData.get("business_hours_open") as string ?? "").trim();
  const businessHoursClose = (formData.get("business_hours_close") as string ?? "").trim();

  if (!name) return { ok: false, error: "Nome da empresa é obrigatório." };
  if (isNaN(confidence) || confidence < 0 || confidence > 1) {
    return { ok: false, error: "Limiar de confiança deve ser entre 0 e 1." };
  }

  const ctx = await resolveTenant(tenantSlug);
  if (!ctx) return { ok: false, error: "Sessão expirada ou sem permissão." };

  const sb = serviceClient();
  const { error } = await sb
    .from("tenants")
    .update({
      name,
      settings: {
        agent_persona: persona,
        confidence_threshold: confidence,
        business_hours: { open: businessHoursOpen, close: businessHoursClose },
      },
    })
    .eq("id", ctx.tenantId);

  if (error) return { ok: false, error: `Erro ao salvar: ${error.message}` };

  revalidatePath(`/${tenantSlug}/settings`);
  return { ok: true, error: "" };
}
