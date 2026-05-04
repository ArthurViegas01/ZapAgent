"use server";

import { revalidatePath } from "next/cache";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
          try { toSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options)); }
          catch {}
        },
      },
    }
  );
}

/** Get Supabase JWT to authenticate with the FastAPI backend */
async function getJwt(): Promise<string | null> {
  const uc = userClient();
  const { data: { session } } = await uc.auth.getSession();
  return session?.access_token ?? null;
}

async function getTenantId(slug: string): Promise<string | null> {
  const sc = serviceClient();
  const { data } = await sc.from("tenants").select("id").eq("slug", slug).single();
  return data?.id ?? null;
}

// ---------------------------------------------------------------------------
// WhatsApp — proxy through FastAPI (has the correct Evolution key)
// ---------------------------------------------------------------------------

const _dev = process.env.NODE_ENV === "development";

export async function createWhatsappInstance(tenantId: string, tenantSlug: string) {
  const jwt = await getJwt();
  if (!jwt) {
    if (_dev) console.warn("[integrations] createWhatsappInstance: no JWT (session missing/expired)");
    return { error: "Sessão expirada. Faça login novamente." };
  }

  const res = await fetch(`${API_URL}/api/v1/tenants/${tenantId}/integrations/whatsapp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${jwt}`,
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "Erro desconhecido");
    if (_dev) console.warn("[integrations] POST /integrations/whatsapp failed", res.status, body.slice(0, 400));
    return { error: `Erro ao conectar WhatsApp: ${body}` };
  }

  const data = await res.json();
  revalidatePath(`/${tenantSlug}/integrations`);
  return { qrcode: data.qrcode ?? "", instanceName: data.instance_name ?? "" };
}

export async function pollWhatsappStatus(tenantId: string): Promise<{ status: string; qrcode?: string; instance_name?: string }> {
  const jwt = await getJwt();
  if (!jwt) {
    if (_dev) console.warn("[integrations] pollWhatsappStatus: no JWT");
    return { status: "error" };
  }

  const res = await fetch(`${API_URL}/api/v1/tenants/${tenantId}/integrations/whatsapp/status`, {
    headers: { Authorization: `Bearer ${jwt}` },
    cache: "no-store",
  });
  if (!res.ok) {
    if (_dev) console.warn("[integrations] GET whatsapp/status failed", res.status);
    return { status: "error" };
  }
  return res.json();
}

export async function disconnectWhatsapp(tenantId: string, tenantSlug: string, _instanceName: string) {
  const jwt = await getJwt();
  if (!jwt) return { error: "Sessão expirada." };

  await fetch(`${API_URL}/api/v1/tenants/${tenantId}/integrations/whatsapp`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${jwt}` },
  });

  revalidatePath(`/${tenantSlug}/integrations`);
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Google Calendar OAuth
// ---------------------------------------------------------------------------

const GCAL_SCOPES = "https://www.googleapis.com/auth/calendar.events";

export async function startGoogleCalendarOAuth(tenantId: string, tenantSlug: string): Promise<{ url: string } | { error: string }> {
  const clientId = process.env.GOOGLE_OAUTH_CLIENT_ID;
  const redirectUri = process.env.GOOGLE_OAUTH_REDIRECT_URI;

  if (!clientId || !redirectUri) {
    return { error: "Google OAuth não configurado no servidor." };
  }

  const uc = userClient();
  const { data: { user } } = await uc.auth.getUser();
  if (!user) return { error: "Sessão expirada." };

  const sc = serviceClient();
  const { data: membership } = await sc.from("users")
    .select("role").eq("auth_user_id", user.id).eq("tenant_id", tenantId).single();
  if (!membership || !["owner", "admin"].includes(membership.role)) {
    return { error: "Permissão insuficiente." };
  }

  const state = Buffer.from(JSON.stringify({ tenantId, tenantSlug })).toString("base64url");
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: "code",
    scope: GCAL_SCOPES,
    access_type: "offline",
    prompt: "consent",
    state,
  });

  return { url: "https://accounts.google.com/o/oauth2/v2/auth?" + params.toString() };
}

export async function disconnectGoogleCalendar(tenantId: string, tenantSlug: string) {
  const uc = userClient();
  const { data: { user } } = await uc.auth.getUser();
  if (!user) return { error: "Sessão expirada." };

  const sc = serviceClient();
  await sc.from("integrations")
    .update({ status: "revoked" })
    .eq("tenant_id", tenantId)
    .eq("kind", "google_calendar");

  revalidatePath(`/${tenantSlug}/integrations`);
  return { ok: true };
}
