/**
 * Tenant resolution helpers used by Server Components and Route Handlers.
 *
 * Every dashboard page lives under /[tenantSlug]/... We resolve the slug
 * to a tenant row, then verify that the authenticated user is a member.
 *
 * NOTE: We use service role for the tenant/membership lookups because the
 * RLS policies require the app.tenant_id GUC which the Supabase JS client
 * does not set. Migration 0002 adds JS-client-friendly policies; service
 * role acts as a belt-and-suspenders fallback.
 */
import { redirect } from "next/navigation";

import { createClient } from "./supabase/server";
import { createServiceClient } from "./supabase/service";

export interface TenantContext {
  tenantId: string;
  tenantSlug: string;
  tenantName: string;
  userId: string;
  role: "owner" | "admin" | "agent" | "viewer";
}

export async function requireTenant(slug: string): Promise<TenantContext> {
  // Auth check — must use the user-scoped client to get the JWT identity.
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  // Tenant + membership lookups — use service role to bypass RLS GUC requirement.
  const service = createServiceClient();

  const { data: tenant } = await service
    .from("tenants")
    .select("id, slug, name")
    .eq("slug", slug)
    .single();

  if (!tenant) redirect("/tenants");

  const { data: membership } = await service
    .from("users")
    .select("role")
    .eq("auth_user_id", user.id)
    .eq("tenant_id", tenant.id)
    .single();

  if (!membership) redirect("/tenants");

  return {
    tenantId: tenant.id,
    tenantSlug: tenant.slug,
    tenantName: tenant.name,
    userId: user.id,
    role: membership.role as TenantContext["role"],
  };
}

/** Returns all tenants the user belongs to (for the /tenants picker page). */
export async function getUserTenants(userId: string) {
  const service = createServiceClient();
  const { data } = await service
    .from("users")
    .select("role, tenant_id, tenants:tenant_id ( id, slug, name )")
    .eq("auth_user_id", userId);
  return (data ?? []) as Array<{
    role: string;
    tenants: { id: string; slug: string; name: string } | null;
  }>;
}
