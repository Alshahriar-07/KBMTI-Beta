"""KBMTI license verification service.

Run behind HTTPS in production, for example:

    KBMTI_LICENSE_SIGNING_KEY=/secure/kbmti-signing.pem \
      uvicorn license_server.app:create_app --factory --host 0.0.0.0 --port 8790

The service is the authorization boundary: it verifies access keys, license
state, expiry, revocation and device binding, then mints short-lived Ed25519
launch tickets. The desktop application contains only the matching public key.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from kbmti.licensing.tokens import (
    ISSUER,
    TokenError,
    load_signing_key,
    public_key_b64,
    sign_token,
    verify_token,
)

from .db import (
    ROLES,
    LicenseDenied,
    audit,
    connect,
    ensure_schema,
    iso,
    parse_iso,
    seed_legacy,
    utc_now,
    verify_secret,
)
from .seed_legacy import LEGACY_LICENSES

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "licenses.db"
LAUNCHER_TTL = 120
BACKEND_TTL = 300
RENEWAL_TTL = 86_400
MAX_FAILURES = 5
LOCK_SECONDS = 30
DEVICE_ID_MIN = 32
DEVICE_MAX = 256


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=4, max_length=20)
    key: str = Field(min_length=8, max_length=64)
    admin_password: str | None = Field(default=None, max_length=128)
    device_id: str = Field(min_length=DEVICE_ID_MIN, max_length=DEVICE_MAX)
    nonce: str = Field(min_length=32, max_length=128)
    client_version: str = Field(default="1.2.0", max_length=32)


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=4096)
    audience: str = Field(pattern="^(launcher|backend)$")
    device_id: str = Field(min_length=DEVICE_ID_MIN, max_length=DEVICE_MAX)


class RenewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=4096)
    device_id: str = Field(min_length=DEVICE_ID_MIN, max_length=DEVICE_MAX)
    nonce: str = Field(min_length=32, max_length=128)


def _normalize_key(value: str) -> str:
    """Accept lowercase, mixed-case, spaces and missing separators on the server.

    The launcher already formats keys, but validating the canonical form here means a
    direct client, an older launcher, or a pasted compact key behaves identically.
    """

    key = re.sub(r"\s+", "", str(value or "")).upper()
    compact = key.replace("-", "")
    if compact.startswith("KBMTI") and len(compact) == 14:
        body = compact[5:]
        return f"KBMTI-{body[:5]}-{body[5:]}"
    if "-" not in key and len(compact) == 9:
        return f"KBMTI-{compact[:5]}-{compact[5:]}"
    return key


def _device_hash(device_id: str) -> str:
    import hashlib

    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def _error(code: str, message: str, status: int = 401) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _license_state(connection: sqlite3.Connection, license_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
    if row is None:
        raise LicenseDenied("LICENSE_NOT_FOUND", "The KBMTI license was not found.")
    if row["status"] != "active":
        raise LicenseDenied("LICENSE_REVOKED", "This KBMTI license has been revoked.", status=403)
    expires = parse_iso(row["expires_at"])
    if expires is not None and expires <= utc_now():
        raise LicenseDenied("LICENSE_EXPIRED", "This KBMTI license has expired.", status=403)
    return row


def _check_lock(connection: sqlite3.Connection, scope: str) -> None:
    row = connection.execute("SELECT * FROM auth_failures WHERE scope = ?", (scope,)).fetchone()
    lock_until = parse_iso(row["lock_until"]) if row else None
    if lock_until is not None and lock_until > utc_now():
        seconds = max(1, int((lock_until - utc_now()).total_seconds()))
        raise LicenseDenied(
            "AUTH_LOCKED",
            f"Too many failed attempts. Try again in {seconds} seconds.",
            status=429,
        )


def _record_failure(connection: sqlite3.Connection, scope: str) -> None:
    now = utc_now()
    row = connection.execute("SELECT * FROM auth_failures WHERE scope = ?", (scope,)).fetchone()
    failures = (row["failures"] if row else 0) + 1
    lock_until = iso(now + timedelta(seconds=LOCK_SECONDS)) if failures >= MAX_FAILURES else None
    connection.execute(
        """
        INSERT INTO auth_failures (scope, failures, lock_until) VALUES (?, ?, ?)
        ON CONFLICT(scope) DO UPDATE SET failures = excluded.failures, lock_until = excluded.lock_until
        """,
        (scope, failures, lock_until),
    )
    connection.commit()


def _clear_failures(connection: sqlite3.Connection, scope: str) -> None:
    connection.execute("DELETE FROM auth_failures WHERE scope = ?", (scope,))
    connection.commit()


def _find_license(connection: sqlite3.Connection, role: str, key: str) -> sqlite3.Row | None:
    from .db import key_lookup

    lookup = key_lookup(role, key)
    row = connection.execute(
        "SELECT * FROM licenses WHERE role = ? AND key_lookup = ?",
        (role, lookup),
    ).fetchone()
    if row is not None:
        return row
    # Legacy rows were imported as PBKDF2 hashes before a lookup index existed.
    for candidate in connection.execute(
        "SELECT * FROM licenses WHERE role = ? AND key_lookup IS NULL AND status = 'active'",
        (role,),
    ).fetchall():
        if verify_secret(
            key,
            salt=candidate["key_salt"],
            expected=candidate["key_hash"],
            algo=candidate["key_algo"],
            iterations=candidate["key_iterations"],
        ):
            return candidate
    return None


def _bind_device(connection: sqlite3.Connection, license_row: sqlite3.Row, device_hash: str) -> None:
    now = iso(utc_now())
    existing = connection.execute(
        "SELECT 1 FROM devices WHERE license_id = ? AND device_hash = ?",
        (license_row["id"], device_hash),
    ).fetchone()
    if existing:
        connection.execute(
            "UPDATE devices SET last_seen = ? WHERE license_id = ? AND device_hash = ?",
            (now, license_row["id"], device_hash),
        )
        connection.commit()
        return
    count = connection.execute(
        "SELECT COUNT(*) AS n FROM devices WHERE license_id = ?",
        (license_row["id"],),
    ).fetchone()["n"]
    if count >= int(license_row["max_devices"]):
        raise LicenseDenied(
            "DEVICE_LIMIT",
            "This KBMTI license is already active on its allowed device. Contact KBMTI to reset it.",
            status=403,
        )
    connection.execute(
        "INSERT INTO devices (license_id, device_hash, first_seen, last_seen) VALUES (?, ?, ?, ?)",
        (license_row["id"], device_hash, now, now),
    )
    connection.commit()


def _claims(
    *,
    audience: str,
    jti: str,
    sid: str,
    license_id: str,
    role: str,
    device_hash: str,
    nonce: str,
    ttl: int,
) -> dict[str, Any]:
    now = int(time.time())
    return {
        "v": 1,
        "iss": ISSUER,
        "aud": audience,
        "jti": jti,
        "sid": sid,
        "sub": license_id,
        "role": role,
        "device": device_hash,
        "nonce": nonce,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
    }


def _store_session(connection: sqlite3.Connection, claims: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO sessions (jti, sid, license_id, audience, device_hash, nonce, issued_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            claims["jti"],
            claims["sid"],
            claims["sub"],
            claims["aud"],
            claims["device"],
            claims["nonce"],
            iso(datetime.fromtimestamp(claims["iat"], UTC)),
            iso(datetime.fromtimestamp(claims["exp"], UTC)),
        ),
    )
    connection.commit()


def create_app(
    *,
    db_path: str | Path | None = None,
    signing_key_path: str | Path | None = None,
    seed: bool = True,
) -> FastAPI:
    db = Path(db_path or os.environ.get("KBMTI_LICENSE_DB", DEFAULT_DB))
    key_path = signing_key_path or os.environ.get("KBMTI_LICENSE_SIGNING_KEY", "").strip()
    if not key_path:
        raise RuntimeError("KBMTI_LICENSE_SIGNING_KEY must point to the Ed25519 private key.")
    private_key = load_signing_key(key_path)
    public_key = private_key.public_key()
    connection = connect(db)
    ensure_schema(connection)
    if seed:
        seed_legacy(connection, LEGACY_LICENSES)

    application = FastAPI(title="KBMTI License Service", version="1.0.0", docs_url=None, redoc_url=None)
    db_lock = threading.RLock()
    application.state.db_path = db
    application.state.public_key_b64 = public_key_b64(private_key)

    @application.exception_handler(LicenseDenied)
    async def denied_handler(request: Request, exc: LicenseDenied) -> JSONResponse:
        return _error(exc.code, exc.message, exc.status)

    @application.exception_handler(TokenError)
    async def token_error_handler(request: Request, exc: TokenError) -> JSONResponse:
        return _error(exc.code, "The launch token is invalid or expired.", 401)

    @application.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "kbmti-license", "version": "1.0.0"}

    @application.post("/v1/auth/login")
    def login(body: LoginRequest, request: Request) -> dict[str, Any]:
        # PBKDF2 is intentionally slow; this synchronous endpoint runs in
        # FastAPI's worker thread, not the event loop.
        role = body.role.upper().strip()
        if role not in ROLES:
            raise LicenseDenied("ROLE_INVALID", "Unknown KBMTI role.", status=400)
        ip = request.client.host if request.client else "unknown"
        scope = f"ip:{ip}"
        key = _normalize_key(body.key)
        admin_password = (body.admin_password or "").strip() or None
        with db_lock:
            _check_lock(connection, scope)
            license_row = _find_license(connection, role, key)
            if license_row is None:
                _record_failure(connection, scope)
                raise LicenseDenied("CREDENTIALS_INVALID", "The KBMTI access key is invalid.")
            try:
                _license_state(connection, license_row["id"])
            except LicenseDenied:
                _record_failure(connection, scope)
                raise
            if role == "ADMIN":
                if not admin_password or not license_row["admin_hash"]:
                    _record_failure(connection, scope)
                    raise LicenseDenied("ADMIN_PASSWORD_REQUIRED", "Administrator password is required.")
                if not verify_secret(
                    admin_password,
                    salt=license_row["admin_salt"],
                    expected=license_row["admin_hash"],
                    algo=license_row["admin_algo"],
                    iterations=license_row["admin_iterations"],
                ):
                    _record_failure(connection, scope)
                    raise LicenseDenied("CREDENTIALS_INVALID", "The administrator credentials are invalid.")
            device_hash = _device_hash(body.device_id)
            _bind_device(connection, license_row, device_hash)
            _clear_failures(connection, scope)

            sid = uuid.uuid4().hex
            expires = parse_iso(license_row["expires_at"])
            renewal_ttl = RENEWAL_TTL
            if expires is not None:
                renewal_ttl = max(60, min(renewal_ttl, int((expires - utc_now()).total_seconds())))
            launcher_claims = _claims(
                audience="launcher",
                jti=uuid.uuid4().hex,
                sid=sid,
                license_id=license_row["id"],
                role=license_row["role"],
                device_hash=device_hash,
                nonce=body.nonce,
                ttl=LAUNCHER_TTL,
            )
            backend_claims = _claims(
                audience="backend",
                jti=uuid.uuid4().hex,
                sid=sid,
                license_id=license_row["id"],
                role=license_row["role"],
                device_hash=device_hash,
                nonce=body.nonce,
                ttl=BACKEND_TTL,
            )
            renewal_claims = _claims(
                audience="renew",
                jti=uuid.uuid4().hex,
                sid=sid,
                license_id=license_row["id"],
                role=license_row["role"],
                device_hash=device_hash,
                nonce=body.nonce,
                ttl=renewal_ttl,
            )
            for claims in (launcher_claims, backend_claims, renewal_claims):
                _store_session(connection, claims)
            audit(connection, "auth.success", license_row["id"], f"role={role} device={device_hash[:12]}")
            return {
                "role": license_row["role"],
                "license_id": license_row["id"],
                "launcher_token": sign_token(launcher_claims, private_key),
                "backend_token": sign_token(backend_claims, private_key),
                "renewal_token": sign_token(renewal_claims, private_key),
                "expires_at": iso(expires) if expires else None,
            }

    @application.post("/v1/session/consume")
    def consume(body: TokenRequest) -> dict[str, Any]:
        with db_lock:
            claims = verify_token(body.token, public_key, audience=body.audience)
            device_hash = _device_hash(body.device_id)
            if claims["device"] != device_hash:
                raise LicenseDenied("DEVICE_MISMATCH", "This launch token belongs to another device.", status=403)
            row = connection.execute("SELECT * FROM sessions WHERE jti = ?", (claims["jti"],)).fetchone()
            if row is None or row["audience"] != body.audience:
                raise LicenseDenied("SESSION_NOT_FOUND", "This launch session is not recognized.")
            if row["consumed_at"]:
                raise LicenseDenied("TOKEN_ALREADY_USED", "This launch token has already been used.", status=409)
            if row["device_hash"] != device_hash:
                raise LicenseDenied("DEVICE_MISMATCH", "This launch token belongs to another device.", status=403)
            _license_state(connection, row["license_id"])
            connection.execute("UPDATE sessions SET consumed_at = ? WHERE jti = ?", (iso(utc_now()), claims["jti"]))
            connection.commit()
            audit(connection, "session.consumed", row["license_id"], f"aud={body.audience} jti={claims['jti'][:12]}")
            return {"ok": True, "role": claims["role"], "license_id": row["license_id"]}

    @application.post("/v1/session/renew")
    def renew(body: RenewRequest) -> dict[str, Any]:
        with db_lock:
            claims = verify_token(body.token, public_key, audience="renew")
            device_hash = _device_hash(body.device_id)
            if claims["device"] != device_hash:
                raise LicenseDenied("DEVICE_MISMATCH", "This renewal token belongs to another device.", status=403)
            row = connection.execute("SELECT * FROM sessions WHERE jti = ?", (claims["jti"],)).fetchone()
            if row is None or row["audience"] != "renew":
                raise LicenseDenied("SESSION_NOT_FOUND", "This renewal session is not recognized.")
            _license_state(connection, row["license_id"])
            backend_claims = _claims(
                audience="backend",
                jti=uuid.uuid4().hex,
                sid=claims["sid"],
                license_id=row["license_id"],
                role=claims["role"],
                device_hash=device_hash,
                nonce=body.nonce,
                ttl=BACKEND_TTL,
            )
            _store_session(connection, backend_claims)
            audit(connection, "session.renewed", row["license_id"], f"sid={claims['sid'][:12]}")
            return {"ok": True, "backend_token": sign_token(backend_claims, private_key)}

    return application
