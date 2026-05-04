"use server";

import { revalidatePath } from "next/cache";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export interface FaqState {
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
  if (!membership) return null;

  return { tenantId: tenant.id as string };
}

export async function createFaq(
  tenantSlug: string,
  _prev: FaqState | null,
  formData: FormData,
): Promise<FaqState> {
  const question = (formData.get("question") as string ?? "").trim();
  const answer = (formData.get("answer") as string ?? "").trim();

  if (!question) return { error: "Pergunta é obrigatória." };
  if (!answer) return { error: "Resposta é obrigatória." };

  const ctx = await resolveTenant(tenantSlug);
  if (!ctx) return { error: "Sessão expirada ou sem permissão." };

  const sb = serviceClient();
  const { error } = await sb
    .from("faq_items")
    .insert({ tenant_id: ctx.tenantId, question, answer });

  if (error) return { error: `Erro ao salvar: ${error.message}` };

  revalidatePath(`/${tenantSlug}/faq`);
  return { error: "" };
}

export async function deleteFaq(tenantSlug: string, faqId: string): Promise<void> {
  const ctx = await resolveTenant(tenantSlug);
  if (!ctx) return;

  const sb = serviceClient();
  await sb
    .from("faq_items")
    .delete()
    .eq("id", faqId)
    .eq("tenant_id", ctx.tenantId);

  revalidatePath(`/${tenantSlug}/faq`);
}

export async function toggleFaq(tenantSlug: string, faqId: string, isActive: boolean): Promise<void> {
  const ctx = await resolveTenant(tenantSlug);
  if (!ctx) return;

  const sb = serviceClient();
  await sb
    .from("faq_items")
    .update({ is_active: isActive })
    .eq("id", faqId)
    .eq("tenant_id", ctx.tenantId);

  revalidatePath(`/${tenantSlug}/faq`);
}
