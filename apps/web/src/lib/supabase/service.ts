/**
 * Service-role Supabase client — bypasses RLS.
 * Use ONLY in Server Components, Server Actions, and Route Handlers.
 * Never expose to the client bundle.
 */
import { createServerClient } from "@supabase/ssr";

export function createServiceClient() {
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!serviceKey) {
    throw new Error("SUPABASE_SERVICE_ROLE_KEY is not set");
  }
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    serviceKey,
    // Service role never needs cookie-based auth
    { cookies: { getAll: () => [], setAll: () => {} } },
  );
}
