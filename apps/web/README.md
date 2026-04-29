# apps/web

Next.js 14 App Router dashboard. Multi-tenant by URL: `/[tenantSlug]/...`.
Auth comes from Supabase (magic link MVP). Tenant context is enforced by
`requireTenant()` in `src/lib/tenant.ts`, which reads the membership row
from the `users` table.

## Install & run

```bash
pnpm install
pnpm dev      # http://localhost:3000
pnpm build    # production build
pnpm lint     # eslint
pnpm typecheck
```

## Layout

```
src/
├── app/
│   ├── layout.tsx                       # root layout
│   ├── page.tsx                         # marketing landing
│   ├── login/                           # magic-link sign-in
│   ├── tenants/                         # post-login tenant picker
│   └── (dashboard)/[tenantSlug]/        # authenticated, tenant-scoped UI
│       ├── layout.tsx                   # sidebar + nav
│       └── page.tsx                     # overview metrics
├── lib/
│   ├── env.ts                           # zod-validated env access
│   ├── tenant.ts                        # requireTenant() guard
│   └── supabase/{client,server}.ts      # SSR + browser clients
└── middleware.ts                        # cookie refresh + auth gate
```
