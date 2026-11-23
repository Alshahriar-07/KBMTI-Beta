from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kbmti.licensing.gate import LaunchDenied, require_desktop_launch, verify_launch_token  # noqa: E402
from kbmti.licensing.tokens import TokenError, sign_token, verify_token  # noqa: E402
from license_server.app import create_app as create_license_app  # noqa: E402
from license_server.db import connect, issue_license  # noqa: E402


def _setup(tmp_path: Path):
    private = Ed25519PrivateKey.generate()
    key_path = tmp_path / "signing.pem"
    key_path.write_bytes(
        private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    db = tmp_path / "licenses.db"
    app = create_license_app(db_path=db, signing_key_path=key_path, seed=True)
    connection = connect(db)
    user_id, user_key = issue_license(connection, role="USER", days=30)
    dev_id, dev_key = issue_license(connection, role="DEVELOPER", days=30)
    admin_id, admin_key = issue_license(connection, role="ADMIN", days=30, admin_password="admin-pass-123")
    connection.close()
    return TestClient(app), private.public_key(), db, {
        "user": (user_id, user_key),
        "dev": (dev_id, dev_key),
        "admin": (admin_id, admin_key),
    }


def _login(client: TestClient, *, role: str, key: str, nonce: str = "n" * 64, device: str = "d" * 64, password: str | None = None):
    body = {"role": role, "key": key, "nonce": nonce, "device_id": device, "client_version": "test"}
    if password is not None:
        body["admin_password"] = password
    return client.post("/v1/auth/login", json=body)


def test_valid_user_and_developer_and_admin_login(tmp_path: Path) -> None:
    api, public, _db, keys = _setup(tmp_path)
    for role, name in (("USER", "user"), ("DEVELOPER", "dev"), ("ADMIN", "admin")):
        _id, key = keys[name]
        response = _login(api, role=role, key=key, password="admin-pass-123" if role == "ADMIN" else None)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["role"] == role
        assert verify_token(body["launcher_token"], public, audience="launcher")["role"] == role
        assert verify_token(body["backend_token"], public, audience="backend")["role"] == role
        assert verify_token(body["renewal_token"], public, audience="renew")["role"] == role


def test_server_accepts_lowercase_mixed_case_and_compact_keys(tmp_path: Path) -> None:
    api, _public, _db, keys = _setup(tmp_path)
    _id, key = keys["user"]
    lowered = key.lower()
    compact = key.replace("-", "").lower()
    for variant in (lowered, compact, key.swapcase()):
        response = _login(api, role="USER", key=variant, device="a" * 64)
        assert response.status_code == 200, response.text

    _admin_id, admin_key = keys["admin"]
    admin = _login(
        api,
        role="ADMIN",
        key=admin_key.lower().replace("-", ""),
        password="  admin-pass-123  ",
        device="z" * 64,
    )
    assert admin.status_code == 200, admin.text


def test_invalid_expired_and_revoked_keys_are_denied(tmp_path: Path) -> None:
    api, _public, db, keys = _setup(tmp_path)
    user_id, user_key = keys["user"]
    assert _login(api, role="USER", key="KBMTI-AAAAA-0000").status_code == 401

    connection = connect(db)
    connection.execute("UPDATE licenses SET expires_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", user_id))
    connection.commit()
    expired = _login(api, role="USER", key=user_key)
    assert expired.status_code == 403
    assert expired.json()["error"]["code"] == "LICENSE_EXPIRED"

    connection.execute("UPDATE licenses SET expires_at = NULL, status = 'revoked' WHERE id = ?", (user_id,))
    connection.commit()
    revoked = _login(api, role="USER", key=user_key)
    assert revoked.status_code == 403
    assert revoked.json()["error"]["code"] == "LICENSE_REVOKED"
    connection.close()


def test_admin_requires_password(tmp_path: Path) -> None:
    api, _public, _db, keys = _setup(tmp_path)
    _id, key = keys["admin"]
    missing = _login(api, role="ADMIN", key=key)
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "ADMIN_PASSWORD_REQUIRED"
    wrong = _login(api, role="ADMIN", key=key, password="wrong-password")
    assert wrong.status_code == 401


