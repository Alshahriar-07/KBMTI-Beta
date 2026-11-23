"""Launch-gate checks shared by the desktop runtime and the local backend."""

from __future__ import annotations

import hashlib
import hmac
import os

from .config import device_id as local_device_id
from .config import license_server_url, new_nonce
from .tokens import TokenError, load_trusted_public_key, verify_token


class LaunchDenied(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def hash_device(device_id: str) -> str:
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def verify_launch_token(token: str, device_id: str, *, audience: str = "backend") -> dict:
    try:
        claims = verify_token(token, load_trusted_public_key(), audience=audience)
    except TokenError as exc:
        raise LaunchDenied(exc.code, "This launch is not authorized by the KBMTI license service.") from exc
    expected = hash_device(device_id)
    if not hmac.compare_digest(str(claims["device"]), expected):
        raise LaunchDenied("LICENSE_DEVICE_MISMATCH", "This launch token belongs to another device.")
    return claims


def require_desktop_launch() -> dict:
    """Verify the backend launch ticket before the desktop app initializes.

    The FastAPI child consumes the same ticket. Consumption by the backend is the
    one-time-use check; this function proves the ticket is genuinely signed and
    bound to this device before any Qt or service code runs.
    """

    token = os.environ.get("KBMTI_APP_TOKEN", "").strip()
    device = os.environ.get("KBMTI_DEVICE_ID", "").strip()
    if not token or not device:
        raise LaunchDenied(
            "LICENSE_REQUIRED",
            "KBMTI must be started through KBMTI-RAW-TEST.exe and authenticated with a valid access key.",
        )
    try:
        license_server_url()
    except Exception as exc:  # configuration errors are a denial, not a bypass
        raise LaunchDenied("LICENSE_CONFIGURATION_INVALID", str(exc)) from exc
    return verify_launch_token(token, device)


def renew_backend_ticket() -> str | None:
    """Exchange the in-memory renewal ticket for a fresh backend ticket.

    Every backend start consumes a distinct one-time ticket. The renewal ticket
    lives only in the launcher process, is device-bound, and is never written to
    disk. If it is absent, the caller keeps its original launch ticket.
    """

    renewal = os.environ.get("KBMTI_RENEWAL_TOKEN", "").strip()
    if not renewal:
        return None
    from .client import LicenseClient, LicenseError

    try:
        device = local_device_id()
        renewed = LicenseClient().renew(renewal, device_id=device, nonce=new_nonce())
    except LicenseError as exc:
        raise LaunchDenied(exc.code, exc.message) from exc
    except Exception as exc:  # noqa: BLE001 - fail closed on any renewal failure
        raise LaunchDenied("LICENSE_RENEWAL_FAILED", "The KBMTI license session could not be renewed.") from exc
    return str(renewed["backend_token"])
