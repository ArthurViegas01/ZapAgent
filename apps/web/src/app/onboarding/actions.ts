"use server";

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export interface CreateTenantState {
  error: string;
  slug?: string;
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[aáâãäå]/g, "a")
    .replace(/[eéêë]/g, "e")
    .replace(/[iíîï]/g, "i")
    .replace(/[oóôõö]/g, "o")
    .replace(/[uúûü]/g, "u")
    .replace(/[c]/g, "c")
    .replace(/[n]/g, "n")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

export async function createTenant(
  _prev: CreateTenantState | null,
  formData: FormData,
): Promise<CreateTenantState> {
  const name = ((formData.get("name") as string) ?? "").trim();
  const customSlug = ((formData.get("slug") as string) ?? "").trim();
  const businessType = ((formData.get("business_type") as string) ?? "").trim();

  if (!name) return { error: "Nome da empresa e obrigatorio." };

  const slug = customSlug || slugify(name);
  if (!/^[a-z0-9-]{2,48}$/.test(slug)) {
    return { error: "Slug invalido. Use apenas letras minusculas, numeros e hifens." };
  }

  const cookieStore = cookies();

  const userClient = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll: (toSet) => {
          try {
            toSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {}
        },
      },
    }
  );

  const {
    data: { user },
  } = await userClient.auth.getUser();
  if (!user) return { error: "Sessao expirada. Faca login novamente." };

  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!serviceKey)
    return { error: "Configuracao do servidor incompleta (service key)." };

  const serviceClient = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    serviceKey,
    { cookies: { getAll: () => [], setAll: () => {} } }
  );

  const { data: tenant, error: tenantErr } = await serviceClient
    .from("tenants")
    .insert({ name, slug, business_type: businessType || null })
    .select("id, slug")
    .single();

  if (tenantErr) {
    if (tenantErr.code === "23505")
      return { error: "Esse slug ja esta em uso. Tente outro nome." };
    return { error: "Erro ao criar empresa: " + tenantErr.message };
  }

  const { error: userErr } = await serviceClient.from("users").insert({
    tenant_id: tenant.id,
    auth_user_id: user.id,
    email: user.email ?? "",
    role: "owner",
  });

  if (userErr)
    return { error: "Erro ao vincular usuario: " + userErr.message };

  // Return slug so the client can navigate — do NOT call redirect() here
  return { error: "", slug: tenant.slug };
}
