"""Evolution QR payload normalization."""

from src.core.evolution_qr import evolution_qr_diagnose, evolution_qr_to_data_url


def test_evolution_qr_to_data_url_from_nested_base64() -> None:
    url = evolution_qr_to_data_url({"qrcode": {"base64": "AAA"}})
    assert url == "data:image/png;base64,AAA"


def test_evolution_qr_to_data_url_preserves_data_prefix() -> None:
    raw = "data:image/png;base64,BBBB"
    assert evolution_qr_to_data_url({"base64": raw}) == raw


def test_evolution_qr_to_data_url_from_baileys_code_only() -> None:
    url = evolution_qr_to_data_url({"code": "2@test-ref-string-for-qr", "count": 1})
    assert url.startswith("data:image/png;base64,")
    assert len(url) > 80


def test_evolution_qr_diagnose_nested() -> None:
    d = evolution_qr_diagnose({"qrcode": {"base64": "x", "code": "2@a"}})
    assert d["has_base64"] is True
    assert d["has_code"] is True