def test_device_binding_and_replay(tmp_path: Path) -> None:
    api, _public, _db, keys = _setup(tmp_path)
    _id, key = keys["user"]
    first = _login(api, role="USER", key=key, device="a" * 64)
    assert first.status_code == 200
    second = _login(api, role="USER", key=key, device="b" * 64)
    assert second.status_code == 403
    assert second.json()["error"]["code"] == "DEVICE_LIMIT"

    token = first.json()["launcher_token"]
    consumed = api.post("/v1/session/consume", json={"token": token, "audience": "launcher", "device_id": "a" * 64})
    assert consumed.status_code == 200
    replay = api.post("/v1/session/consume", json={"token": token, "audience": "launcher", "device_id": "a" * 64})
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "TOKEN_ALREADY_USED"


def test_modified_token_is_rejected(tmp_path: Path) -> None:
    api, _public, _db, keys = _setup(tmp_path)
    _id, key = keys["user"]
    token = _login(api, role="USER", key=key, device="c" * 64).json()["launcher_token"]
    payload = token.split(".")[1]
    replacement = "A" if payload[0] != "A" else "B"
    modified = f"{token.split('.')[0]}.{replacement}{payload[1:]}.{token.split('.')[2]}"
    response = api.post("/v1/session/consume", json={"token": modified, "audience": "launcher", "device_id": "c" * 64})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_SIGNATURE_INVALID"


def test_renewal_issues_fresh_one_time_backend_ticket(tmp_path: Path) -> None:
    api, public, _db, keys = _setup(tmp_path)
    _id, key = keys["user"]
    body = _login(api, role="USER", key=key, device="e" * 64).json()
    renewed = api.post(
        "/v1/session/renew",
        json={"token": body["renewal_token"], "device_id": "e" * 64, "nonce": "r" * 64},
    )
    assert renewed.status_code == 200, renewed.text
    fresh = renewed.json()["backend_token"]
    assert verify_token(fresh, public, audience="backend")["nonce"] == "r" * 64
    assert api.post(
        "/v1/session/consume", json={"token": fresh, "audience": "backend", "device_id": "e" * 64}
    ).status_code == 200


def test_masked_input_shows_stars_backspace_and_never_echoes_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import msvcrt

    from kbmti.launch import read_masked

    keys = iter(["K", "B", "\x08", "M", "T", "I", "\r"])
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(keys))
    assert read_masked("KEY > ", 16) == "KMTI"
    output = capsys.readouterr().out
    assert output.startswith("KEY > ")
    assert output.count("*") == 5
    assert "\b \b" in output
    assert "KMTI" not in output


def test_masked_input_ignores_arrow_keys_and_enforces_length(monkeypatch: pytest.MonkeyPatch) -> None:
    import msvcrt

    from kbmti.launch import read_masked

    keys = iter(["a", "\xe0", "K", "b", "\x00", "M", "c", "\r"])
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(keys))
    assert read_masked("> ", 2) == "ab"


def test_masked_input_escape_cancels(monkeypatch: pytest.MonkeyPatch) -> None:
    import msvcrt

    from kbmti.launch import InputCancelled, read_masked

    keys = iter(["X", "\x1b"])
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(keys))
    with pytest.raises(InputCancelled):
        read_masked("> ", 16)


def test_key_formatting_is_case_insensitive_and_inserts_hyphens() -> None:
    from kbmti.launch import format_key_live, normalize_key

    assert normalize_key("kbmti-devmp-1304") == "KBMTI-DEVMP-1304"
    assert normalize_key("KbMtI-DeVmP-1304") == "KBMTI-DEVMP-1304"
    assert normalize_key("KBMTIDEVMP1304") == "KBMTI-DEVMP-1304"
    assert normalize_key("  kbmti devmp 1304  ") == "KBMTI-DEVMP-1304"
    assert normalize_key("devmp1304") == "KBMTI-DEVMP-1304"
    assert format_key_live("kbmtiDEVMP1304") == "KBMTI-DEVMP-1304"
    assert format_key_live("kbmtidev") == "KBMTI-DEV"


def test_key_editor_formats_uppercase_and_handles_paste_and_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    import msvcrt

    from kbmti.launch import read_key

    # Lowercase paste with separators already present: separators must not count
    # as characters, and the result must normalize to the canonical key.
    pasted = iter(list("kbmti-devmp-1304") + ["\r"])
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(pasted))
    assert read_key() == "KBMTI-DEVMP-1304"

    # Cursor left, then Delete removes the character under the cursor, not the
    # last character and not an automatically inserted hyphen.
    keys = iter(["A", "B", "C", "\xe0", "K", "\xe0", "S", "\r"])
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(keys))
    assert read_key() == "AB"


