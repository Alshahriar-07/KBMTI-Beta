from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.market_data.mt5_gateway import MT5Gateway
from tests.fake_mt5 import FakeMT5


@pytest.fixture
def terminal_exe(tmp_path: Path) -> Path:
    install = tmp_path / "MetaTrader 5"
    install.mkdir()
    exe = install / "terminal64.exe"
    exe.write_bytes(b"fake terminal executable")
    return exe


@pytest.fixture
def fake_mt5() -> FakeMT5:
    return FakeMT5()


@pytest.fixture
def gateway(fake_mt5: FakeMT5, terminal_exe: Path) -> MT5Gateway:
    return MT5Gateway(module=fake_mt5, terminal_path=str(terminal_exe))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        poll_interval_seconds=1.0,
        stale_after_seconds=120.0,
        default_provider="mt5",
        patron_autoload=False,
        patron_checkpoint=tmp_path / "patron-checkpoint-missing.pt",
        patron_warmup_path=tmp_path / "patron-warmup-missing.parquet",
    )


@pytest.fixture
def make_client(settings: Settings, terminal_exe: Path):
    created: list[TestClient] = []

    def factory(gateway: MT5Gateway | None = None, **kwargs) -> TestClient:
        app = create_app(
            settings=kwargs.pop("settings", settings),
            gateway=gateway or MT5Gateway(module=FakeMT5(), terminal_path=str(terminal_exe)),
            start_polling=False,
            configure_logs=False,
        )
        client = TestClient(app)
        client.__enter__()
        created.append(client)
        return client

    yield factory
    for client in created:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:  # type: ignore[no-untyped-def]
    return make_client()
