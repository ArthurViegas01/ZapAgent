"""Normalize Evolution API QR payloads (connect response + qrcode.updated webhook).

Evolution v2 often returns only ``code`` / ``pairingCode`` / ``count`` from
``GET /instance/connect/{name}`` while ``state == connecting``; ``base64`` may
be absent. We flatten nested ``{"qrcode": {...}}`` and, when needed, render a
PNG data URL from ``code`` (Baileys ref string) for the dashboard <img src>.
"""

from __future__ import annotations

import base64
import io
from typing import Any

import qrcode

from src.core.logging import get_logger

_logger = get_logger(__name__)


def _flatten_qr_fields(data: dict[str, Any]) -> dict[str, Any]:
    merged = dict(data)
    inner = merged.get("qrcode")
    if isinstance(inner, dict):
        for key, val in inner.items():
            if val is not None and val != "":
                merged[key] = val
    return merged


def evolution_qr_diagnose(data: dict[str, Any] | None) -> dict[str, Any]:
    """Safe metadata for logs (no secrets, no QR / ref contents)."""
    if not isinstance(data, dict):
        return {"shape": "non_dict", "type": type(data).__name__}
    if not data:
        return {"shape": "empty_dict"}
    flat = _flatten_qr_fields(data)
    code = flat.get("code")
    b64 = flat.get("base64")
    pairing = flat.get("pairingCode")
    return {
        "shape": "dict",
        "top_keys": sorted(data.keys()),
        "flat_keys": sorted(flat.keys()),
        "has_code": isinstance(code, str) and bool(code.strip()),
        "code_len": len(code.strip()) if isinstance(code, str) else 0,
        "has_base64": isinstance(b64, str) and bool(b64.strip()),
        "base64_len": len(b64.strip()) if isinstance(b64, str) else 0,
        "has_pairing_code": isinstance(pairing, str) and bool(pairing.strip()),
        "pairing_len": len(pairing.strip()) if isinstance(pairing, str) else 0,
        "count": flat.get("count"),
    }


def evolution_qr_to_data_url(data: dict[str, Any] | None) -> str:
    """Return a value suitable for ``<img src>`` (data URL), or ``\"\"``."""
    if not data:
        _logger.info("evolution_qr.result", source="none", reason="empty_payload")
        return ""
    flat = _flatten_qr_fields(data)

    b64 = flat.get("base64")
    if isinstance(b64, str) and b64.strip():
        s = b64.strip()
        out = s if s.startswith("data:") else f"data:image/png;base64,{s}"
        _logger.info(
            "evolution_qr.result",
            source="base64_field",
            out_len=len(out),
        )
        return out

    code = flat.get("code")
    if not (isinstance(code, str) and code.strip()):
        _logger.info(
            "evolution_qr.result",
            source="none",
            reason="no_base64_no_code",
            flat_keys=sorted(flat.keys()),
        )
        return ""

    buf = io.BytesIO()
    qr = qrcode.QRCode(version=None, box_size=6, border=2)
    qr.add_data(code.strip())
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(buf, format="PNG")
    raw_b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    out = f"data:image/png;base64,{raw_b64}"
    _logger.info(
        "evolution_qr.result",
        source="rendered_from_code",
        out_len=len(out),
        code_len=len(code.strip()),
    )
    return out
