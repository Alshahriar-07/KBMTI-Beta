"""``/api/v1/kie`` — additive namespace for the embedded intelligence engine.

Nothing here is used by ``/api/v1/chat/*``: that endpoint keeps its existing behaviour and
its existing responder. KIE is reachable only through these routes (and, opt-in, through
``KieResponder`` assigned in the container).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import ContainerDep
from app.kie.errors import ModelNotLoadedError
from app.kie.service import parse_run_request

router = APIRouter(prefix="/kie", tags=["kie"])


class KieMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=4000)


class KieChatRequest(BaseModel):
    message: str | None = Field(default=None, max_length=4000)
    messages: list[KieMessage] | None = Field(default=None, max_length=32)
    mode: Literal["fast", "reasoning"] | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=1024)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    thinking: bool | None = None
    # Optional, already-assembled market context (the UI passes what it already shows).
    context: dict[str, Any] | None = None


class CancelRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=64)


def _service(container: Any):
    kie = getattr(container, "kie", None)
    if kie is None:  # pragma: no cover - the container always builds one
        from app.kie.errors import KieDisabledError

        raise KieDisabledError("KIE is not wired into this build.")
    return kie


@router.get("/status")
def status(container: ContainerDep) -> dict:
    return _service(container).status()


@router.get("/models")
def models(container: ContainerDep) -> dict:
    return _service(container).models()


@router.get("/tools")
def tools(container: ContainerDep) -> dict:
    return _service(container).tool_specs()


@router.post("/load")
def load(container: ContainerDep) -> dict:
    return _service(container).load()


@router.post("/unload")
def unload(container: ContainerDep) -> dict:
    return _service(container).unload()


@router.post("/chat")
def chat(payload: KieChatRequest, container: ContainerDep) -> dict:
    service = _service(container)
    request = parse_run_request(
        messages=[message.model_dump() for message in payload.messages] if payload.messages else None,
        message=payload.message,
        mode=payload.mode,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
        top_p=payload.top_p,
        thinking=payload.thinking,
    )
    return service.chat(request, context=payload.context)


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
def chat_stream(payload: KieChatRequest, container: ContainerDep) -> StreamingResponse:
    service = _service(container)
    request = parse_run_request(
        messages=[message.model_dump() for message in payload.messages] if payload.messages else None,
        message=payload.message,
        mode=payload.mode,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
        top_p=payload.top_p,
        thinking=payload.thinking,
    )
    # Fail before the stream starts: an SSE connection that immediately reports
    # "model not loaded" is worse than a normal 503 for every client.
    if not service.ready:
        raise ModelNotLoadedError()

    def generate() -> Iterator[str]:
        for event in service.stream_events(request, context=payload.context):
            yield _sse(event.as_dict())
        if False:  # pragma: no cover - keeps the generator type explicit
            yield ""

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/cancel")
def cancel(payload: CancelRequest, container: ContainerDep) -> dict:
    return _service(container).cancel(payload.run_id)


@router.get("/runs")
def runs(container: ContainerDep, limit: int = 20) -> dict:
    return _service(container).recent_runs(max(1, min(limit, 200)))


@router.get("/runs/{run_id}")
def run(run_id: str, container: ContainerDep) -> dict:
    return _service(container).run(run_id)


__all__ = ["router"]
