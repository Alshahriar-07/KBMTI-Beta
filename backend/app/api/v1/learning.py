"""Dataset, backtest and model-registry endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.core.errors import ApiError
from app.learning.contracts import (
    BacktestReport,
    BacktestRequest,
    DatasetManifest,
    DatasetPrepareRequest,
    LearningStatus,
    ModelActionRequest,
    ModelRegisterRequest,
    TrainingJobRequest,
)

router = APIRouter(prefix="/learning", tags=["learning"])


def _service(container):  # noqa: ANN001
    service = container.learning
    if service is None:
        raise ApiError("LEARNING_UNAVAILABLE", "The learning service is unavailable.", 503)
    return service


@router.get("/status", response_model=LearningStatus)
def learning_status(container: ContainerDep) -> LearningStatus:
    return _service(container).status()


@router.post("/datasets/prepare", response_model=DatasetManifest)
def prepare_dataset(container: ContainerDep, request: DatasetPrepareRequest) -> DatasetManifest:
    return _service(container).prepare_dataset(request)


@router.get("/datasets")
def list_datasets(container: ContainerDep, limit: int = Query(default=50, ge=1, le=200)) -> dict:
    return _service(container).datasets(limit)


@router.get("/datasets/{dataset_id}")
def get_dataset(container: ContainerDep, dataset_id: str) -> dict:
    return _service(container).get_dataset(dataset_id)


@router.post("/backtests", response_model=BacktestReport)
def run_backtest(container: ContainerDep, request: BacktestRequest) -> BacktestReport:
    return _service(container).run_backtest(limit=request.limit, config=request.config)


@router.get("/backtests")
def list_backtests(container: ContainerDep, limit: int = Query(default=20, ge=1, le=100)) -> dict:
    return _service(container).backtests(limit)


@router.get("/backtests/{backtest_id}")
def get_backtest(container: ContainerDep, backtest_id: str) -> dict:
    return _service(container).get_backtest(backtest_id)


@router.get("/models")
def list_models(container: ContainerDep) -> dict:
    return _service(container).models()


@router.post("/models")
def register_model(container: ContainerDep, request: ModelRegisterRequest) -> dict:
    return _service(container).register_model(request)


@router.post("/models/{model_id}/promote")
def promote_model(container: ContainerDep, model_id: str, request: ModelActionRequest) -> dict:
    return _service(container).promote_model(model_id, request.actor)


@router.post("/models/rollback")
def rollback_model(container: ContainerDep, request: ModelActionRequest) -> dict:
    return _service(container).rollback_model(request.actor)


@router.get("/jobs")
def list_jobs(container: ContainerDep, limit: int = Query(default=20, ge=1, le=100)) -> dict:
    return _service(container).jobs(limit)


@router.post("/jobs")
def request_job(container: ContainerDep, request: TrainingJobRequest) -> dict:
    return _service(container).request_job(request)


@router.post("/jobs/{job_id}/approve")
def approve_job(container: ContainerDep, job_id: str, request: ModelActionRequest) -> dict:
    return _service(container).approve_job(job_id, request.actor)
