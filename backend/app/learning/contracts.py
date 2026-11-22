"""Contracts for the controlled learning and evaluation layer."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SplitName(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"
    PURGED = "PURGED"


class DatasetCase(StrictModel):
    case_id: str
    snapshot_id: str
    data_as_of: AwareDatetime
    symbol: str
    timeframe: str
    split: SplitName
    synthetic: bool = False
    payload: dict = Field(default_factory=dict)


class DatasetAudit(StrictModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    cases: int
    duplicates: int
    train_cases: int
    validation_cases: int
    test_cases: int
    purge_cases: int


class DatasetManifest(StrictModel):
    dataset_id: str
    name: str
    version: str
    manifest_hash: str
    created_at: AwareDatetime
    status: str
    cases: list[DatasetCase]
    audit: DatasetAudit
    summary: dict


class BacktestConfig(StrictModel):
    symbol: str = "BTCUSDT"
    timeframe: str = "M15"
    window_bars: int = Field(default=300, ge=120, le=500)
    max_hold_bars: int = Field(default=8, ge=1, le=96)
    fee_bps: float = Field(default=2.0, ge=0.0, le=100.0)
    spread_bps: float = Field(default=1.0, ge=0.0, le=100.0)
    slippage_bps: float = Field(default=1.0, ge=0.0, le=100.0)
    train_fraction: float = Field(default=0.6, gt=0.0, lt=1.0)
    validation_fraction: float = Field(default=0.2, gt=0.0, lt=1.0)
    purge_bars: int = Field(default=2, ge=0, le=50)
    embargo_bars: int = Field(default=1, ge=0, le=50)
    min_samples: int = Field(default=30, ge=1)
    final_test_sealed: bool = True


class BacktestTrade(StrictModel):
    direction: str
    signal_time: str
    entry_time: str | None = None
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    exit_time: str | None = None
    exit_price: float | None = None
    exit_reason: str
    gross_r: float | None = None
    net_r: float | None = None
    mfe_r: float | None = None
    mae_r: float | None = None
    regime: str
    split: str


class BacktestMetrics(StrictModel):
    trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float | None
    average_win_r: float | None
    average_loss_r: float | None
    total_r: float | None
    by_regime: dict[str, dict]
    by_direction: dict[str, dict]
    sample_warning: str | None


class BacktestReport(StrictModel):
    backtest_id: str
    created_at: AwareDatetime
    status: str
    config: BacktestConfig
    windows: dict
    metrics: BacktestMetrics
    overall: BacktestMetrics
    trades: list[BacktestTrade]
    warnings: list[str]
    evaluation_scope: str
    sealed_test_note: str


class LearningStatus(StrictModel):
    enabled: bool
    datasets: int
    backtests: int
    approved_outcomes: int
    paper_trade_gate: dict
    training_available: bool
    training_reason: str
    execution: Literal["DISABLED"] = "DISABLED"
    generated_at: AwareDatetime


class DatasetPrepareRequest(StrictModel):
    name: str = Field(default="market-intelligence", min_length=1, max_length=80)
    limit: int = Field(default=500, ge=30, le=5000)
    train_fraction: float = Field(default=0.6, gt=0.0, lt=1.0)
    validation_fraction: float = Field(default=0.2, gt=0.0, lt=1.0)
    purge: int = Field(default=2, ge=0, le=50)


class BacktestRequest(StrictModel):
    limit: int = Field(default=400, ge=150, le=2000)
    config: BacktestConfig = Field(default_factory=BacktestConfig)


class ModelVersion(StrictModel):
    model_id: str
    name: str
    status: str
    base_model: str
    artifact_path: str | None
    metrics: dict
    approved_by: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ModelRegisterRequest(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    base_model: str = "Qwen3-4B"
    artifact_path: str | None = None
    metrics: dict = Field(default_factory=dict)
    requested_by: str = "local_operator"


class ModelActionRequest(StrictModel):
    actor: str = Field(min_length=1, max_length=80)
    note: str | None = None


class TrainingJobRequest(StrictModel):
    dataset_id: str
    requested_by: str = "local_operator"
    config: dict = Field(default_factory=dict)
