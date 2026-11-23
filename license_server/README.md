# KBMTI License Service

This is the server-side authorization boundary for KBMTI. It verifies access
keys, license state, expiry, revocation and device binding, then mints
short-lived Ed25519 launch tickets. The desktop client contains only the matching
public key.

## Install

```bash
python -m pip install -r license_server/requirements.txt
# The client and backend also need cryptography:
python -m pip install -r backend/requirements-desktop.txt
```

## Generate the trust anchor

Run this once on the server:

```bash
python -m license_server.cli init --key-out /secure/kbmti-signing.pem
```

The command prints the public key. Put that value in
`kbmti/licensing/trusted_public_key.txt` in the client build and rebuild the EXE
and application. Keep the private key off the client machine.

## Seed existing credentials and issue new keys

```bash
python -m license_server.cli --db /secure/licenses.db seed-legacy
python -m license_server.cli --db /secure/licenses.db issue --role USER --days 365
python -m license_server.cli --db /secure/licenses.db issue --role DEVELOPER --days 365
python -m license_server.cli --db /secure/licenses.db issue --role ADMIN --days 365
```

The administrator issue command prompts for the second-factor password. The
access key is printed once; only its salted PBKDF2 hash is stored.

Administration:

```bash
python -m license_server.cli list
python -m license_server.cli revoke --license-id lic-...
python -m license_server.cli reset-device --license-id lic-...
```

Device reset allows the license to be activated on a replacement machine. It
does not change the access key.

## Run

```bash
KBMTI_LICENSE_SIGNING_KEY=/secure/kbmti-signing.pem \
KBMTI_LICENSE_DB=/secure/licenses.db \
  python -m license_server.cli serve --host 0.0.0.0 --port 8790 \
  --signing-key /secure/kbmti-signing.pem
```

Run it behind an HTTPS reverse proxy (Caddy, nginx, or a managed platform).
The client refuses plain HTTP for any non-loopback host. Do not expose the SQLite
file or signing key over the network.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/health` | Service health |
| `POST` | `/v1/auth/login` | Verify role/key/password, bind device, issue three signed tickets |
| `POST` | `/v1/session/consume` | One-time consumption of launcher or backend ticket |
| `POST` | `/v1/session/renew` | Device-bound renewal of a backend ticket for Retry |

All failures return:

```json
{"error": {"code": "LICENSE_EXPIRED", "message": "This KBMTI license has expired."}}
```

## Schema and state

SQLite tables:

- `licenses` — role, salted key hash, admin hash, status, expiry, device limit.
- `devices` — bound device hashes and timestamps.
- `sessions` — one-time ticket IDs, audiences, nonces and consumption state.
- `auth_failures` — short IP lockout after repeated failures.
- `audit` — issue, login, consumption and renewal events.

## Security limits

- This service is only as secure as its signing key and database. Use filesystem
  permissions, encrypted backups, least-privilege service accounts and HTTPS.
- Rate limiting is a simple in-process/IP database lockout, not a substitute for
  an edge WAF or distributed rate limiter.
- The client's device identifier is generated locally, not TPM-attested.
- Source distribution means a determined attacker can patch the local client.
  The license service's refusal to sign a valid ticket is the real boundary.
- No destructive anti-debugging or machine modification is implemented.
