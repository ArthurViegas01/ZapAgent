/**
 * Browser-side Supabase client. Used inside `"use client"` components.
 */
import { createBrowserClient } from "@supabase/ssr";

import { publicEnv } from "../env";

export function createClient() {
  return createBrowserClient(
    publicEnv.NEXT_PUBLIC_SUPABASE_URL,
    publicEnv.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  );
}
