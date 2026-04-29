/**
 * Sanity test for the public env loader. The actual env values come from
 * `process.env` at module load time; here we only assert the schema rejects
 * malformed inputs, since failures at boot would crash the dashboard.
 */
import { describe, expect, it } from "vitest";
import { z } from "zod";

const schema = z.object({
  NEXT_PUBLIC_SUPABASE_URL: z.string().url(),
  NEXT_PUBLIC_SUPABASE_ANON_KEY: z.string().min(1),
  NEXT_PUBLIC_API_URL: z.string().url(),
});

describe("publicEnv schema", () => {
  it("accepts a valid payload", () => {
    expect(() =>
      schema.parse({
        NEXT_PUBLIC_SUPABASE_URL: "https://example.supabase.co",
        NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon-key",
        NEXT_PUBLIC_API_URL: "https://api.zapagent.com.br",
      }),
    ).not.toThrow();
  });

  it("rejects a non-URL", () => {
    expect(() =>
      schema.parse({
        NEXT_PUBLIC_SUPABASE_URL: "not-a-url",
        NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon-key",
        NEXT_PUBLIC_API_URL: "https://api.zapagent.com.br",
      }),
    ).toThrow();
  });
});
