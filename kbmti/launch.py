"""Authenticated launcher gateway used by ``x.bat``.

The launcher prompts for the access key, exchanges it with the KBMTI license
service over HTTPS, verifies the returned Ed25519 tokens, consumes the launcher
ticket, then starts the internal runtime with a one-time backend ticket. No
access key, role flag or local environment variable is accepted as proof of
authorization.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys

from .licensing.client import LicenseClient, LicenseError
from .licensing.config import device_id, new_nonce

KEY_RE = re.compile(r"^KBMTI-[A-Z0-9]{5}-[A-Z0-9]{4}$")
KEY_MAX_LENGTH = len("KBMTI-XXXXX-0000")
KEY_RAW_MAX_LENGTH = 14  # KBMTI + XXXXX + 0000, without the two separators
PASSWORD_MAX_LENGTH = 128
ROLES = {"DEVELOPER": "DEVELOPER", "USER": "USER", "ADMIN": "ADMIN"}


def normalize_key(value: str) -> str:
    """Canonicalize a key for comparison: uppercase, no whitespace, fixed hyphens."""

    key = re.sub(r"\s+", "", value).upper()
    compact = key.replace("-", "")
    if compact.startswith("KBMTI") and len(compact) == 14:
        body = compact[5:]
        key = f"KBMTI-{body[:5]}-{body[5:]}"
    elif "-" not in key and len(compact) == 9:
        key = f"KBMTI-{compact[:5]}-{compact[5:]}"
    return key


def format_key_live(raw: str) -> str:
    """Format a partially typed key with the two separators inserted automatically.

    This operates on the raw alphanumeric buffer, never on the displayed text, so
    deleting a character cannot leave a stray hyphen behind. Hyphens the user
    types are ignored by the reader; only this function places separators.
    """

    key = raw.upper()
    if len(key) > 5:
        key = f"{key[:5]}-{key[5:]}"
    if len(raw) > 10:
        key = f"{key[:11]}-{key[11:]}"
    return key


def _read_key_windows(prompt: str) -> str:
    """Read a key with live uppercase formatting, cursor editing and no echo limits.

    Hyphens are not stored in the buffer, so they never count toward the key
    length and Backspace/Delete always remove a real character. The displayed
    key is uppercase because the credential is intentionally visible for this
    login field; passwords use the masked reader below.
    """

    import msvcrt

    buffer: list[str] = []
    cursor = 0
    padding = 24

    def render() -> None:
        shown = format_key_live("".join(buffer))
        visible_cursor = len(format_key_live("".join(buffer[:cursor])))
        line = prompt + shown
        target = len(prompt) + visible_cursor
        # Clear the old line by overwriting it with spaces, then move the cursor
        # back to the logical insertion point. Terminal width is not assumed.
        sys.stdout.write("\r" + line + " " * padding)
        sys.stdout.write("\b" * (padding + len(line) - target))
        sys.stdout.flush()

    render()
    try:
        while True:
            char = msvcrt.getwch()
            if char in {"\r", "\n"}:
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer)
            if char == "\x1b":
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise InputCancelled
            if char in {"\x00", "\xe0"}:
                second = msvcrt.getwch()
                if second == "K":  # left
                    cursor = max(0, cursor - 1)
                elif second == "M":  # right
                    cursor = min(len(buffer), cursor + 1)
                elif second == "G":  # home
                    cursor = 0
                elif second == "O":  # end
                    cursor = len(buffer)
                elif second == "S":  # delete
                    if cursor < len(buffer):
                        del buffer[cursor]
                render()
                continue
            if char == "\x08":
                if cursor > 0:
                    del buffer[cursor - 1]
                    cursor -= 1
                render()
                continue
            if char == "\x03":
                raise KeyboardInterrupt
            if char.isalnum() and len(buffer) < KEY_RAW_MAX_LENGTH:
                buffer.insert(cursor, char.upper())
                cursor += 1
                render()
    finally:
        char = ""


class InputCancelled(Exception):
    """The user pressed Escape at a credential prompt."""


def _read_masked_windows(prompt: str, max_length: int) -> str:
    """Read a credential with immediate, per-keystroke ``*`` feedback.

    ``getwch`` does not echo and does not wait for Enter. Function/arrow-key
    scancodes arrive as a NUL or 0xE0 prefix plus a second code; both are
    discarded. Only printable characters are retained, so paste and IME input
    cannot put control characters into the credential.
    """

    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()
    buffer: list[str] = []
    try:
        while True:
            char = msvcrt.getwch()
            if char in {"\r", "\n"}:
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer)
            if char == "\x1b":
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise InputCancelled
            if char in {"\x00", "\xe0"}:
                msvcrt.getwch()  # consume the second byte of an arrow/function key
                continue
            if char == "\x08":
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if char == "\x03":
                raise KeyboardInterrupt
            if char.isprintable() and len(buffer) < max_length:
                buffer.append(char)
                sys.stdout.write("*")
                sys.stdout.flush()
    finally:
        # Do not leave a credential in this frame's locals longer than needed.
        char = ""


def read_masked(prompt: str, max_length: int) -> str:
    if os.name == "nt":
        return _read_masked_windows(prompt, max_length)
    # Non-Windows terminals: getpass at least suppresses echo. The official
    # launcher is Windows-only; the stars are implemented by the Windows path.
    return getpass.getpass(prompt)


def read_key() -> str:
    try:
        if os.name == "nt":
            return normalize_key(_read_key_windows("  ENTER KEY    > "))
        return normalize_key(read_masked("  ENTER KEY    > ", KEY_MAX_LENGTH))
    except InputCancelled as exc:
        raise InputCancelled from exc


def read_password() -> str:
    try:
        return read_masked("  PASSWORD     > ", PASSWORD_MAX_LENGTH).strip()
    except InputCancelled as exc:
        raise InputCancelled from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kbmti.launch",
        description="Authenticate with the KBMTI license service and start the licensed desktop app.",
    )
    parser.add_argument("--role", required=True, choices=sorted(ROLES), help="authenticated role")
    parser.add_argument(
        "--key-stdin",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, runtime_args = parser.parse_known_args(argv)
    role = ROLES[args.role]
    try:
        if args.key_stdin:
            key = normalize_key(sys.stdin.readline())
            admin_password = sys.stdin.readline().strip() if role == "ADMIN" else None
        else:
            key = read_key()
            admin_password = read_password() if role == "ADMIN" else None
    except InputCancelled:
        print("  [CANCELLED] Returning to the login menu.", flush=True)
        return 2
    if not KEY_RE.fullmatch(key):
        print("  [DENIED] Key format must be KBMTI-XXXXX-0000.", flush=True)
        return 1
    if role == "ADMIN" and not admin_password:
        print("  [DENIED] Administrator password is required.", flush=True)
        return 1

    device = device_id()
    nonce = new_nonce()
    try:
        client = LicenseClient()
        session = client.login(
            role=role,
            key=key,
            device_id=device,
            nonce=nonce,
            admin_password=admin_password,
        )
        client.consume(session["launcher_token"], audience="launcher", device_id=device)
    except LicenseError as exc:
        print(f"  [DENIED] {exc.message}", flush=True)
        print(f"  [CODE]   {exc.code}", flush=True)
        return 1
    except Exception:  # noqa: BLE001 - never leak key material or a traceback to the login screen
        print("  [DENIED] The KBMTI license service could not authorize this launch.", flush=True)
        return 1
    finally:
        key = ""
        admin_password = None

    print(f"  [OK] {session['role']} license verified · {session['license_id']}", flush=True)
    os.environ["KBMTI_APP_TOKEN"] = session["backend_token"]
    os.environ["KBMTI_RENEWAL_TOKEN"] = session["renewal_token"]
    os.environ["KBMTI_DEVICE_ID"] = device
    os.environ["KBMTI_LICENSE_ROLE"] = session["role"]
    os.environ["KBMTI_LICENSE_ID"] = session["license_id"]
    os.environ["KBMTI_ROLE"] = session["role"]
    # The role variable above is display metadata only. Authorization is the
    # signed backend ticket, which the FastAPI startup gate consumes.

    from .runtime import main as runtime_main

    return runtime_main(runtime_args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