def test_expired_and_wrong_audience_tokens_are_rejected() -> None:
    private = Ed25519PrivateKey.generate()
    now = int(time.time())
    claims = {
        "v": 1,
        "iss": "kbmti-license-service",
        "aud": "backend",
        "jti": "expired",
        "sid": "expired-session",
        "sub": "license",
        "role": "USER",
        "device": "d" * 64,
        "nonce": "n" * 64,
        "iat": now - 120,
        "nbf": now - 120,
        "exp": now - 60,
    }
    expired = sign_token(claims, private)
    with pytest.raises(TokenError, match="expired"):
        verify_token(expired, private.public_key(), audience="backend")
    active = {**claims, "jti": "active", "iat": now, "nbf": now, "exp": now + 60}
    token = sign_token(active, private)
    with pytest.raises(TokenError, match="different component"):
        verify_token(token, private.public_key(), audience="launcher")


def test_client_verifies_server_tokens_and_renews(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import kbmti.licensing.client as client_module

    api, public, _db, keys = _setup(tmp_path)
    _id, key = keys["user"]

    def fake_post(url: str, payload: dict) -> dict:
        path = "/" + url.split("/", 3)[3]
        response = api.post(path, json=payload)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(client_module, "_post", fake_post)
    monkeypatch.setattr(client_module, "load_trusted_public_key", lambda: public)
    client = client_module.LicenseClient(server_url="http://127.0.0.1:8790")
    device = "j" * 64
    session = client.login(role="USER", key=key, device_id=device, nonce="n" * 64)
    assert session["role"] == "USER"
    assert client.consume(session["launcher_token"], audience="launcher", device_id=device)["ok"] is True
    renewed = client.renew(session["renewal_token"], device_id=device, nonce="q" * 64)
    assert renewed["backend_token"]


def test_fake_environment_and_direct_runtime_are_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBMTI_APP_TOKEN", "v1.fake.signature")
    monkeypatch.setenv("KBMTI_DEVICE_ID", "f" * 64)
    with pytest.raises(LaunchDenied):
        require_desktop_launch()
    monkeypatch.delenv("KBMTI_APP_TOKEN")
    monkeypatch.delenv("KBMTI_DEVICE_ID")
    with pytest.raises(LaunchDenied):
        require_desktop_launch()


def test_signed_token_is_device_bound(tmp_path: Path) -> None:
    api, public, _db, keys = _setup(tmp_path)
    _id, key = keys["user"]
    body = _login(api, role="USER", key=key, device="g" * 64).json()
    claims = verify_token(body["backend_token"], public, audience="backend")
    assert claims["device"] == __import__("hashlib").sha256(("g" * 64).encode()).hexdigest()
    # The test signing key is not the pinned release key, so this must fail
    # closed rather than accepting a token merely because it is well-formed.
    with pytest.raises(LaunchDenied):
        verify_launch_token(body["backend_token"], "g" * 64)


def test_public_python_entry_redirects_to_official_exe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from kbmti import __main__ as entry

    fake_exe = tmp_path / "KBMTI-RAW-TEST.exe"
    fake_exe.write_bytes(b"fake official launcher")
    monkeypatch.setattr(entry, "official_launcher", lambda: fake_exe)
    called: list[list[str]] = []

    def fake_run(command, check=False):
        called.append(command)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert entry.main(["--headless"]) == 7
    assert called == [[str(fake_exe), "--headless"]]


def test_public_python_entry_never_initializes_app(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from kbmti import __main__ as entry

    monkeypatch.setattr(entry, "official_launcher", lambda: None)
    assert entry.main([]) == 3
    assert "Direct Python execution is not supported" in capsys.readouterr().err


def test_direct_backend_and_runtime_are_blocked_without_ticket() -> None:
    env = dict(os.environ)
    for name in ("KBMTI_APP_TOKEN", "KBMTI_RENEWAL_TOKEN", "KBMTI_DEVICE_ID"):
        env.pop(name, None)
    backend = subprocess.run(
        [sys.executable, "-m", "app"],
        cwd=ROOT / "backend",
        env={**env, "PYTHONPATH": "."},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert backend.returncode == 3
    assert "cannot start directly" in backend.stderr
    runtime = subprocess.run(
        [sys.executable, "-m", "kbmti.runtime", "--headless"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert runtime.returncode == 3
    assert "KBMTI-RAW-TEST.exe" in runtime.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher check")
def test_batch_self_test() -> None:
    result = subprocess.run(
        ["cmd.exe", "/d", "/s", "/c", "x.bat /selftest"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert "KBMTI launcher self-test OK" in result.stdout
