"""Compact Ed25519-signed tokens used by the KBMTI launcher and backend.

Format: ``v1.<base64url(payload-json)>.<base64url(signature)>``

The token is deliberately not a general-purpose JWT: only the fields listed in
``REQUIRED_CLAIMS`` are accepted, and both audience and device binding are
checked by the caller. The server's private key is the only way to mint a valid
token. The client contains only the public key.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

TOKEN_VERSION = "v1"
TOKEN_PREFIX = f"{TOKEN_VERSION}."
ISSUER = "kbmti-license-service"
REQUIRED_CLAIMS = {
    "v",
    "iss",
    "aud",
    "jti",
    "sid",
    "sub",
    "role",
    "device",
    "nonce",
    "iat",
    "exp",
}
MAX_TOKEN_LENGTH = 4096
PUBLIC_KEY_PATH = Path(__file__).with_name("trusted_public_key.txt")


class TokenError(ValueError):
    """A token is malformed, forged, expired or addressed to another component."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def load_public_key_text(text: str) -> Ed25519PublicKey:
    text = text.strip()
    if not text:
        raise TokenError("TRUST_ANCHOR_MISSING", "The pinned license public key is empty.")
    try:
        raw = _b64d(text)
    except ValueError as exc:
        raise TokenError("TRUST_ANCHOR_INVALID", "The pinned license public key is not valid base64.") from exc
    if len(raw) != 32:
        raise TokenError("TRUST_ANCHOR_INVALID", "The pinned license public key must be 32 bytes.")
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise TokenError("TRUST_ANCHOR_INVALID", "The pinned license public key is not Ed25519.") from exc


def load_trusted_public_key() -> Ed25519PublicKey:
    try:
        text = PUBLIC_KEY_PATH.read_text(encoding="ascii")
    except OSError as exc:
        raise TokenError(
            "TRUST_ANCHOR_MISSING",
            f"The pinned license public key was not found at {PUBLIC_KEY_PATH}.",
        ) from exc
    return load_public_key_text(text)


def load_signing_key(path: str | Path) -> Ed25519PrivateKey:
    """Load a private key from a raw-base64 file or a PEM file.

    The server is the only component that calls this. The application never
    reads or embeds this file.
    """

    raw = Path(path).read_bytes()
    if b"BEGIN" in raw:
        try:
            key = serialization.load_pem_private_key(raw, password=None)
        except (ValueError, TypeError) as exc:
            raise TokenError("SIGNING_KEY_INVALID", "The license signing key is not a valid PEM key.") from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise TokenError("SIGNING_KEY_INVALID", "The license signing key must be Ed25519.")
        return key
    try:
        decoded = _b64d(raw.decode("ascii").strip())
    except (ValueError, UnicodeDecodeError) as exc:
        raise TokenError("SIGNING_KEY_INVALID", "The license signing key is not valid base64.") from exc
    if len(decoded) != 32:
        raise TokenError("SIGNING_KEY_INVALID", "The raw Ed25519 signing key must be 32 bytes.")
    return Ed25519PrivateKey.from_private_bytes(decoded)


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _b64e(raw)


def sign_token(payload: dict[str, Any], private_key: Ed25519PrivateKey) -> str:
    missing = REQUIRED_CLAIMS.difference(payload)
    if missing:
        raise TokenError("TOKEN_INCOMPLETE", f"Refusing to sign an incomplete token: {sorted(missing)}")
    encoded = _b64e(canonical_json(payload))
    signed = f"{TOKEN_PREFIX}{encoded}".encode("ascii")
    signature = private_key.sign(signed)
    return f"{TOKEN_PREFIX}{encoded}.{_b64e(signature)}"


def verify_token(
    token: str,
    public_key: Ed25519PublicKey,
    *,
    audience: str,
    now: float | None = None,
    leeway_seconds: float = 5.0,
) -> dict[str, Any]:
    """Verify a token's signature, claims, audience and lifetime.

    Callers must still verify ``device`` against the local device identity and
    ask the license service to consume the one-time token. This function proves
    only that the token was minted by the trusted signing key and is currently
    valid for the requested component.
    """

    if not token or len(token) > MAX_TOKEN_LENGTH:
        raise TokenError("TOKEN_MALFORMED", "The launch token is missing or too large.")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        raise TokenError("TOKEN_MALFORMED", "The launch token has an unsupported format.")
    try:
        payload_raw = _b64d(parts[1])
        signature = _b64d(parts[2])
    except (ValueError, UnicodeEncodeError) as exc:
        raise TokenError("TOKEN_MALFORMED", "The launch token encoding is invalid.") from exc
    try:
        public_key.verify(signature, f"{TOKEN_VERSION}.{parts[1]}".encode("ascii"))
    except InvalidSignature as exc:
        raise TokenError("TOKEN_SIGNATURE_INVALID", "The launch token signature is invalid.") from exc
    try:
        payload = json.loads(payload_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenError("TOKEN_MALFORMED", "The launch token payload is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise TokenError("TOKEN_MALFORMED", "The launch token payload must be an object.")
    missing = REQUIRED_CLAIMS.difference(payload)
    if missing:
        raise TokenError("TOKEN_INCOMPLETE", f"The launch token is missing claims: {sorted(missing)}")
    if payload.get("v") != 1:
        raise TokenError("TOKEN_VERSION_UNSUPPORTED", "The launch token version is not supported.")
    if payload.get("iss") != ISSUER:
        raise TokenError("TOKEN_ISSUER_INVALID", "The launch token issuer is not KBMTI.")
    if payload.get("aud") != audience:
        raise TokenError("TOKEN_AUDIENCE_INVALID", "The launch token is for a different component.")
    current = time.time() if now is None else now
    try:
        issued = float(payload["iat"])
        expires = float(payload["exp"])
        not_before = float(payload.get("nbf", issued))
    except (TypeError, ValueError) as exc:
        raise TokenError("TOKEN_TIME_INVALID", "The launch token times are invalid.") from exc
    if issued > current + leeway_seconds or not_before > current + leeway_seconds:
        raise TokenError("TOKEN_NOT_YET_VALID", "The launch token is not valid yet.")
    if expires <= current - leeway_seconds:
        raise TokenError("TOKEN_EXPIRED", "The launch token has expired.")
    if expires <= issued:
        raise TokenError("TOKEN_TIME_INVALID", "The launch token expires before it was issued.")
    for claim in ("jti", "sid", "sub", "role", "device", "nonce"):
        value = payload.get(claim)
        if not isinstance(value, str) or not value or len(value) > 256:
            raise TokenError("TOKEN_CLAIM_INVALID", f"The launch token claim '{claim}' is invalid.")
    return payload
