"""Administrative CLI for the KBMTI license service.

Examples:
    python -m license_server.cli init --key-out .local/license/signing-key.pem
    python -m license_server.cli seed-legacy
    python -m license_server.cli issue --role USER --days 365
    python -m license_server.cli revoke --license-id lic-...
    python -m license_server.cli reset-device --license-id lic-...
    python -m license_server.cli serve --port 8790
"""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kbmti.licensing.tokens import public_key_b64

from .db import DB_PATH, connect, ensure_schema, issue_license, seed_legacy, utc_now
from .seed_legacy import LEGACY_LICENSES


def _open(db: str) -> object:
    connection = connect(db)
    ensure_schema(connection)
    return connection


def init_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing signing key: {path}")
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(raw)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print(f"Signing key written to {path}")
    print("Pinned public key (put this in kbmti/licensing/trusted_public_key.txt):")
    print(public_key_b64(key))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m license_server.cli")
    parser.add_argument("--db", default=os.environ.get("KBMTI_LICENSE_DB", str(DB_PATH)))
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="generate an Ed25519 signing key")
    p_init.add_argument("--key-out", type=Path, required=True)

    sub.add_parser("seed-legacy", help="import the original x.bat credential hashes")

    p_issue = sub.add_parser("issue", help="issue a new access key")
    p_issue.add_argument("--role", choices=["DEVELOPER", "USER", "ADMIN"], required=True)
    p_issue.add_argument("--days", type=int, default=None, help="validity in days; omit for no expiry")
    p_issue.add_argument("--devices", type=int, default=1)
    p_issue.add_argument("--note", default="")

    p_revoke = sub.add_parser("revoke", help="revoke a license")
    p_revoke.add_argument("--license-id", required=True)

    p_reset = sub.add_parser("reset-device", help="remove all device bindings for a license")
    p_reset.add_argument("--license-id", required=True)

    sub.add_parser("list", help="list licenses without secrets")

    p_serve = sub.add_parser("serve", help="run the license service")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8790)
    p_serve.add_argument("--signing-key", default=os.environ.get("KBMTI_LICENSE_SIGNING_KEY", ""))

    args = parser.parse_args(argv)

    if args.command == "init":
        init_key(args.key_out)
        return 0
    if args.command == "serve":
        if not args.signing_key:
            raise SystemExit("--signing-key or KBMTI_LICENSE_SIGNING_KEY is required")
        os.environ["KBMTI_LICENSE_DB"] = args.db
        os.environ["KBMTI_LICENSE_SIGNING_KEY"] = args.signing_key
        import uvicorn

        uvicorn.run("license_server.app:create_app", factory=True, host=args.host, port=args.port, log_level="info")
        return 0

    connection = _open(args.db)
    try:
        if args.command == "seed-legacy":
            print(f"Imported {seed_legacy(connection, LEGACY_LICENSES)} legacy license(s).")
        elif args.command == "issue":
            password = None
            if args.role == "ADMIN":
                password = getpass.getpass("Admin password for the new license: ")
                if len(password) < 8:
                    raise SystemExit("Admin password must be at least 8 characters.")
            license_id, key = issue_license(
                connection,
                role=args.role,
                days=args.days,
                max_devices=args.devices,
                note=args.note,
                admin_password=password,
            )
            print(f"license_id: {license_id}")
            print(f"access_key: {key}")
            print("Store the access key now. Only its salted hash is retained.")
        elif args.command == "revoke":
            connection.execute(
                "UPDATE licenses SET status = 'revoked', revoked_at = ? WHERE id = ?",
                (utc_now().isoformat(), args.license_id),
            )
            connection.commit()
            print(f"Revoked {args.license_id}.")
        elif args.command == "reset-device":
            connection.execute("DELETE FROM devices WHERE license_id = ?", (args.license_id,))
            connection.commit()
            print(f"Cleared device bindings for {args.license_id}.")
        elif args.command == "list":
            for row in connection.execute(
                "SELECT id, role, status, expires_at, max_devices, note FROM licenses ORDER BY created_at"
            ).fetchall():
                devices = connection.execute(
                    "SELECT COUNT(*) AS n FROM devices WHERE license_id = ?", (row["id"],)
                ).fetchone()["n"]
                print(
                    f"{row['id']:24} {row['role']:10} {row['status']:8} "
                    f"devices={devices}/{row['max_devices']} expires={row['expires_at'] or 'never'} {row['note'] or ''}"
                )
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
