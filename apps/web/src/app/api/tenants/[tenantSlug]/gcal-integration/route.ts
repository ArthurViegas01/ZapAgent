import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";

export async function GET(
  _req: NextRequest,
  { params }: { params: { tenantSlug: string } },
) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

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
    .select("status, external_id")
    .eq("tenant_id", tenant.id)
    .eq("kind", "google_calendar")
    .neq("status", "revoked")
    .order("created_at", { ascending: false })
    .limit(1)
    .single();

  if (!integration) return NextResponse.json({ status: "revoked", email: null });

  const email = integration.external_id?.includes("@") ? integration.external_id : null;
  return NextResponse.json({ status: integration.status, email });
}
