from retell.lib.webhook_auth import symmetric

from app.config import get_settings
from app.routes.webhook import verify_signature


def test_verify_signature_accepts_everything_when_no_api_key_configured(monkeypatch):
    monkeypatch.setenv("RETELL_API_KEY", "")
    get_settings.cache_clear()
    try:
        assert verify_signature(b"any body", None) is True
    finally:
        get_settings.cache_clear()


def test_verify_signature_rejects_missing_header_when_api_key_configured(monkeypatch):
    monkeypatch.setenv("RETELL_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        assert verify_signature(b"body", None) is False
    finally:
        get_settings.cache_clear()


def test_verify_signature_accepts_valid_hmac_rejects_invalid(monkeypatch):
    monkeypatch.setenv("RETELL_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        body = b'{"event": "call_started"}'
        signature = symmetric["sign"](body.decode("utf-8"), "test-key")
        assert verify_signature(body, signature) is True
        assert verify_signature(body, "v=1,d=" + "0" * 64) is False
    finally:
        get_settings.cache_clear()
