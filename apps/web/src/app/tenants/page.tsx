/**
 * Post-login landing: pick a tenant or create one.
 * Single tenant -> redirect straight to its dashboard.
 */
import Link from "next/link";
import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";
import { getUserTenants } from "@/lib/tenant";

export default async function TenantsPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  const rows = await getUserTenants(user.id);
  const validRows = rows.filter((r) => r.tenants !== null);

  // Single tenant: go straight to dashboard
  if (validRows.length === 1 && validRows[0].tenants) {
    redirect(`/${validRows[0].tenants.slug}`);
  }

  if (validRows.length === 0) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600">
              <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5 text-white" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
            </div>
            <span className="text-lg font-semibold tracking-tight">ZapAgent</span>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
            <div className="mb-6 flex justify-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-50">
                <svg viewBox="0 0 24 24" fill="none" className="h-8 w-8 text-brand-600" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 21v-7.5a.75.75 0 01.75-.75h3a.75.75 0 01.75.75V21m-4.5 0H2.36m11.14 0H18m0 0h3.64m-1.39 0V9.349m-16.5 11.65V9.35m0 0a3.001 3.001 0 003.75-.615A2.993 2.993 0 009.75 9.75c.896 0 1.7-.393 2.25-1.016a2.993 2.993 0 002.25 1.016c.896 0 1.7-.393 2.25-1.016a3.001 3.001 0 003.75.614m-16.5 0a3.004 3.004 0 01-.621-4.72L4.318 3.44A1.5 1.5 0 015.378 3h13.243a1.5 1.5 0 011.06.44l1.19 1.189a3 3 0 01-.621 4.72m-13.5 8.65h3.75a.75.75 0 00.75-.75V13.5a.75.75 0 00-.75-.75H6.75a.75.75 0 00-.75.75v3.75c0 .415.336.75.75.75z" />
                </svg>
              </div>
            </div>
            <h1 className="text-center text-xl font-semibold text-slate-900">Crie sua empresa</h1>
            <p className="mt-2 text-center text-sm text-slate-500">
              Configure seu atendente de WhatsApp em menos de 2 minutos.
            </p>
            <Link
              href="/onboarding"
              className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-brand-700"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                <path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
              </svg>
              Criar empresa
            </Link>
          </div>

          <p className="mt-4 text-center text-xs text-slate-400">
            Precisa de ajuda?{" "}
            <a href="mailto:suporte@zapagent.com.br" className="underline hover:text-slate-600">
              Fale com a gente
            </a>
          </p>
        </div>
      </main>
    );
  }

  // Multiple tenants: show picker
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600">
            <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5 text-white" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
          </div>
          <span className="text-lg font-semibold tracking-tight">ZapAgent</span>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-semibold text-slate-900">Suas empresas</h1>
          <p className="mt-1 text-sm text-slate-500">Escolha uma para continuar.</p>
          <ul className="mt-4 flex flex-col gap-2">
            {validRows.map((row) =>
              row.tenants ? (
                <li key={row.tenants.slug}>
                  <Link
                    href={`/${row.tenants.slug}`}
                    className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 p-4 transition hover:border-brand-400 hover:bg-brand-50"
                  >
                    <div>
                      <p className="font-medium text-slate-900">{row.tenants.name}</p>
                      <p className="text-xs text-slate-500">@{row.tenants.slug} · {row.role}</p>
                    </div>
                    <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4 text-slate-400">
                      <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
                    </svg>
                  </Link>
                </li>
              ) : null
            )}
          </ul>
          <Link
            href="/onboarding"
            className="mt-4 flex w-full items-center justify-center gap-1 rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 transition hover:bg-slate-50"
          >
            + Adicionar empresa
          </Link>
        </div>
      </div>
    </main>
  );
}
