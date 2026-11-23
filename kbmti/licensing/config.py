"""License server configuration and local device identity."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEVICE_ID_FILE = Path(
    os.environ.get("KBMTI_DEVICE_FILE", str(Path.home() / ".kbmti" / "device-id"))
).expanduser()
DEFAULT_SERVER_URL = "http://127.0.0.1:8790"
CLIENT_VERSION = "1.2.0"
REQUEST_TIMEOUT_SECONDS = 12.0
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class LicenseConfigurationError(RuntimeError):
    """The license client cannot be configured safely."""


def _load_dotenv() -> None:
    """Load the project's .env for developer convenience without overriding it."""

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - optional in frozen installs
        load_dotenv = None
    candidates = (PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env")
    if load_dotenv is not None:
        for candidate in candidates:
            if candidate.is_file():
                load_dotenv(candidate, override=False)
        return
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def license_server_url() -> str:
    _load_dotenv()
    raw = os.environ.get("KBMTI_LICENSE_SERVER_URL", DEFAULT_SERVER_URL).strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LicenseConfigurationError("KBMTI_LICENSE_SERVER_URL must be an absolute HTTP(S) URL.")
    # A local development server is allowed; any remote license service must use
    # TLS. This prevents silently sending access keys over plaintext networking.
    if parsed.scheme != "https" and parsed.hostname not in LOOPBACK_HOSTS:
        raise LicenseConfigurationError(
            "A non-local license server must use HTTPS. Refusing to send access keys over plaintext."
        )
    return raw


def device_identity_path() -> Path:
    override = os.environ.get("KBMTI_DEVICE_FILE", "").strip()
    return Path(override).expanduser() if override else DEVICE_ID_FILE


def device_id() -> str:
    path = device_identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = path.read_text(encoding="ascii").strip()
    except OSError:
        value = ""
    if len(value) < 32:
        value = secrets.token_hex(32)
        path.write_text(value, encoding="ascii")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return value


def new_nonce() -> str:
    return secrets.token_hex(32)
