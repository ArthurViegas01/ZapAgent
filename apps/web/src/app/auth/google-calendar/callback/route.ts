import { NextResponse, type NextRequest } from "next/server";

import { createClient } from "../../../../lib/supabase/server";
import { createServiceClient } from "../../../../lib/supabase/service";
import { encryptSecret, encryptionConfigured } from "../../../../lib/crypto";

const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";

export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const stateRaw = searchParams.get("state");
  const errorParam = searchParams.get("error");

  if (errorParam || !code || !stateRaw) {
    return NextResponse.redirect(`${origin}/login?error=gcal_denied`);
  }

  // Decode state (carries the target tenant; membership is verified below).
  let tenantId = "";
  let tenantSlug = "";
  try {
    const decoded = JSON.parse(Buffer.from(stateRaw, "base64url").toString());
    tenantId = decoded.tenantId;
    tenantSlug = decoded.tenantSlug;
  } catch {
    return NextResponse.redirect(`${origin}/login?error=gcal_state_invalid`);
  }

  // ZAP-003: require an authenticated session and verify the user actually
  // belongs to the tenant named in state, BEFORE touching any secrets. Without
  // this, anyone could POST a crafted state and write OAuth tokens into any
  // tenant using the service role.
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.redirect(`${origin}/login?error=gcal_unauthorized`);
  }

  const service = createServiceClient();
  const { data: membership } = await service
    .from("users")
    .select("role")
    .eq("auth_user_id", user.id)
    .eq("tenant_id", tenantId)
    .maybeSingle();
  if (!membership) {
    return NextResponse.redirect(`${origin}/login?error=gcal_forbidden`);
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
  } catch {
    /* ignore */
  }

  // ZAP-006: encrypt secrets at rest when a key is configured. Stored as
  // {"enc": "<blob>"} so the Python read path can tell encrypted from legacy.
  const secretsColumn = encryptionConfigured()
    ? { enc: encryptSecret(JSON.stringify(secrets)) }
    : secrets;

  await service.from("integrations").upsert(
    {
      tenant_id: tenantId,
      kind: "google_calendar",
      external_id: calendarId,
      status: "connected",
      config: {},
      secrets: secretsColumn,
    },
    { onConflict: "tenant_id,kind,external_id" },
  );

  return NextResponse.redirect(`${origin}/${tenantSlug}/integrations?gcal=connected`);
}
