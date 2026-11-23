# KBMTI-RAW-TEST — Official Launcher & Licensing Context

> **Purpose:** authoritative context for `KBMTI-RAW-TEST.exe`, `x.bat`, the
> authenticated Python runtime, and the server-side KBMTI license service.

## 1. Source-of-truth relationship

- **Official user-facing executable:** `KBMTI-RAW-TEST.exe`
- **Editable launcher source:** `x.bat`
- **EXE source:** `launcher/KBMTILauncher.cs`
- **Build script:** `launcher/build.ps1`
- **Authenticated Python gateway:** `kbmti/launch.py`
- **License service:** `license_server/`
- **Application runtime:** `kbmti/runtime.py`

`KBMTI-RAW-TEST.exe` is a small .NET Framework launcher. It verifies that
`x.bat` matches the SHA-256 embedded at build time, then runs `x.bat` in the
installation directory. `x.bat` is the human-readable authentication and boot UI.

The EXE does **not** contain the Python application or the license signing key.
Changing `x.bat` requires rebuilding the EXE, because the EXE rejects a batch file
whose hash does not match its build-time value.

## 2. Mandatory entry point

| Invocation | Result |
|---|---|
| `KBMTI-RAW-TEST.exe` | Official authenticated launch |
| `python -m kbmti` | Redirects to `KBMTI-RAW-TEST.exe`; never starts the app |
| `python -m kbmti.launch --role ...` | Authenticated gateway only |
| `python -m kbmti.runtime` | Blocked unless a valid signed backend ticket exists |
| `python -m app` | Blocked unless the launcher supplies a valid signed backend ticket |
| Direct internal scripts | Not an application launch path |

Importing `kbmti` does not initialize Qt, the backend, the frontend, or the
license client.

## 3. Authentication and license flow

1. User launches `KBMTI-RAW-TEST.exe`.
2. `x.bat` presents Developer, User, Administrator, or Exit.
3. `x.bat` calls `python -m kbmti.launch --role ...`.
4. The launcher prompts for the key (and admin password for Administrator) with immediate `*` masking. Every accepted character appears as one star; Backspace removes one star; arrow/function keys are ignored; the credential is never echoed.
5. The launcher sends the key to `KBMTI_LICENSE_SERVER_URL` over HTTPS.
6. The license service verifies the salted key hash, license status, expiry,
   revocation, role, and device binding.
7. The service returns three Ed25519-signed tokens:
   - `launcher_token` — one-time, consumed before startup;
   - `backend_token` — one-time, consumed by the FastAPI startup gate;
   - `renewal_token` — device-bound, used only to issue a fresh backend ticket
     when the desktop retry action restarts the backend.
8. The launcher verifies signatures with the pinned public key, consumes the
   launcher ticket, and starts `kbmti.runtime`.
9. The runtime verifies the backend ticket before importing Qt.
10. The FastAPI backend verifies and consumes a fresh backend ticket before
    market data, PATRON, or Qwen can start.
11. Only after all checks does the native window open.

`KBMTI_ROLE` is display metadata only. It is not authorization. Fake environment
variables, hand-written role values, modified tokens and replayed tickets fail.

## 4. Access keys and licensing

- Existing key format is preserved: `KBMTI-XXXXX-0000`.
- Developer, User, and Administrator roles are supported.
- Administrator login requires the admin key **and** a separate admin password.
- The original `x.bat` PBKDF2-SHA1 hashes are imported into the license database,
  so existing credentials continue to work. The documented user key
  `KBMTI-USRMP-1304` was verified against the original hash.
- New keys use PBKDF2-HMAC-SHA-256 with a random salt and 310,000 iterations.
- Keys can expire, be revoked, and be bound to a limited number of devices.
- A second unauthorized device receives `DEVICE_LIMIT`.
- The signing private key exists only on the license service. The client ships
  only the public key.
- A modified local license record has no effect: there is no trusted local
  license file. Authorization is server state plus a signed token.

The server's private key is the security boundary. Possession of the Python
source does not provide that key. A determined attacker with the complete source
and executable can still patch the local code; no local check is unbreakable.
The enforceable control is that the **license service will not issue a token**
without a valid, active, device-bound license.

## 5. Runtime layout

```text
KBMTI application folder/
├── KBMTI-RAW-TEST.exe
├── x.bat
├── .env                      # KBMTI_LICENSE_SERVER_URL
├── launcher/
│   ├── KBMTILauncher.cs
│   └── build.ps1
├── kbmti/
│   ├── __main__.py           # redirects to EXE
│   ├── launch.py             # authenticated gateway
│   ├── runtime.py            # licensed internal runtime
│   └── licensing/            # client, gate, pinned public key
├── license_server/           # separate server-side service
└── backend/
    ├── .venv/
    └── app/
```

## 6. Configuration

```env
# Production: HTTPS only. Plain HTTP is accepted only for loopback development.
KBMTI_LICENSE_SERVER_URL=https://license.example.com
```

The pinned public key is `kbmti/licensing/trusted_public_key.txt`. Replacing it
requires rebuilding the application because it is the trust anchor.

Local development only:

```env
KBMTI_LICENSE_SERVER_URL=http://127.0.0.1:8790
```

## 7. Build the EXE

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File launcher/build.ps1
```

Requirements: Windows PowerShell and the .NET Framework 4.x C# compiler
(`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`). The build script writes
the current `x.bat` SHA-256 into `launcher/LauncherIntegrity.cs` and compiles the
EXE. The generated integrity file is rebuild output; do not hand-edit it.

## 8. License service setup

```bash
python -m license_server.cli init --key-out /secure/kbmti-signing.pem
# Copy the printed public key into kbmti/licensing/trusted_public_key.txt.
python -m license_server.cli seed-legacy
python -m license_server.cli issue --role USER --days 365
python -m license_server.cli serve --host 0.0.0.0 --port 8790 \
  --signing-key /secure/kbmti-signing.pem
```

Run the service behind an HTTPS reverse proxy. Never commit the signing key or
the license database. See `license_server/README.md` for administration,
revocation, device reset, and deployment guidance.

## 9. Honest security limitations

- Source code and the executable are distributed. Local enforcement can be
  patched by a determined attacker; the server-side signature is the practical
  boundary.
- The EXE is not Authenticode-signed in this repository. Code signing is
  recommended before public distribution; without a trusted certificate,
  Windows SmartScreen may warn.
- The EXE's `x.bat` hash check detects accidental tampering, not a modified EXE
  rebuilt by someone with source access.
- The local device identifier is not a hardware TPM attestation. It binds a
  license to a generated device ID; deleting it does not bypass the server's
  existing binding.
- The license service's SQLite database and signing key must be protected with
  filesystem permissions, backups, and HTTPS.
- No destructive anti-debugging, file deletion, or system modification is used.

## 10. Verification commands

```bash
# Launcher source self-test (no application start)
cmd /c "x.bat /selftest"
cmd /c "KBMTI-RAW-TEST.exe /selftest"

# Python redirect must reach the EXE, not the app
cmd /c "backend\.venv\Scripts\python.exe -m kbmti /selftest"

# Direct startup must be refused
backend/.venv/Scripts/python.exe -m app
backend/.venv/Scripts/python.exe -m kbmti.runtime --headless

# License and launch tests
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_license_enforcement.py -q
```

See `docs/AUTHENTICATION_AND_LICENSING.md` and
`docs/SECURITY_TEST_REPORT_EXE_ONLY.md` for the full architecture and test report.
