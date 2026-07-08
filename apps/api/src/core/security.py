"""Shared security primitives: JWT verification and secret encryption.

Both the auth dependency and the rate-limit middleware need to turn a bearer
token into *verified* claims. Centralizing it here guarantees a single,
fail-closed verification path (ZAP-002 / ZAP-008): claims are only ever
returned after the signature and expiry are checked. There is no
"unverified claims" escape hatch.
"""

from __future__ import annotations

import base64
import hashlib
import os

from .config import get_settings


def verify_supabase_jwt_local(token: str) -> dict | None:
    """Verify a Supabase HS256 access token locally.

    Returns the validated claims dict, or None when the token cannot be
    trusted (bad signature, expired, missing required claims) or when no
    local secret is configured. It never returns unverified claims.
    """
    settings = get_settings()
    secret = settings.supabase_jwt_secret
    if not secret:
        return None
    try:
        from jose import jwt

        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Secret encryption (ZAP-006)
# ---------------------------------------------------------------------------
#
# Integration secrets (OAuth access/refresh tokens) are encrypted at the
# application layer before hitting Postgres. Format is AES-256-GCM with a
# 12-byte nonce prepended to the ciphertext+tag, base64-encoded. The exact
# same layout is produced by the Next.js side (node:crypto), so a token
# written by either runtime is readable by the other.
#
# The key is derived as SHA-256(APP_ENCRYPTION_KEY) so any sufficiently random
# env string works and both runtimes derive the identical 32-byte key.


def encryption_configured() -> bool:
    return bool(get_settings().app_encryption_key)


def _load_key() -> bytes:
    raw = get_settings().app_encryption_key
    if not raw:
        raise RuntimeError("APP_ENCRYPTION_KEY is not configured")
    return hashlib.sha256(raw.encode()).digest()


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a UTF-8 string, returning base64(nonce | ciphertext | tag)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ct = AESGCM(_load_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_secret(blob: str) -> str:
    """Decrypt a base64(nonce | ciphertext | tag) blob back to a string."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    data = base64.b64decode(blob)
    nonce, ct = data[:12], data[12:]
    return AESGCM(_load_key()).decrypt(nonce, ct, None).decode()
