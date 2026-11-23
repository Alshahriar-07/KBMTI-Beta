from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.market_data.mt5_gateway import MT5Gateway
from tests.fake_mt5 import FakeMT5


def select_symbol(client: TestClient, symbol: str = "BTCUSDm") -> dict:
    response = client.post("/api/v1/market/symbol", json={"symbol": symbol})
    assert response.status_code == 200, response.text
    return response.json()


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["stage"] == 2
    assert body["app"] == "KBMTI"
    assert body["patron"]["state"] in {"NOT_CONFIGURED", "DISABLED"}


def test_root_documents_read_only_scope(client: TestClient) -> None:
    body = client.get("/").json()
    assert body["stage"] == 2
    assert "no trading" in body["note"].lower()


def test_request_id_is_preserved_and_returned_on_errors(client: TestClient) -> None:
    supplied = "kbmti-correlation-1234"
    response = client.get("/api/v1/health", headers={"X-Request-ID": supplied})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == supplied

    error = client.post(
        "/api/v1/market/symbol",
        json={"symbol": "NOTAREALPAIR"},
        headers={"X-Request-ID": supplied},
    )
    assert error.status_code == 422
    assert error.headers["X-Request-ID"] == supplied
    assert error.json()["error"]["request_id"] == supplied


def test_invalid_request_id_is_replaced_not_reflected(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "x" * 65})
    generated = response.headers["X-Request-ID"]
    assert generated != "x" * 65
    assert len(generated) == 32


def test_disconnected_startup_is_usable(make_client) -> None:  # type: ignore[no-untyped-def]
    failing = MT5Gateway(module=FakeMT5(fail_initialize=True))
    client = make_client(gateway=failing)
    snapshot = client.get("/api/v1/market/snapshot").json()
    assert snapshot["connected"] is False
    assert snapshot["data_state"] == "unavailable"
    assert snapshot["stale_reason"]

    status = client.get("/api/v1/mt5/status").json()
    assert status["connected"] is False
    assert status["last_error"]

    symbols = client.get("/api/v1/mt5/symbols").json()
    assert symbols["connected"] is False
    assert symbols["symbols"] == []
    assert symbols["error"]


def test_symbol_discovery_lists_btc_variants(client: TestClient) -> None:
    response = client.get("/api/v1/mt5/symbols?refresh=true")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert body["symbols"][0]["name"] == "BTCUSD"
    assert all("BTC" in item["name"] for item in body["symbols"])


def test_symbol_selection_persists_and_loads_data(client: TestClient) -> None:
    body = select_symbol(client, "BTCUSDm")
    assert body["selected_symbol"] == "BTCUSDm"
    assert body["btc_like"] is True
    assert body["status"]["connected"] is True

    status = client.get("/api/v1/mt5/status").json()
    assert status["selected_symbol"] == "BTCUSDm"
    assert status["timeframe"] == "M15"

    candles = client.get("/api/v1/market/candles?limit=200").json()
    assert candles["symbol"] == "BTCUSDm"
    assert candles["source"] == "mt5"
    assert candles["count"] > 100
    assert candles["forming_candle"] is not None
    assert "tick_volume_note" in candles
    assert candles["time_basis"] == "utc"
    assert candles["server_offset_seconds"] is not None
    first = candles["candles"][0]
    assert {"time", "open", "high", "low", "close", "tick_volume"} <= set(first)
    assert first["high"] >= max(first["open"], first["close"])


