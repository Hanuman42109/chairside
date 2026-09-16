import hashlib
import hmac

from app.config import get_settings
from app.routes.webhook import verify_signature


def test_verify_signature_accepts_everything_when_no_secret_configured():
    get_settings.cache_clear()
    assert verify_signature(b"any body", None) is True


def test_verify_signature_rejects_missing_header_when_secret_configured(monkeypatch):
    monkeypatch.setenv("RETELL_WEBHOOK_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        assert verify_signature(b"body", None) is False
    finally:
        get_settings.cache_clear()


def test_verify_signature_accepts_valid_hmac(monkeypatch):
    monkeypatch.setenv("RETELL_WEBHOOK_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        body = b'{"event": "call_started"}'
        signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        assert verify_signature(body, signature) is True
        assert verify_signature(body, "wrong-signature") is False
    finally:
        get_settings.cache_clear()
