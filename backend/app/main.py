"""FastAPI application factory for the local KBMTI backend."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.analysis.service import AnalysisService
from app.api.v1.router import api_router
from app.api.ws import ws_router
from app.container import AppContainer, build_container
from app.core.config import APP_NAME, APP_VERSION, STAGE, Settings, get_settings
from app.core.errors import ApiError
from app.core.logging import configure_logging
from app.intelligence.service import IntelligenceService
from app.kie.runtime.openmp_compat import configure_windows_openmp_compat
from app.learning.service import LearningService
from app.market_data.binance_history import BinanceHistoryClient
from app.market_data.mt5_gateway import MT5Gateway
from app.market_data.providers.binance import BinanceMarketDataProvider
from app.outcomes.service import OutcomeService
from app.patron.service import PatronInferenceService
from app.risk.service import RiskService
from app.strategies.service import StrategyService
from app.trade_journal.service import JournalService
from app.trade_planning.service import TradePlanningService

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.kie.service import KieService

logger = logging.getLogger(__name__)

_REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def _request_id(value: str | None) -> str:
    """Accept a safe correlation id from a trusted local client, else mint one."""

    candidate = (value or "").strip()
    return candidate if _REQUEST_ID_RE.fullmatch(candidate) else uuid.uuid4().hex


def _request_id_from(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def create_app(
    settings: Settings | None = None,
    gateway: MT5Gateway | None = None,
    binance: BinanceMarketDataProvider | None = None,
    binance_history: BinanceHistoryClient | None = None,
    patron: PatronInferenceService | None = None,
    kie: KieService | None = None,
    analysis: AnalysisService | None = None,
    strategies: StrategyService | None = None,
    risk: RiskService | None = None,
    trade_planning: TradePlanningService | None = None,
    journal: JournalService | None = None,
    outcomes: OutcomeService | None = None,
    intelligence: IntelligenceService | None = None,
    learning: LearningService | None = None,
    start_polling: bool = True,
    configure_logs: bool = True,
) -> FastAPI:
    resolved = settings or get_settings()
    resolved.ensure_dirs()
    log_file: Path = configure_logging(resolved.log_dir) if configure_logs else resolved.log_dir / "kbmti-backend.log"
    container: AppContainer = build_container(
        resolved,
        gateway=gateway,
        binance=binance,
        binance_history=binance_history,
        patron=patron,
        kie=kie,
        analysis=analysis,
        strategies=strategies,
        risk=risk,
        trade_planning=trade_planning,
        journal=journal,
        outcomes=outcomes,
        intelligence=intelligence,
        learning=learning,
    )
    container.log_file = log_file
    if resolved.patron_enabled and container.kie.enabled:
        # Both workloads are enabled in this process. Set the compatibility guard
        # before either OpenMP runtime is initialized; the failure mode is a native
        # abort with no Python traceback (the old HTTP 502).
        configure_windows_openmp_compat()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Production startup is licensed. The test suite constructs the app with
        # start_polling=False and bypasses the network-bound startup gate.
        if start_polling:
            from app.launch_guard import enforce

            application.state.license = enforce()
        container.broadcaster.bind_loop(asyncio.get_running_loop())
        task: asyncio.Task | None = None
        if start_polling:
            task = asyncio.create_task(container.market.run(), name="kbmti-market-poll")
            logger.info("KBMTI backend ready on %s:%s", resolved.host, resolved.port)
        if resolved.patron_autoload and start_polling:
            container.patron.start_background_load()
        if start_polling:
            # The loop waits for PATRON readiness and only forecasts on closed
            # 15m bars; it never regenerates on individual ticks.
            container.forecast_automation.start()
        # KIE is optional: a missing model or a dead GPU driver must never stop KBMTI.
        try:
            container.kie.startup()
        except Exception:  # pragma: no cover - defensive
            logger.exception("KIE startup failed; continuing without it")
        yield
        try:
            container.kie.shutdown()
        except Exception:  # pragma: no cover - shutdown is best effort
            logger.warning("KIE shutdown failed", exc_info=True)
        container.forecast_automation.stop()
        container.patron.shutdown()
        container.market.stop()
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pragma: no cover - shutdown path
                pass

    application = FastAPI(
        title=f"{APP_NAME} API",
        version=APP_VERSION,
        description=(
            "KBMTI local market intelligence API. Binance (default) or MetaTrader 5 read-only "
            "market data, indicators, rule-based technical bias, PATRON probabilistic forecasts "
            "and a PATRON-grounded deterministic assistant. No order execution."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    application.state.container = container
    application.state.log_file = log_file
    application.state.stage = STAGE

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def limit_request_size(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method in {"POST", "PUT", "PATCH"}:
            raw_length = request.headers.get("content-length")
            try:
                declared = int(raw_length) if raw_length is not None else None
            except ValueError:
                declared = None
            if declared is not None and declared > resolved.max_request_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "REQUEST_TOO_LARGE",
                            "message": f"Request bodies are limited to {resolved.max_request_bytes} bytes.",
                            "details": {"limit": resolved.max_request_bytes},
                            "request_id": _request_id_from(request),
                        }
                    },
                )
        return await call_next(request)

    @application.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Attach one correlation id to logs and to every HTTP response."""

        request.state.request_id = _request_id(request.headers.get(_REQUEST_ID_HEADER))
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "http_request_failed request_id=%s method=%s path=%s",
                request.state.request_id,
                request.method,
                request.url.path,
            )
            raise
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
        response.headers[_REQUEST_ID_HEADER] = request.state.request_id
        logger.info(
            "http_request request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @application.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": _request_id_from(request),
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request did not match the documented API contract.",
                    "details": {"errors": exc.errors()},
                    "request_id": _request_id_from(request),
                }
            },
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Never leak a traceback or turn an internal failure into a fake success."""

        logger.exception(
            "unhandled_exception request_id=%s method=%s path=%s",
            _request_id_from(request),
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "The backend failed while processing this request.",
                    "details": {},
                    "request_id": _request_id_from(request),
                }
            },
        )

    @application.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "stage": STAGE,
            "docs": "/docs",
            "health": "/api/v1/health",
            "note": (
                "Read-only market intelligence with PATRON forecasts. "
                "No trading or order execution endpoints exist."
            ),
        }

    application.include_router(api_router)
    application.include_router(ws_router)
    return application
