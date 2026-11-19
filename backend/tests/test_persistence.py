from __future__ import annotations

from pathlib import Path

from app.market_data.candles import Candle
from app.persistence.db import Database
from app.persistence.repositories import (
    CandleRepository,
    ChatRepository,
    ForecastRepository,
    SettingsRepository,
    SignalRepository,
    TickRepository,
)


def build(tmp_path: Path) -> tuple[Database, dict]:
    db = Database(tmp_path / "test.db")
    db.initialize()
    repos = {
        "settings": SettingsRepository(db),
        "candles": CandleRepository(db),
        "ticks": TickRepository(db),
        "signals": SignalRepository(db),
        "forecast": ForecastRepository(db),
        "chat": ChatRepository(db),
    }
    return db, repos


def test_settings_roundtrip(tmp_path: Path) -> None:
    _, repos = build(tmp_path)
    settings = repos["settings"]
    assert settings.get("missing", "fallback") == "fallback"
    settings.set("market.symbol", "BTCUSDm")
    settings.set("chart", {"show_ema": False})
    assert settings.get("market.symbol") == "BTCUSDm"
    assert settings.get("chart") == {"show_ema": False}
    assert settings.all()["market.symbol"] == "BTCUSDm"


def test_candle_upsert_and_recent(tmp_path: Path) -> None:
    _, repos = build(tmp_path)
    repo = repos["candles"]
    rows = [
        Candle(time=100, open=1, high=2, low=0.5, close=1.5, tick_volume=10, spread=2),
        Candle(time=200, open=1.5, high=3, low=1, close=2.5, tick_volume=11, spread=2),
    ]
    assert repo.upsert_many("BTCUSDm", "M15", rows) == 2
    repo.upsert_many("BTCUSDm", "M15", [Candle(time=200, open=1.5, high=4, low=1, close=3.5)])
    recent = repo.recent("BTCUSDm", "M15", limit=10)
    assert [row["timestamp_utc"] for row in recent] == [100, 200]
    assert recent[-1]["high"] == 4
    assert repo.count("BTCUSDm", "M15") == 2
    assert repo.delete_before(150) == 1


def test_tick_retention(tmp_path: Path) -> None:
    _, repos = build(tmp_path)
    repo = repos["ticks"]
    repo.insert("BTCUSDm", 1_000, 100.0, 101.0, 100.5)
    repo.insert("BTCUSDm", 2_000, 101.0, 102.0, 101.5)
    assert repo.delete_before(1_500) == 1


def test_signal_history(tmp_path: Path) -> None:
    _, repos = build(tmp_path)
    repo = repos["signals"]
    repo.insert(
        {
            "symbol": "BTCUSDm",
            "timeframe": "M15",
            "timestamp_utc": 1_700_000_000,
            "label": "WAIT",
            "direction": "neutral",
            "score": 0.12,
            "engine": "rule-based-technical-v1",
            "freshness": "fresh",
            "evidence": [{"id": "rsi"}],
            "invalidation": ["close below EMA 21"],
        }
    )
    events = repo.recent(limit=5, symbol="BTCUSDm")
    assert len(events) == 1
    assert events[0]["label"] == "WAIT"
    assert events[0]["invalidation"] == ["close below EMA 21"]
    assert repo.recent(limit=5, symbol="BTCUSD") == []


def test_forecast_run_and_candles(tmp_path: Path) -> None:
    _, repos = build(tmp_path)
    repo = repos["forecast"]
    run_id = repo.insert_run(
        {
            "provider": "test",
            "model_id": "patron-1.0.0",
            "tokenizer_id": None,
            "symbol": "BTCUSDm",
            "timeframe": "M15",
            "created_at": "2026-11-12T00:00:00+00:00",
            "input_last_bar_at": 1_700_000_000,
            "input_candle_count": 512,
            "horizon": 5,
            "latency_ms": 100.5,
            "runtime": "cpu",
            "status": "completed",
            "warnings": ["test warning"],
        }
    )
    repo.insert_candles(
        run_id,
        [
            {"time": 1_700_000_900 + index * 900, "open": 1, "high": 2, "low": 0.5, "close": 1.5}
            for index in range(3)
        ],
    )
    runs = repo.list_runs()
    assert runs[0]["id"] == run_id
    assert runs[0]["warnings"] == ["test warning"]
    detail = repo.get_run(run_id)
    assert detail is not None
    assert len(detail["candles"]) == 3
    assert repo.get_run("missing") is None


def test_chat_conversations_and_messages(tmp_path: Path) -> None:
    _, repos = build(tmp_path)
    repo = repos["chat"]
    conversation = repo.create_conversation("Market check")
    conversation_id = conversation["id"]
    repo.add_message(conversation_id, "user", "What is structure?", {"symbol": "BTCUSDm"})
    assistant = repo.add_message(conversation_id, "assistant", "Structure is ...", {"ai_available": False})

    messages = repo.list_messages(conversation_id)
    assert len(messages) == 2
    assert messages[1]["role"] == "assistant"
    assert messages[1]["context"] == {"ai_available": False}
    assert messages[1]["id"] == assistant["id"]

    listing = repo.list_conversations()
    assert listing[0]["message_count"] == 2

    repo.rename_conversation(conversation_id, "Renamed")
    assert repo.get_conversation(conversation_id)["title"] == "Renamed"  # type: ignore[index]

    repo.clear_messages(conversation_id)
    assert repo.list_messages(conversation_id) == []

    repo.delete_conversation(conversation_id)
    assert repo.get_conversation(conversation_id) is None


def test_database_integrity_and_counts(tmp_path: Path) -> None:
    db, repos = build(tmp_path)
    repos["ticks"].insert("BTCUSDm", 1, 1.0, 2.0, 1.5)
    assert db.integrity_check() == "ok"
    counts = db.table_counts()
    assert counts["market_ticks"] == 1
    assert counts["forecast_runs"] == 0
    assert db.size_bytes() > 0
