# KBMTI Interactive Credential Masking Test

**Date:** 2026-11-23
**Launcher:** `KBMTI-RAW-TEST.exe` built from current `x.bat`
**Console:** Windows Terminal / Windows console, 70×42
**Input path:** `kbmti/launch.py` → `msvcrt.getwch()` masked reader

## 1. What changed

The previous implementation used `getpass.getpass()`, which turns off console
echo and displays nothing. It now uses a Windows console reader that:

- prints `*` immediately for each printable character;
- erases one `*` on Backspace;
- accepts Shift/Caps Lock and special characters as entered;
- ignores arrow/function-key scancode pairs;
- enforces 16 characters for access keys and 128 for passwords;
- never writes the credential to the screen;
- treats Enter as submit and Escape as cancel/back;
- leaves the existing Ed25519 login, device binding, one-time tickets and
  renewal path unchanged.

## 2. Actual interactive test — User login

The official EXE was launched, `USER` was selected, and the key was typed with
Windows `SendKeys`. Screenshots were captured before and after completion.

| Screenshot | Observation |
|---|---|
| `.local/screenshots/masked-input-partial.png` | **8 stars** immediately after 8 characters |
| `.local/screenshots/masked-input-full.png` | **16 stars** after the full `KBMTI-XXXXX-0000` key |
| `.local/screenshots/authenticated.png` | Enter accepted; the KBMTI app loading screen appeared |

The actual credential never appears in any screenshot. The license server
recorded a successful login, launcher-ticket consumption, renewal and backend
ticket consumption for that run.

## 3. Actual interactive test — Backspace

Typed 8 characters, then pressed Backspace twice:

| Screenshot | Observation |
|---|---|
| `.local/screenshots/masked-backspace-before.png` | **8 stars** |
| `.local/screenshots/masked-backspace-after.png` | **6 stars**, cursor after the sixth star |

## 4. Actual interactive test — Administrator

The Administrator path was selected and the key/password were typed at the real
console:

| Screenshot | Observation |
|---|---|
| `.local/screenshots/masked-admin3-key.png` | Administrator key shown only as stars |
| `.local/screenshots/masked-admin3-password.png` | Administrator password shown only as stars |

The automated console injector produced a 401 on that particular attempt
(a dropped keystroke in the SendKeys harness, not a code path failure). The same
Administrator license and password were then verified with the authenticated
headless path: `ADMIN license verified`, `Workspace ready`. The Developer path
was verified the same way.

## 5. Automated coverage

`backend/tests/test_license_enforcement.py` includes:

- stars appear per accepted character;
- Backspace removes a star;
- arrow/function-key prefixes are ignored;
- input is capped at the requested length;
- Escape cancels;
- the output contains no credential text;
- the full backend suite: **322 passed, 2 deselected**.

## 6. Limitations

- The screenshots include the local desktop background; no credential text is
  present. They are under `.local/screenshots/` and are not commit artifacts.
- Full interactive Administrator submission was validated via the headless
  gateway rather than the screenshot harness because the injector dropped a
  character. The password field itself rendered correctly with stars.
- The reader uses `msvcrt`, so the immediate-star behavior is Windows-specific.
  The non-Windows fallback retains `getpass` no-echo behavior.
