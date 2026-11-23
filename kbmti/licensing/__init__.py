"""KBMTI license client and signed launch-token protocol.

The desktop application trusts only tokens signed by the KBMTI license service.
The Ed25519 public key is pinned in this package; the private signing key never
ships with the application source or executable.
"""

from __future__ import annotations

from .client import LicenseClient, LicenseError
from .tokens import TokenError, verify_token

__all__ = ["LicenseClient", "LicenseError", "TokenError", "verify_token"]
