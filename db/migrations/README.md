# Database migrations

Plain SQL migrations, applied in lexical order.

| File              | Purpose                                            |
|-------------------|----------------------------------------------------|
| `0001_init.sql`   | Initial schema: tenants, users, conversations, messages, faq_items, appointments, integrations, webhook_events. Enables pgvector and RLS. |

## Why SQL and not Alembic?

Supabase favors SQL migrations (its CLI tracks them by filename), and writing
the policies and pgvector index definitions in raw SQL is clearer than going
through SQLAlchemy DDL. We may add Alembic later for runtime model drift, but
the source of truth stays here.

## Local

```bash
make migrate                # via docker-compose
```

## Supabase (staging/prod)

```bash
supabase db push            # from the repo root
```
