"""End-to-end smoke test against a deployed Encaixe stack.

Run AFTER `terraform apply` (Railway) and Netlify deploy succeed.
Does NOT need ANY repo dependency beyond Python 3.10+ stdlib.

What it checks (in order — stops at the first failure):

  1. ``GET <API_URL>/health``  → process alive.
  2. ``GET <API_URL>/ready``   → DB pool + WhatsApp provider resolvable.
  3. ``HEAD <WEB_URL>/``       → Netlify served the dashboard.
  4. ``HEAD <WEB_URL>/login``  → Next.js route handler responding.
  5. (optional) ``GET <API_URL>/api/v1/tenants/<tid>/billing`` with a
     Bearer JWT — proves the subscription gate is reachable end-to-end
     for the pilot tenant. Skipped if --jwt and --tenant-id not given.

Usage::

    python scripts/smoke_test_prod.py \\
        --api-url   https://zapagent-api-xxx.up.railway.app \\
        --web-url   https://zapagent.netlify.app \\
        [--jwt $SUPABASE_JWT --tenant-id <uuid>]

Exit codes::

    0 — all checks passed
    1 — a required check failed (CI-friendly: pipe into `set -e`)
    2 — usage error
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> tuple[int, str]:
    """Tiny HTTP helper — stdlib only, returns (status, body)."""
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body
    except urllib.error.URLError as exc:
        return 0, f"URLError: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return 0, f"unhandled: {type(exc).__name__}: {exc}"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str

    def render(self) -> str:
        mark = "PASS" if self.ok else "FAIL"
        return f"  [{mark}] {self.name}\n         {self.detail}"


def _check(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=ok, detail=detail)


def check_api_health(api_url: str) -> CheckResult:
    status, body = _request("GET", f"{api_url.rstrip('/')}/health")
    if status == 200 and '"ok"' in body:
        return _check("API /health", True, f"200 OK body={body.strip()[:120]}")
    return _check("API /health", False, f"status={status} body={body[:200]}")


def check_api_ready(api_url: str) -> CheckResult:
    """Ready endpoint reports DB pool + WhatsApp provider state.

    Accepts ``status in {ready, degraded}`` because degraded still serves
    traffic; we only hard-fail on a non-2xx or a response missing keys.
    """
    status, body = _request("GET", f"{api_url.rstrip('/')}/ready")
    if status != 200:
        return _check("API /ready", False, f"status={status} body={body[:200]}")
    try:
        payload: dict[str, Any] = json.loads(body)
    except json.JSONDecodeError:
        return _check("API /ready", False, f"non-JSON body: {body[:200]}")
    required = {"status", "db", "whatsapp_provider"}
    missing = required - payload.keys()
    if missing:
        return _check("API /ready", False, f"missing keys: {sorted(missing)}")
    detail = (
        f"status={payload['status']} db={payload['db']} "
        f"provider={payload['whatsapp_provider']}"
    )
    ok = bool(payload["db"]) and bool(payload["whatsapp_provider"])
    return _check("API /ready", ok, detail)


def check_web_root(web_url: str) -> CheckResult:
    status, _ = _request("HEAD", f"{web_url.rstrip('/')}/")
    return _check("WEB /", status in (200, 301, 302), f"status={status}")


def check_web_login(web_url: str) -> CheckResult:
    status, _ = _request("HEAD", f"{web_url.rstrip('/')}/login")
    return _check("WEB /login", status in (200, 301, 302), f"status={status}")


def check_api_billing(api_url: str, jwt: str, tenant_id: str) -> CheckResult:
    """Proves the subscription gate is reachable for the pilot tenant.

    Runs only if --jwt + --tenant-id are supplied; otherwise the runner
    prints a SKIP line (some smoke runs happen before any tenant exists).
    """
    url = f"{api_url.rstrip('/')}/api/v1/tenants/{tenant_id}/billing"
    status, body = _request(
        "GET", url, headers={"Authorization": f"Bearer {jwt}"}
    )
    if status != 200:
        return _check("API /billing", False, f"status={status} body={body[:200]}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _check("API /billing", False, f"non-JSON body: {body[:200]}")
    if "status" not in payload or "allowed" not in payload:
        return _check("API /billing", False, f"bad shape: {payload}")
    return _check(
        "API /billing",
        True,
        f"status={payload['status']} allowed={payload['allowed']} "
        f"days_left={payload.get('days_left')}",
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--api-url", required=True,
                   help="https://zapagent-api-xxx.up.railway.app")
    p.add_argument("--web-url", required=True,
                   help="https://zapagent.netlify.app")
    p.add_argument("--jwt", help="Supabase JWT for the billing check (optional)")
    p.add_argument("--tenant-id",
                   help="UUID of the tenant for the billing check (optional)")
    args = p.parse_args()

    checks: list[CheckResult] = [
        check_api_health(args.api_url),
        check_api_ready(args.api_url),
        check_web_root(args.web_url),
        check_web_login(args.web_url),
    ]

    if args.jwt and args.tenant_id:
        checks.append(check_api_billing(args.api_url, args.jwt, args.tenant_id))
    else:
        print("  [SKIP] API /billing  (pass --jwt + --tenant-id to enable)")

    print()
    print("== Smoke test results ==")
    for c in checks:
        print(c.render())
    print()

    failures = [c for c in checks if not c.ok]
    if failures:
        print(f"FAILED: {len(failures)} of {len(checks)} checks")
        return 1
    print(f"OK: all {len(checks)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
