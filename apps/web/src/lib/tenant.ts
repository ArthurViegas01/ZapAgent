/**
 * Tenant resolution helpers used by Server Components and Route Handlers.
 *
 * Every dashboard page lives under `/[tenantSlug]/...`. We resolve the slug
 * to a tenant row, then verify that the authenticated user is a member.
 */
import { redirect } from "next/navigation";

import { createClient } from "./supabase/server";

export interface TenantContext {
  tenantId: string;
  tenantSlug: string;
  tenantName: string;
  userId: string;
  role: "owner" | "admin" | "agent" | "viewer";
}

export async function requireTenant(slug: string): Promise<TenantContext> {
  const supabase = createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  const { data: tenant, error: tenantErr } = await supabase
    .from("tenants")
    .select("id, slug, name")
    .eq("slug", slug)
    .single();

  if (tenantErr || !tenant) {
    redirect("/tenants");
  }

  const { data: membership, error: memberErr } = await supabase
    .from("users")
    .select("role")
    .eq("auth_user_id", user.id)
    .eq("tenant_id", tenant.id)
    .single();

  if (memberErr || !membership) {
    redirect("/tenants");
  }

  return {
    tenantId: tenant.id,
    tenantSlug: tenant.slug,
    tenantName: tenant.name,
    userId: user.id,
    role: membership.role,
  };
}
