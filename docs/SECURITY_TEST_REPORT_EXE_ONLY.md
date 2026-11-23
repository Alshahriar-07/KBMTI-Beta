# KBMTI EXE-Only Launch and Licensing — Security Test Report

**Date:** 2026-11-23
**Platform:** Windows, Python 3.12, AMD RX 580
**Official launcher:** `KBMTI-RAW-TEST.exe`
**License service:** local test instance at `http://127.0.0.1:8790`

## 1. Result summary

| Test | Expected | Observed |
|---|---|---|
| `KBMTI-RAW-TEST.exe /selftest` | Runs the official embedded source | **PASS** — `KBMTI launcher self-test OK` |
| `python -m kbmti /selftest` | Redirects to official EXE, no app init | **PASS** — EXE self-test output, rc 0 |
| Direct `python -m app` without ticket | Blocked | **PASS** — rc 3, explicit launch message |
| Direct `python -m kbmti.runtime --headless` without ticket | Blocked | **PASS** — rc 3 |
| Fake `KBMTI_APP_TOKEN` / `KBMTI_ROLE` | Denied | **PASS** — signature/trust-anchor failure |
| Modified `x.bat` with unchanged EXE | Denied | **PASS** — EXE integrity check rc 2 |
| Invalid access key | Denied | **PASS** — HTTP 401 `CREDENTIALS_INVALID` |
| Expired access key | Denied | **PASS** — HTTP 403 `LICENSE_EXPIRED` |
| Revoked access key | Denied | **PASS** — HTTP 403 `LICENSE_REVOKED` |
| Modified token | Denied | **PASS** — `TOKEN_SIGNATURE_INVALID` |
| Replayed session ticket | Denied | **PASS** — 409 `TOKEN_ALREADY_USED` |
| Second device on one-device license | Denied | **PASS** — 403 `DEVICE_LIMIT` |
| Valid Developer key | Authorized | **PASS** — real headless launch, services ready |
| Valid User key | Authorized | **PASS** — real headless launch, services ready |
| Valid Admin key + password | Authorized | **PASS** — real headless launch, services ready |
| Admin key without password | Denied | **PASS** — `ADMIN_PASSWORD_REQUIRED` |
| Renewal ticket issues a fresh backend ticket | Works | **PASS** — renewed ticket consumed successfully |
| Interactive key masking | Stars appear immediately | **PASS** — 8 and 16 stars captured; no key text |
| Interactive Backspace | Removes one star | **PASS** — 8 stars → 6 stars |
| Interactive admin password masking | Stars appear, no password echo | **PASS** — password prompt captured as stars |

No execution, position sizing or trading state was changed by this work.

Interactive evidence is recorded in `docs/INTERACTIVE_INPUT_MASKING_TEST.md`;
screenshots are under `.local/screenshots/`.

## 2. Reproduction commands

### Launcher integrity

```bash
cmd /c "KBMTI-RAW-TEST.exe /selftest"
cmd /c "backend\.venv\Scripts\python.exe -m kbmti /selftest"
```

Output:

```text
KBMTI launcher self-test OK
```

Tamper check:

```bash
cp KBMTI-RAW-TEST.exe x.bat /tmp/kbmti-tamper/
printf '\r\n:: tampered\r\n' >> /tmp/kbmti-tamper/x.bat
cd /tmp/kbmti-tamper
cmd /c "KBMTI-RAW-TEST.exe /selftest"
# [KBMTI] The launcher source failed its integrity check. Rebuild KBMTI-RAW-TEST.exe.
# exit code 2
```

### Direct startup denial

```text
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m app
# KBMTI backend cannot start: The KBMTI backend cannot start directly.
# Launch KBMTI-RAW-TEST.exe and authenticate.
# exit code 3

backend/.venv/Scripts/python.exe -m kbmti.runtime --headless
# [kbmti] KBMTI must be started through KBMTI-RAW-TEST.exe ...
# exit code 3
```

### Licensed launches

Each command used a fresh device file and a real local license service:

```bash
printf 'KBMTI-<USER-KEY>\n' | \
  KBMTI_LICENSE_SERVER_URL=http://127.0.0.1:8790 \
  backend/.venv/Scripts/python.exe -m kbmti.launch \
  --role USER --key-stdin --headless --timeout 30
```

Observed for USER, DEVELOPER and ADMIN:

```text
[OK] <ROLE> license verified · <license-id>
[kbmti] Backend ready · checking model
[kbmti] Workspace ready
[kbmti] patron: patron-1.0.0 · READY
```

The ADMIN run also required the second password and was denied without it.

### Automated test suite

```text
backend: 322 passed, 2 deselected, 1 warning in 89.04s
license enforcement: 17 passed
ruff: All checks passed
```

The 2 deselected tests are the existing opt-in real-model suites.

## 3. What is actually enforced

- **Server-side authorization:** a valid key, active license, unexpired/unrevoked
  status, admin second factor, and matching device binding are required before
  the service signs a launch ticket.
- **Pinned trust anchor:** the client verifies Ed25519 signatures with the
  public key in `kbmti/licensing/trusted_public_key.txt`. A fake local server
  cannot mint a valid ticket without the private key.
- **One-time tickets:** launcher and backend tickets are consumed exactly once.
- **Device binding:** a generated device identity is stored locally and bound
  server-side. Deleting the local file does not reset the server binding.
- **Startup gates:** the desktop runtime and FastAPI backend both refuse to start
  without a valid ticket. `python -m app` and direct runtime invocation exit 3.
- **EXE integrity:** the EXE rejects a modified `x.bat`.

## 4. Limits and honest caveats

1. **Source distribution cannot be made unbreakable.** A determined attacker can
   patch the Python client or rebuild the EXE. The server's refusal to sign a
   ticket is the practical boundary.
2. **No Authenticode signature.** `signtool` and a code-signing certificate were
   not available. Windows SmartScreen may warn. Sign the EXE before distribution.
3. **The EXE hash is not a signature.** It detects accidental modification, not
   a rebuilt EXE from modified source.
4. **Device identity is not TPM attestation.** It is a generated identifier bound
   server-side.
5. **Full interactive GUI login was not automated** because the production prompt
   reads the console directly. The authenticated headless path and the real
   runtime were verified; the GUI itself was not driven end-to-end.
6. **Local test license service.** The local server used for verification is not
   a production deployment. Production requires HTTPS, a protected signing key,
   a protected SQLite database, backups and monitoring.
7. **Research/training scripts are not application entry points.** They do not
   launch the UI or backend. The enforced application paths are the EXE, the
   authenticated gateway, the runtime and `python -m app`.
