"""Composition root: builds every service once per application process."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from app.analysis.service import AnalysisService
from app.analysis.sources import BinanceCandleSource, FallbackCandleSource, RepositoryCandleSource
from app.chat.service import ChatService
from app.core.config import Settings
from app.forecasting.automation import ForecastAutomation
from app.forecasting.patron_provider import PatronForecastProvider
from app.forecasting.service import ForecastService
from app.kie.responder import KieResponder
from app.kie.service import KieService
from app.market_data.binance_history import BinanceHistoryClient
from app.market_data.broadcaster import Broadcaster
from app.market_data.manager import MarketDataService
from app.market_data.mt5_gateway import MT5Gateway
from app.market_data.providers.binance import BinanceMarketDataProvider
from app.market_data.service import MT5MarketDataProvider
from app.patron.service import PatronInferenceService
from app.persistence.db import Database
from app.persistence.repositories import (
    CandleRepository,
    ChatRepository,
    ForecastRepository,
    MarketSnapshotRepository,
    SettingsRepository,
    SignalRepository,
    TickRepository,
)
from app.signals.service import SignalService
from app.system.monitor import SystemMonitor

logger = logging.getLogger(__name__)


@dataclass
class AppContainer:
    settings: Settings
    db: Database
    gateway: MT5Gateway
    broadcaster: Broadcaster
    settings_repo: SettingsRepository
    candle_repo: CandleRepository
    tick_repo: TickRepository
    signal_repo: SignalRepository
    forecast_repo: ForecastRepository
    chat_repo: ChatRepository
    market: MarketDataService
    binance: BinanceMarketDataProvider
    binance_history: BinanceHistoryClient
    mt5: MT5MarketDataProvider
    patron: PatronInferenceService
    signals: SignalService
    forecast: ForecastService
    forecast_automation: ForecastAutomation
    chat: ChatService
    kie: KieService
    analysis: AnalysisService | None
    system: SystemMonitor
    started_at: float
    log_file: Path | None = None

    @property
    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_at)


def build_container(
    settings: Settings,
    gateway: MT5Gateway | None = None,
    binance: BinanceMarketDataProvider | None = None,
    binance_history: BinanceHistoryClient | None = None,
    patron: PatronInferenceService | None = None,
    kie: KieService | None = None,
    analysis: AnalysisService | None = None,
) -> AppContainer:
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.initialize()

    settings_repo = SettingsRepository(db)
    candle_repo = CandleRepository(db)
    tick_repo = TickRepository(db)
    signal_repo = SignalRepository(db)
    forecast_repo = ForecastRepository(db)
    chat_repo = ChatRepository(db)

    broadcaster = Broadcaster()
    # The optional MT5 session must never publish into the active-provider stream.
    # Its direct status endpoints remain available; the manager owns the UI stream.
    mt5_broadcaster = Broadcaster()
    mt5_gateway = gateway or MT5Gateway()
    mt5_provider = MT5MarketDataProvider(
        settings=settings,
        gateway=mt5_gateway,
        candles_repo=candle_repo,
        ticks_repo=tick_repo,
        settings_repo=settings_repo,
        broadcaster=mt5_broadcaster,
    )
    binance_provider = binance or BinanceMarketDataProvider(
        settings=settings,
        settings_repo=settings_repo,
        candles_repo=candle_repo,
        ticks_repo=tick_repo,
    )
    market = MarketDataService(
        settings=settings,
        settings_repo=settings_repo,
        binance=binance_provider,
        mt5=mt5_provider,
        broadcaster=broadcaster,
    )
    binance_history = binance_history or BinanceHistoryClient(settings)
    patron = patron or PatronInferenceService(settings)
    # Market intelligence is optional exactly like KIE: a construction failure must
    # degrade the analysis endpoints, never prevent the application from starting.
    if analysis is None:
        try:
            analysis = AnalysisService(
                source=FallbackCandleSource(
                    BinanceCandleSource(binance_history),
                    RepositoryCandleSource(candle_repo, source="binance"),
                ),
                repository=MarketSnapshotRepository(db),
                settings=settings,
            )
        except Exception:  # pragma: no cover - construction is intentionally defensive
            logger.exception("Market analysis failed to initialize; continuing without it")
            analysis = None
    signals = SignalService(market=market, repository=signal_repo, settings=settings)
    forecast = ForecastService(
        provider=PatronForecastProvider(patron=patron, history=binance_history, settings=settings),
        repository=forecast_repo,
        history=binance_history,
    )
    def latest_binance_bar() -> int | None:
        # This is a memory read on the provider that owns the live Binance
        # stream. It lets recovery avoid a REST call when no bar has changed.
        if market.provider_id != "binance":
            return None
        candles = binance_provider.completed_candles(force=False)
        return int(candles[-1].time) if candles else None

    forecast_automation = ForecastAutomation(
        forecast=forecast,
        repository=forecast_repo,
        settings=settings,
        latest_bar=latest_binance_bar,
    )
    forecast.automation_status = forecast_automation.status
    forecast.set_event_sink(lambda event: broadcaster.publish(event))

    def route_binance_event(event: dict) -> None:
        """Publish live frames and wake the forecast scheduler on close."""

        if market.provider_id != "binance":
            return
        broadcaster.publish(event)
        if event.get("type") != "candle":
            return
        payload = event.get("payload") or {}
        if (
            payload.get("closed")
            and payload.get("symbol") == "BTCUSDT"
            and payload.get("timeframe") == "M15"
        ):
            candle = payload.get("candle") or {}
            forecast_automation.notify_closed(
                int(candle.get("time") or 0),
                received_at=payload.get("received_at"),
            )

    binance_provider.subscribe(route_binance_event)
    # KIE is constructed but not loaded: no model is touched until /kie/load (or autoload).
    # When it is disabled or the artifacts are missing it still exists and reports a
    # degraded status, so no caller has to special-case its absence.
    kie_service = kie or KieService(db=db)
    chat = ChatService(
        repository=chat_repo,
        market=market,
        signals=signals,
        forecast=forecast,
        patron=patron,
        # Dark by default (Phase B): /chat stays byte-compatible with the rules engine.
        responder=KieResponder(kie_service) if kie_service.config.chat_responder else None,
    )

    return AppContainer(
        settings=settings,
        db=db,
        gateway=mt5_gateway,
        broadcaster=broadcaster,
        settings_repo=settings_repo,
        candle_repo=candle_repo,
        tick_repo=tick_repo,
        signal_repo=signal_repo,
        forecast_repo=forecast_repo,
        chat_repo=chat_repo,
        market=market,
        binance=binance_provider,
        binance_history=binance_history,
        mt5=mt5_provider,
        patron=patron,
        signals=signals,
        forecast=forecast,
        forecast_automation=forecast_automation,
        chat=chat,
        kie=kie_service,
        analysis=analysis,
        system=SystemMonitor(),
        started_at=time.time(),
    )
