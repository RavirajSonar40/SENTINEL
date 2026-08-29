"""Cryptographic utilities for webhook secret encryption, decryption, and constant-time HMAC verification."""

import base64
import hashlib
import hmac
import secrets
from typing import Tuple
from cryptography.fernet import Fernet
from app.core.config import Settings

settings = Settings()


def _get_fernet() -> Fernet:
    # Derive a deterministic 32-byte url-safe base64 key from settings.SECRET_KEY
    key = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    url_safe_key = base64.urlsafe_b64encode(key)
    return Fernet(url_safe_key)


def encrypt_secret(plain_text: str) -> str:
    """Encrypt a raw secret string into an encrypted ciphertext."""
    if not plain_text:
        return ""
    fernet = _get_fernet()
    encrypted_bytes = fernet.encrypt(plain_text.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_secret(encrypted_text: str) -> str:
    """Decrypt an encrypted ciphertext back into the raw secret string."""
    if not encrypted_text:
        return ""
    fernet = _get_fernet()
    decrypted_bytes = fernet.decrypt(encrypted_text.encode("utf-8"))
    return decrypted_bytes.decode("utf-8")


def compute_hmac_sha256(payload: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest for payload."""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def generate_hmac_sha256(payload: bytes, secret: str) -> str:
    """Alias for compute_hmac_sha256."""
    return compute_hmac_sha256(payload, secret)


def verify_hmac_sha256(payload: bytes, signature_header: str, secret: str) -> bool:
    """
    Verify HMAC-SHA256 signature against payload in constant time.
    Handles 'sha256=...' prefix if present (e.g. GitHub and standard headers).
    """
    if not signature_header or not secret:
        return False

    expected_sig = signature_header.removeprefix("sha256=").strip()
    computed_mac = compute_hmac_sha256(payload, secret)
    return hmac.compare_digest(computed_mac.lower(), expected_sig.lower())


def generate_webhook_credentials() -> Tuple[str, str]:
    """
    Generate a new pair of (key_id, raw_secret).
    Example key_id: 'whk_3a1b...'
    Example secret: 'whsec_9f82...'
    """
    key_id = f"whk_{secrets.token_hex(16)}"
    raw_secret = f"whsec_{secrets.token_hex(24)}"
    return key_id, raw_secret
