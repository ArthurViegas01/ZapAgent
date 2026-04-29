/**
 * Post-login landing: pick a tenant to enter.
 * If the user belongs to a single tenant we redirect straight to it.
 */
import Link from "next/link";
import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";

export default async function TenantsPage() {
  const supabase = createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  const { data: memberships } = await supabase
    .from("users")
    .select("tenant_id, role, tenants:tenant_id ( slug, name )")
    .eq("auth_user_id", user.id);

  const rows = (memberships ?? []) as Array<{
    role: string;
    tenants: { slug: string; name: string } | null;
  }>;

  if (rows.length === 1 && rows[0].tenants) {
    redirect(`/${rows[0].tenants.slug}`);
  }

  if (rows.length === 0) {
    return (
      <main className="mx-auto max-w-md px-6 py-16">
        <h1 className="text-2xl font-semibold">Bem-vindo!</h1>
        <p className="mt-2 text-slate-600">
          Sua conta ainda não está vinculada a nenhuma empresa. Crie a primeira
          para começar.
        </p>
        <Link
          href="/onboarding"
          className="mt-4 inline-block rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white"
        >
          Criar empresa
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <h1 className="text-2xl font-semibold">Escolha uma empresa</h1>
      <ul className="mt-4 flex flex-col gap-2">
        {rows.map(
          (row) =>
            row.tenants && (
              <li key={row.tenants.slug}>
                <Link
                  href={`/${row.tenants.slug}`}
                  className="block rounded-md border border-slate-200 bg-white p-4 hover:border-brand-500"
                >
                  <p className="font-medium">{row.tenants.name}</p>
                  <p className="text-xs text-slate-500">
                    @{row.tenants.slug} · {row.role}
                  </p>
                </Link>
              </li>
            ),
        )}
      </ul>
    </main>
  );
}
