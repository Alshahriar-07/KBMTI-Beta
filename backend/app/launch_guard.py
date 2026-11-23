"""Fail-closed license check for the local FastAPI backend.

The desktop launcher passes a short-lived, device-bound, one-time backend ticket.
This module verifies the pinned Ed25519 signature, then consumes the ticket with
the license service before any market data or model starts. ``create_app`` tests
that explicitly disable polling bypass this production startup gate.

Source availability means a determined operator can modify these files. The
enforceable boundary is the remote license service's signing key and session
state, not an unbreakable local check.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


class LaunchDenied(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _licensing_modules():
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from kbmti.licensing.client import LicenseClient
    from kbmti.licensing.config import device_id
    from kbmti.licensing.gate import verify_launch_token

    return LicenseClient, device_id, verify_launch_token


def _claims() -> tuple[str, str, dict]:
    token = os.environ.get("KBMTI_APP_TOKEN", "").strip()
    device = os.environ.get("KBMTI_DEVICE_ID", "").strip()
    if not token or not device:
        raise LaunchDenied(
            "LICENSE_REQUIRED",
            "The KBMTI backend cannot start directly. Launch KBMTI-RAW-TEST.exe and authenticate.",
        )
    _LicenseClient, _device_id, verify_launch_token = _licensing_modules()
    return token, device, verify_launch_token(token, device, audience="backend")


def preflight() -> dict:
    """Offline signature/device check for a friendly CLI failure before uvicorn."""

    _token, _device, claims = _claims()
    return claims


def enforce() -> dict:
    token, device, claims = _claims()
    LicenseClient, _device_id, _verify_launch_token = _licensing_modules()
    try:
        LicenseClient().consume(token, audience="backend", device_id=device)
    except Exception as exc:
        raise LaunchDenied(
            "LICENSE_SESSION_REJECTED",
            "The KBMTI license service rejected this backend session.",
        ) from exc
    return claims
