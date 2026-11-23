# KBMTI Authentication and Licensing

**Status:** implemented and verified
**Official launcher:** `KBMTI-RAW-TEST.exe`
**Server-side service:** `license_server/`

## 1. Security boundary

KBMTI now uses a **server-side license service** as its authorization boundary.
The desktop application contains:

- the Ed25519 **public** key;
- a client that sends keys to the configured license server;
- local launch gates that refuse to start without signed tickets.

It does **not** contain the Ed25519 private signing key. Possessing the Python
source, the EXE, the database schema or documentation does not permit minting a
valid ticket. A determined attacker with the complete source can patch the local
client; no local check is unbreakable. The enforceable control is that the
license service will not issue a ticket without an active, licensed,
device-bound key.

## 2. Launch flow

```text
KBMTI-RAW-TEST.exe
  -> verifies x.bat SHA-256
  -> runs x.bat
     -> Developer / User / Administrator / Exit
     -> python -m kbmti.launch --role ...
        -> prompt for key (+ admin password)
        -> HTTPS POST /v1/auth/login
           -> salted key verification
           -> license status / expiry / revocation
           -> device binding
           -> Ed25519 launcher + backend + renewal tickets
        -> verify signatures with pinned public key
        -> consume launcher ticket (one-time)
        -> python -m kbmti.runtime
           -> verify backend ticket + device binding
           -> start FastAPI backend with a fresh ticket
              -> /v1/session/consume (one-time)
              -> only then market data / PATRON / Qwen
           -> start Vite
           -> open the native window
```

`KBMTI_ROLE` is display metadata. It is not accepted as authorization.

## 3. Token properties

Compact format:

```text
v1.<base64url(canonical JSON payload)>.<base64url(Ed25519 signature)>
```

Required claims include `iss`, `aud`, `jti`, `sid`, `sub`, `role`, `device`,
`nonce`, `iat`, `nbf`, `exp`. The client checks:

- pinned public-key signature;
- issuer and version;
- audience (`launcher`, `backend`, `renew`);
- expiry and not-before;
- device hash;
- nonce binding to the login request.

The server additionally checks the session row, one-time consumption, license
status, expiry and revocation. Backend tickets are single-use. The renewal ticket
is device-bound and only mints fresh backend tickets; it does not start an
application by itself. It exists so the existing Retry action can restart the
backend without a second key prompt.

## 4. Access keys

- Format preserved: `KBMTI-XXXXX-0000`.
- Roles: Developer, User, Administrator.
- Administrator requires a key **and** a separate password.
- Existing `x.bat` PBKDF2-SHA1 hashes were imported into the license database.
  The documented user key `KBMTI-USRMP-1304` was verified to match the original
  hash, but it is not printed or stored in the repository.
- New keys use PBKDF2-HMAC-SHA-256, random salt, 310,000 iterations.
- License fields: status, expiry, revocation timestamp, max devices, device rows.
- A key is bound to a generated local device ID on first activation.
- A second device gets `DEVICE_LIMIT` until an administrator resets bindings.
- Revocation takes effect on the next login or renewal.

## 5. Entry-point protection

`kbmti/__main__.py` never imports the runtime. It locates the official EXE, runs
it with the same arguments, and exits with the EXE status. If the EXE is missing,
it prints the required message and returns 3.

`kbmti/launch.py` is the authenticated gateway. It can be invoked directly, but
it only starts the app after a successful server login; it does not accept a role
flag or environment variable as proof.

`kbmti/runtime.py` verifies the signed backend ticket before importing Qt or
starting services.

`backend/app/__main__.py` and the FastAPI lifespan verify and consume the backend
ticket before market data or models start. Tests construct the app with
`start_polling=False`, which is the existing test-only composition path; they do
not launch a production backend.

`python -m app` without a ticket exits 3 with a clear message. `uvicorn
app.main:create_app` also fails at lifespan if no valid ticket is present.

Importing `kbmti` is side-effect free.

## 6. Configuration

```env
# Production must be HTTPS.
KBMTI_LICENSE_SERVER_URL=https://license.example.com

# Local development only:
# KBMTI_LICENSE_SERVER_URL=http://127.0.0.1:8790
```

The client deliberately rejects plain HTTP for non-loopback hosts. A remote
server URL is not a trust anchor: a fake server cannot sign tokens because it
does not have the pinned private key.

The trust anchor is `kbmti/licensing/trusted_public_key.txt`. Rotating it
requires rebuilding the client. The private key is configured on the server with
`KBMTI_LICENSE_SIGNING_KEY` and must never be shipped.

## 7. Administration

See `license_server/README.md` for:

- signing-key generation;
- importing legacy hashes;
- issuing Developer/User/Admin keys;
- revocation;
- device reset;
- HTTPS deployment.

## 8. Tamper resistance

Implemented:

- pinned Ed25519 trust anchor;
- short-lived, audience-bound, device-bound, one-time tickets;
- server-side revocation and expiry;
- device binding;
- EXE rejects a modified `x.bat` hash;
- no trusted local license file to edit;
- no authorization from `KBMTI_ROLE` or other environment flags;
- generic errors that do not disclose whether a key exists;
- IP-level short lockout after repeated failures;
- audit table.

Not implemented (honestly):

- Authenticode signing (no certificate available in this environment);
- TPM/hardware attestation;
- impossible-to-patch local enforcement;
- destructive anti-debugging or machine modification.

## 9. Verification summary

See `docs/SECURITY_TEST_REPORT_EXE_ONLY.md` for the test table and observed
results, including real Developer/User/Admin launches, invalid/expired/revoked
keys, modified tokens, replay, device binding and direct-start rejection.
