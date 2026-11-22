from fastapi import APIRouter

from app.api.v1 import (
    analysis,
    chat,
    diagnostics,
    forecast,
    health,
    indicators,
    kie,
    market,
    mt5,
    patron,
    replay,
    risk,
    settings,
    signals,
    strategies,
    system,
    trade_planning,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(mt5.router)
api_router.include_router(market.router)
api_router.include_router(analysis.router)
api_router.include_router(strategies.router)
api_router.include_router(trade_planning.router)
api_router.include_router(risk.router)
api_router.include_router(indicators.router)
api_router.include_router(signals.router)
api_router.include_router(patron.router)
api_router.include_router(forecast.router)
api_router.include_router(chat.router)
api_router.include_router(kie.router)
api_router.include_router(system.router)
api_router.include_router(settings.router)
api_router.include_router(diagnostics.router)
api_router.include_router(replay.router)
