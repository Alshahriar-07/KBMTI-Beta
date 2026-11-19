from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import ContainerDep
from app.core.errors import ValidationError
from app.schemas.models import MT5Status, SymbolListResponse

router = APIRouter(prefix="/mt5", tags=["mt5"])


class TerminalSelectionRequest(BaseModel):
    path: str | None = Field(default=None, max_length=1024)


class ConnectionTestRequest(BaseModel):
    terminal_path: str | None = Field(default=None, max_length=1024)
    symbol: str | None = Field(default=None, min_length=1, max_length=64)
    include_history: bool = True


@router.get("/status", response_model=MT5Status)
def mt5_status(container: ContainerDep) -> dict:
    return container.market.mt5_status()


@router.post("/connect", response_model=MT5Status)
def mt5_connect(container: ContainerDep) -> dict:
    return container.market.mt5_connect()


@router.post("/reconnect", response_model=MT5Status)
def mt5_reconnect(container: ContainerDep) -> dict:
    return container.market.mt5_reconnect()


@router.post("/disconnect", response_model=MT5Status)
def mt5_disconnect(container: ContainerDep) -> dict:
    return container.market.mt5_disconnect()


@router.get("/terminal")
def mt5_terminal(container: ContainerDep) -> dict:
    return container.market.terminal_payload()


@router.post("/terminal", response_model=MT5Status)
def mt5_select_terminal(payload: TerminalSelectionRequest, container: ContainerDep) -> dict:
    return container.market.select_terminal(payload.path)


@router.get("/diagnostics")
def mt5_diagnostics(container: ContainerDep) -> dict:
    return container.market.diagnostics()


@router.get("/history-check")
def mt5_history_check(
    container: ContainerDep,
    count: int = Query(default=500, ge=1, le=1500),
) -> dict:
    return container.market.history_check(count=count)


@router.post("/test-connection")
def mt5_test_connection(payload: ConnectionTestRequest, container: ContainerDep) -> dict:
    return container.market.test_connection(
        terminal_path=payload.terminal_path,
        symbol=payload.symbol,
        include_history=payload.include_history,
    )


@router.get("/symbols", response_model=SymbolListResponse)
def mt5_symbols(container: ContainerDep, refresh: bool = Query(default=False)) -> dict:
    return container.market.discover_symbols(refresh=refresh)


@router.get("/symbols/{symbol:path}")
def mt5_symbol_details(symbol: str, container: ContainerDep) -> dict:
    if not symbol or len(symbol) > 64:
        raise ValidationError("A valid symbol name is required.")
    return container.market.symbol_details(symbol)
