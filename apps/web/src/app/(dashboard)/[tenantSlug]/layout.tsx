import Link from "next/link";

import { requireTenant } from "@/lib/tenant";

export default async function TenantLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { tenantSlug: string };
}) {
  const tenant = await requireTenant(params.tenantSlug);

  const navItems = [
    { href: `/${tenant.tenantSlug}`, label: "Visão geral" },
    { href: `/${tenant.tenantSlug}/conversations`, label: "Conversas" },
    { href: `/${tenant.tenantSlug}/faq`, label: "FAQ" },
    { href: `/${tenant.tenantSlug}/integrations`, label: "Integrações" },
    { href: `/${tenant.tenantSlug}/settings`, label: "Configurações" },
  ];

  return (
    <div className="grid min-h-screen grid-cols-[16rem_1fr]">
      <aside className="border-r border-slate-200 bg-white px-4 py-6">
        <p className="px-2 pb-6 text-sm font-semibold uppercase tracking-wider text-slate-500">
          {tenant.tenantName}
        </p>
        <nav className="flex flex-col gap-1">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-md px-2 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <section className="px-8 py-6">{children}</section>
    </div>
  );
}