def test_invalid_symbol_returns_structured_error(client: TestClient) -> None:
    response = client.post("/api/v1/market/symbol", json={"symbol": "NOTAREALPAIR"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "NOTAREALPAIR" in body["error"]["message"]


def test_snapshot_contains_bid_ask_spread(client: TestClient) -> None:
    select_symbol(client)
    snapshot = client.get("/api/v1/market/snapshot").json()
    assert snapshot["bid"] is not None and snapshot["ask"] is not None
    assert snapshot["ask"] > snapshot["bid"]
    assert snapshot["spread_points"] == 25
    assert snapshot["tick_time_iso"]
    assert snapshot["data_state"] == "live"


def test_timeframe_switch_reloads_candles(client: TestClient) -> None:
    select_symbol(client)
    response = client.post("/api/v1/market/timeframe", json={"timeframe": "H1"})
    assert response.status_code == 200
    assert response.json()["timeframe"] == "H1"
    candles = client.get("/api/v1/market/candles").json()
    assert candles["timeframe"] == "H1"

    daily = client.post("/api/v1/market/timeframe", json={"timeframe": "D1"})
    assert daily.status_code == 200
    assert daily.json()["timeframe"] == "D1"

    invalid = client.post("/api/v1/market/timeframe", json={"timeframe": "W1"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


def test_timeframe_catalogue_matches_supported_set(client: TestClient) -> None:
    values = [item["value"] for item in client.get("/api/v1/market/timeframes").json()]
    assert values == ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]


def test_indicators_are_computed_from_mt5_candles(client: TestClient) -> None:
    select_symbol(client)
    response = client.get("/api/v1/indicators?limit=200")
    assert response.status_code == 200
    body = response.json()
    assert body["candle_count"] >= 100
    assert body["series"]["ema9"]
    assert body["series"]["rsi14"]
    assert body["latest"]["ema50"] is not None
    assert body["latest"]["atr14"] is not None
    assert body["warmup_bars"] >= 50
    for point in body["series"]["macd"]:
        assert set(point) == {"time", "value"}


def test_signal_is_rule_based_and_explained(client: TestClient) -> None:
    select_symbol(client)
    body = client.get("/api/v1/signals/current").json()
    assert body["engine"] == "rule-based-technical-v1"
    assert body["ai_available"] is False
    assert body["label"] in {"BUY BIAS", "SELL BIAS", "WAIT", "NO CLEAR SETUP"}
    assert body["invalidation"]
    assert "not AI" in body["disclaimer"]
    assert body["metrics"]["rsi14"] is not None


def test_signal_without_data_is_no_clear_setup(client: TestClient) -> None:
    body = client.get("/api/v1/signals/current").json()
    assert body["label"] == "NO CLEAR SETUP"
    assert body["source_candle_count"] == 0
    assert body["warnings"]


def test_forecast_endpoints_report_patron_contract(client: TestClient) -> None:
    status = client.get("/api/v1/forecast/status").json()
    assert status["ai_available"] is False
    assert status["provider"] == "patron"
    assert status["model_id"] == "patron-1.0.0"
    assert status["tokenizer_id"] is None
    assert status["stage"] == 2
    assert status["checkpoint_exists"] is False
    assert status["contract"]["input_candles"] == 96
    assert status["contract"]["horizon_candles"] == 6

    readiness = client.get("/api/v1/patron/readiness").json()
    assert readiness["ready"] is False
    assert readiness["checkpoint_exists"] is False

    run = client.post("/api/v1/forecast/run")
    assert run.status_code == 503
    assert run.json()["error"]["code"] == "PATRON_UNAVAILABLE"

    history = client.get("/api/v1/forecast/history").json()
    # The failed attempt is recorded for monitoring, with no predicted candles.
    assert history["count"] == 1
    assert history["runs"][0]["status"] == "error"
    assert history["runs"][0]["warnings"]
    assert history["ai_available"] is False

    patron = client.get("/api/v1/patron/info").json()
    assert patron["contract"]["symbol"] == "BTC/USDT"
    assert patron["capabilities"]["chat"] is False


def test_system_status_never_invents_temperature(client: TestClient) -> None:
    body = client.get("/api/v1/system/status").json()
    assert body["cpu"]["percent"] is not None
    assert body["memory"]["total_bytes"]
    assert "available" in body["gpu"]
    if not body["temperature"]["available"]:
        assert body["temperature"]["celsius"] is None
        assert body["temperature"]["note"]
    assert body["backend"]["status"] == "ok"


def test_settings_roundtrip(client: TestClient) -> None:
    select_symbol(client)
    initial = client.get("/api/v1/settings").json()
    assert initial["symbol"] == "BTCUSDm"
    assert initial["chart"]["show_ema"] is True
    assert initial["ui"]["theme"] == "dark"

    updated = client.patch(
        "/api/v1/settings",
        json={
            "timeframe": "M5",
            "candle_limit": 300,
            "chart": {"show_rsi": False},
            "ui": {"theme": "light"},
        },
    ).json()
    assert updated["timeframe"] == "M5"
    assert updated["candle_limit"] == 300
    assert updated["chart"]["show_rsi"] is False
    assert updated["chart"]["show_ema"] is True
    assert updated["ui"]["theme"] == "light"

    assert client.patch("/api/v1/settings", json={"candle_limit": 5}).status_code == 422
    assert client.patch("/api/v1/settings", json={"ui": {"theme": "sepia"}}).status_code == 422
    assert client.patch("/api/v1/settings", json={"mt5": {"terminal_path": "Z:/nope/terminal64.exe"}}).status_code == 422


def test_diagnostics_reports_database_and_mt5(client: TestClient) -> None:
    body = client.get("/api/v1/diagnostics").json()
    assert body["app"]["stage"] == 2
    assert body["patron"]["runtime"]["model_id"] == "patron-1.0.0"
    assert body["database"]["integrity"] == "ok"
    assert "chat_messages" in body["database"]["tables"]
    assert body["mt5"]["package_version"]
    assert body["python"]["version"].startswith("3.")
    assert body["backend"]["port"] == 8000 or body["backend"]["port"] > 0


def test_replay_window_slices_cached_candles(client: TestClient) -> None:
    select_symbol(client)
    body = client.get("/api/v1/replay/window?start=10&count=40").json()
    assert body["total"] > 100
    assert body["start_index"] == 10
    assert len(body["candles"]) == 40
    assert body["ai_available"] is False
    assert "Forecasts page" in body["message"]


def test_market_websocket_sends_initial_state(client: TestClient) -> None:
    with client.websocket_connect("/ws/market") as websocket:
        message = websocket.receive_json()
        assert message["type"] == "hello"
        assert "status" in message["payload"]
        assert "snapshot" in message["payload"]
        assert message["payload"]["forecast"]["ai_available"] is False
        assert message["payload"]["forecast"]["provider"] == "patron"


def test_no_trade_execution_routes_exist(client: TestClient) -> None:
    paths = set(client.get("/openapi.json").json()["paths"])
    forbidden = [path for path in paths if any(token in path for token in ("order", "trade", "position", "buy", "sell"))]
    assert forbidden == []
    assert "/api/v1/mt5/connect" in paths


def test_api_settings_fixture_isolated(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(data_dir=tmp_path / "kbmiti")
    app = create_app(settings=settings, gateway=MT5Gateway(module=FakeMT5()), start_polling=False, configure_logs=False)
    with TestClient(app) as isolated:
        assert isolated.get("/api/v1/health").json()["database"].endswith("kbmti.db")
