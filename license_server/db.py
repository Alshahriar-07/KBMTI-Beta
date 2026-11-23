"""SQLite schema and credential helpers for the KBMTI license service."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "data" / "licenses.db"
ROLES = {"DEVELOPER", "USER", "ADMIN"}
PBKDF2_ITERATIONS = 310_000
KEY_ALPHABET = string.ascii_uppercase + string.digits


class LicenseDenied(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int = 401) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def hash_secret(secret: str, salt: str, *, algo: str = "sha256", iterations: int = PBKDF2_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac(algo, secret.encode("utf-8"), salt.encode("utf-8"), iterations, 32).hex()


def verify_secret(
    secret: str,
    *,
    salt: str,
    expected: str,
    algo: str,
    iterations: int,
) -> bool:
    try:
        got = hash_secret(secret, salt, algo=algo, iterations=iterations)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


def new_key(role: str) -> str:
    # Preserve the existing KBMTI-XXXXX-0000 format.
    body = "".join(secrets.choice(KEY_ALPHABET) for _ in range(5))
    tail = "".join(secrets.choice(string.digits) for _ in range(4))
    return f"KBMTI-{body}-{tail}"


def key_lookup(role: str, key: str) -> str:
    return hashlib.sha256(f"{role}\x00{key}".encode()).hexdigest()


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path or DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS licenses (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            key_lookup TEXT,
            key_salt TEXT NOT NULL,
            key_hash TEXT NOT NULL,
            key_algo TEXT NOT NULL,
            key_iterations INTEGER NOT NULL,
            admin_salt TEXT,
            admin_hash TEXT,
            admin_algo TEXT,
            admin_iterations INTEGER,
            status TEXT NOT NULL DEFAULT 'active',
            expires_at TEXT,
            max_devices INTEGER NOT NULL DEFAULT 1,
            note TEXT,
            created_at TEXT NOT NULL,
            revoked_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_licenses_lookup ON licenses(key_lookup);
        CREATE TABLE IF NOT EXISTS devices (
            license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
            device_hash TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            PRIMARY KEY (license_id, device_hash)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            jti TEXT PRIMARY KEY,
            sid TEXT NOT NULL,
            license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
            audience TEXT NOT NULL,
            device_hash TEXT NOT NULL,
            nonce TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_sid ON sessions(sid);
        CREATE TABLE IF NOT EXISTS auth_failures (
            scope TEXT PRIMARY KEY,
            failures INTEGER NOT NULL,
            lock_until TEXT
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            event TEXT NOT NULL,
            license_id TEXT,
            detail TEXT
        );
        """
    )
    connection.commit()


def audit(connection: sqlite3.Connection, event: str, license_id: str | None = None, detail: str = "") -> None:
    connection.execute(
        "INSERT INTO audit (at, event, license_id, detail) VALUES (?, ?, ?, ?)",
        (iso(utc_now()), event, license_id, detail[:500]),
    )
    connection.commit()


def seed_legacy(connection: sqlite3.Connection, licenses: tuple[dict[str, Any], ...]) -> int:
    added = 0
    now = iso(utc_now())
    for item in licenses:
        exists = connection.execute("SELECT 1 FROM licenses WHERE id = ?", (item["id"],)).fetchone()
        if exists:
            continue
        connection.execute(
            """
            INSERT INTO licenses (
                id, role, key_lookup, key_salt, key_hash, key_algo, key_iterations,
                admin_salt, admin_hash, admin_algo, admin_iterations,
                status, expires_at, max_devices, note, created_at
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, 1, ?, ?)
            """,
            (
                item["id"],
                item["role"],
                item["key_salt"],
                item["key_hash"],
                item["key_algo"],
                item["key_iterations"],
                item["admin_salt"],
                item["admin_hash"],
                item["admin_algo"],
                item["admin_iterations"],
                item["note"],
                now,
            ),
        )
        added += 1
    connection.commit()
    return added


def issue_license(
    connection: sqlite3.Connection,
    *,
    role: str,
    days: int | None,
    max_devices: int = 1,
    note: str = "",
    admin_password: str | None = None,
) -> tuple[str, str]:
    role = role.upper()
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}")
    key = new_key(role)
    key_salt = secrets.token_hex(16)
    key_hash = hash_secret(key, key_salt)
    admin_salt = admin_hash = admin_algo = admin_iterations = None
    if role == "ADMIN":
        admin_salt = secrets.token_hex(16)
        if not admin_password:
            raise ValueError("administrator licenses require an admin password")
        admin_hash = hash_secret(admin_password, admin_salt)
        admin_algo = "sha256"
        admin_iterations = PBKDF2_ITERATIONS
    license_id = f"lic-{secrets.token_hex(8)}"
    expires = iso(utc_now() + timedelta(days=days)) if days else None
    connection.execute(
        """
        INSERT INTO licenses (
            id, role, key_lookup, key_salt, key_hash, key_algo, key_iterations,
            admin_salt, admin_hash, admin_algo, admin_iterations,
            status, expires_at, max_devices, note, created_at
        ) VALUES (?, ?, ?, ?, ?, 'sha256', ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        """,
        (
            license_id,
            role,
            key_lookup(role, key),
            key_salt,
            key_hash,
            PBKDF2_ITERATIONS,
            admin_salt,
            admin_hash,
            admin_algo,
            admin_iterations,
            expires,
            max(1, int(max_devices)),
            note,
            iso(utc_now()),
        ),
    )
    connection.commit()
    audit(connection, "license.issued", license_id, f"role={role} expires={expires}")
    return license_id, key
