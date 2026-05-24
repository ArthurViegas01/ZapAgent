"""Integration tests — require a real PostgreSQL with pgvector.

Run with:
    pytest -m integration

Skipped if DATABASE_URL_SYNC is not reachable, so the suite stays
runnable on a laptop without docker-compose up.
"""
