"""HTTPS client for the KBMTI license service."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from .config import CLIENT_VERSION, REQUEST_TIMEOUT_SECONDS, license_server_url
from .gate import hash_device
from .tokens import TokenError, load_trusted_public_key, verify_token


class LicenseError(RuntimeError):
    """A user-presentable licensing failure with a stable machine code."""

    def __init__(self, code: str, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"KBMTI-License-Client/{CLIENT_VERSION}",
        },
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=context) as response:
            raw = response.read(64 * 1024)
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read(64 * 1024)
        status = exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LicenseError(
            "LICENSE_SERVER_UNREACHABLE",
            "The KBMTI license service could not be reached. Check your network or contact KBMTI.",
        ) from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenseError("LICENSE_SERVER_INVALID_RESPONSE", "The license service returned an invalid response.") from exc
    if not isinstance(decoded, dict):
        raise LicenseError("LICENSE_SERVER_INVALID_RESPONSE", "The license service returned an invalid response.")
    if status >= 400:
        error = decoded.get("error") or {}
        code = str(error.get("code") or "LICENSE_DENIED")
        message = str(error.get("message") or "KBMTI denied this license request.")
        raise LicenseError(code, message, status=status)
    return decoded


class LicenseClient:
    def __init__(self, server_url: str | None = None) -> None:
        self.server_url = (server_url or license_server_url()).rstrip("/")
        parsed = urlparse(self.server_url)
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise LicenseError("LICENSE_SERVER_INSECURE", "A remote license server must use HTTPS.")

    def login(
        self,
        *,
        role: str,
        key: str,
        device_id: str,
        nonce: str,
        admin_password: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": role,
            "key": key,
            "device_id": device_id,
            "nonce": nonce,
            "client_version": CLIENT_VERSION,
        }
        if admin_password is not None:
            payload["admin_password"] = admin_password
        response = _post(f"{self.server_url}/v1/auth/login", payload)
        launcher_token = response.get("launcher_token")
        backend_token = response.get("backend_token")
        renewal_token = response.get("renewal_token")
        if not all(isinstance(value, str) for value in (launcher_token, backend_token, renewal_token)):
            raise LicenseError("LICENSE_SERVER_INVALID_RESPONSE", "The license service did not return launch tokens.")
        public_key = load_trusted_public_key()
        try:
            launcher_claims = verify_token(launcher_token, public_key, audience="launcher")
            backend_claims = verify_token(backend_token, public_key, audience="backend")
            renewal_claims = verify_token(renewal_token, public_key, audience="renew")
        except TokenError as exc:
            raise LicenseError(exc.code, "The license service returned a token that failed verification.") from exc
        if any(claims["nonce"] != nonce for claims in (launcher_claims, backend_claims, renewal_claims)):
            raise LicenseError("LICENSE_NONCE_MISMATCH", "The license response was not bound to this launch request.")
        if len({claims["device"] for claims in (launcher_claims, backend_claims, renewal_claims)}) != 1:
            raise LicenseError("LICENSE_DEVICE_MISMATCH", "The license response is bound to another device.")
        return {
            "launcher_token": launcher_token,
            "backend_token": backend_token,
            "renewal_token": renewal_token,
            "role": launcher_claims["role"],
            "license_id": launcher_claims["sub"],
            "expires_at": launcher_claims["exp"],
        }

    def renew(self, renewal_token: str, *, device_id: str, nonce: str) -> dict[str, Any]:
        response = _post(
            f"{self.server_url}/v1/session/renew",
            {"token": renewal_token, "device_id": device_id, "nonce": nonce},
        )
        token = response.get("backend_token")
        if not isinstance(token, str):
            raise LicenseError("LICENSE_SERVER_INVALID_RESPONSE", "The license service did not return a backend token.")
        public_key = load_trusted_public_key()
        try:
            claims = verify_token(token, public_key, audience="backend")
        except TokenError as exc:
            raise LicenseError(exc.code, "The renewed backend token failed verification.") from exc
        if claims["device"] != hash_device(device_id) or claims["nonce"] != nonce:
            raise LicenseError("LICENSE_BINDING_INVALID", "The renewed token is not bound to this launch.")
        return {"backend_token": token, "claims": claims}

    def consume(self, token: str, *, audience: str, device_id: str) -> dict[str, Any]:
        response = _post(
            f"{self.server_url}/v1/session/consume",
            {"token": token, "audience": audience, "device_id": device_id},
        )
        if response.get("ok") is not True:
            raise LicenseError("LICENSE_SESSION_NOT_CONSUMED", "The license service did not accept this session.")
        return response

    def health(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.server_url}/v1/health",
            headers={"Accept": "application/json", "User-Agent": f"KBMTI-License-Client/{CLIENT_VERSION}"},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS, context=ssl.create_default_context()
            ) as response:
                decoded = json.loads(response.read(64 * 1024).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise LicenseError("LICENSE_SERVER_UNREACHABLE", "The KBMTI license service is not reachable.") from exc
        return decoded if isinstance(decoded, dict) else {}
