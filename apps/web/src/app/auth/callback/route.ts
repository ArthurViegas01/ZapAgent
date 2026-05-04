/**
 * Auth callback route — exchanges the PKCE code from Supabase for a session.
 *
 * Supabase redirects here after magic-link verification:
 *   /auth/callback?code=<pkce_code>&next=/tenants
 *
 * We exchange the code for a session (sets the auth cookie) and then
 * redirect the user to their intended destination.
 */
import { NextResponse, type NextRequest } from "next/server";

import { createClient } from "@/lib/supabase/server";

export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/tenants";

  if (code) {
    const supabase = createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  // Exchange failed or no code — send back to login with an error.
  return NextResponse.redirect(
    `${origin}/login?error=auth_callback_failed&next=${encodeURIComponent(next)}`,
  );
}
