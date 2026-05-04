import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";

export async function GET(
  _req: NextRequest,
  { params }: { params: { tenantSlug: string } },
) {
  // Auth check with user-scoped client
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  // Data lookups with service role (bypasses RLS GUC requirement)
  const service = createServiceClient();

  const { data: tenant } = await service
    .from("tenants")
    .select("id")
    .eq("slug", params.tenantSlug)
    .single();
  if (!tenant) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const { data: membership } = await service
    .from("users")
    .select("role")
    .eq("auth_user_id", user.id)
    .eq("tenant_id", tenant.id)
    .single();
  if (!membership) return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const { data: integration } = await service
    .from("integrations")
    .select("status, external_id, config")
    .eq("tenant_id", tenant.id)
    .eq("kind", "whatsapp")
    .single();

  return NextResponse.json({ integration: integration ?? null, tenantId: tenant.id });
}
