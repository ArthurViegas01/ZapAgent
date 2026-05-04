import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";

export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const stateRaw = searchParams.get("state");
  const errorParam = searchParams.get("error");

  if (errorParam || !code || !stateRaw) {
    return NextResponse.redirect(`${origin}/login?error=gcal_denied`);
  }

  // Decode state
  let tenantId = "";
  let tenantSlug = "";
  try {
    const decoded = JSON.parse(Buffer.from(stateRaw, "base64url").toString());
    tenantId = decoded.tenantId;
    tenantSlug = decoded.tenantSlug;
  } catch {
    return NextResponse.redirect(`${origin}/login?error=gcal_state_invalid`);
  }

  const clientId = process.env.GOOGLE_OAUTH_CLIENT_ID ?? "";
  const clientSecret = process.env.GOOGLE_OAUTH_CLIENT_SECRET ?? "";
  const redirectUri = process.env.GOOGLE_OAUTH_REDIRECT_URI ?? "";

  // Exchange code for tokens
  let tokens: Record<string, unknown>;
  try {
    const res = await fetch(GOOGLE_TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        code,
        client_id: clientId,
        client_secret: clientSecret,
        redirect_uri: redirectUri,
        grant_type: "authorization_code",
      }).toString(),
    });
    if (!res.ok) throw new Error(await res.text());
    tokens = await res.json();
  } catch {
    return NextResponse.redirect(`${origin}/${tenantSlug}/integrations?gcal_error=token_exchange`);
  }

  const nowSecs = Math.floor(Date.now() / 1000);
  const secrets = {
    access_token: tokens.access_token as string,
    refresh_token: (tokens.refresh_token as string) ?? "",
    expires_at: nowSecs + ((tokens.expires_in as number) ?? 3600),
    token_type: (tokens.token_type as string) ?? "Bearer",
  };

  // Fetch primary calendar id
  let calendarId = "primary";
  try {
    const calRes = await fetch("https://www.googleapis.com/calendar/v3/calendars/primary", {
      headers: { Authorization: `Bearer ${secrets.access_token}` },
    });
    if (calRes.ok) {
      const calData = await calRes.json();
      calendarId = calData.id ?? "primary";
    }
  } catch { /* ignore */ }

  // Persist to DB using service role
  const cookieStore = cookies();
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { cookies: { getAll: () => [], setAll: () => {} } }
  );

  await supabase.from("integrations").upsert(
    {
      tenant_id: tenantId,
      kind: "google_calendar",
      external_id: calendarId,
      status: "connected",
      config: {},
      secrets,
    },
    { onConflict: "tenant_id,kind,external_id" }
  );

  void cookieStore; // suppress unused warning

  return NextResponse.redirect(`${origin}/${tenantSlug}/integrations?gcal=connected`);
}
