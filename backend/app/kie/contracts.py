"""Stable interfaces of the KIE package.

Everything that crosses a module boundary is declared here: dataclasses for the
request/response shapes, enums for the closed sets of modes and access levels, and
Protocols for the two swappable parts (the inference engine and the tool engine).

Keeping the contracts in one file is what lets ``core`` stay free of llama.cpp,
``model_manager`` stay free of HTTP, and the tests substitute a fake engine without
importing a single DLL.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

# --------------------------------------------------------------------------- modes


class Mode(StrEnum):
    """Answer modes. ``fast`` is the default; ``reasoning`` opts into Qwen3 thinking."""

    FAST = "fast"
    REASONING = "reasoning"


class Access(StrEnum):
    """Tool authorisation level, enforced by the registry (never by the model)."""

    READ = "read"
    WRITE = "write"
    PRIVILEGED = "privileged"


class ModelState(StrEnum):
    """Lifecycle of the single embedded model."""

    DISABLED = "disabled"
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    UNLOADING = "unloading"
    ERROR = "error"


class EventType(StrEnum):
    """Server-sent events produced by a run."""

    START = "start"
    THINKING = "thinking"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class FinishReason(StrEnum):
    STOP = "stop"  # end of generation token
    LENGTH = "length"  # max_tokens reached
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    ERROR = "error"


# --------------------------------------------------------------------------- messages


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class RunRequest:
    """One completed turn requested by the caller."""

    messages: tuple[Message, ...]
    mode: Mode = Mode.FAST
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    thinking: bool | None = None

    @property
    def last_user_text(self) -> str:
        for message in reversed(self.messages):
            if message.role == "user":
                return message.content
        return ""


@dataclass(frozen=True)
class GenerationStats:
    prompt_tokens: int
    completion_tokens: int
    ttft_ms: float
    prompt_ms: float
    decode_ms: float
    total_ms: float
    tok_per_s: float
    prompt_truncated_tokens: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "ttft_ms": round(self.ttft_ms, 2),
            "prompt_ms": round(self.prompt_ms, 2),
            "decode_ms": round(self.decode_ms, 2),
            "total_ms": round(self.total_ms, 2),
            "tok_per_s": round(self.tok_per_s, 2),
            "prompt_truncated_tokens": self.prompt_truncated_tokens,
        }


@dataclass(frozen=True)
class RunResult:
    run_id: str
    text: str
    mode: Mode
    backend: str
    stats: GenerationStats
    finish: FinishReason
    cancelled: bool
    created_at: str
    plan: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "text": self.text,
            "mode": str(self.mode),
            "backend": self.backend,
            "stats": self.stats.as_dict(),
            "finish": str(self.finish),
            "cancelled": self.cancelled,
            "created_at": self.created_at,
            "plan": self.plan,
        }


# --------------------------------------------------------------------------- model info


@dataclass(frozen=True)
class ModelInfo:
    id: str
    file: str
    quantization: str
    size_bytes: int
    n_layer: int
    n_ctx_train: int
    license: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "quantization": self.quantization,
            "size_bytes": self.size_bytes,
            "n_layer": self.n_layer,
            "n_ctx_train": self.n_ctx_train,
            "license": self.license,
        }


@dataclass(frozen=True)
class MemoryBudget:
    """Measured llama.cpp buffer accounting, compared against the configured budget.

    ``measured_mb`` is the sum of the model, KV-cache and compute buffers reported by
    llama.cpp during the last load — not an OS estimate. ``residual_mb`` is the
    Vulkan driver RSS that survives an unload (≈376 MB on this machine, measured in
    Phase A) and is therefore reserved for the whole process lifetime.
    """

    budget_mb: int
    measured_mb: float
    model_mb: float
    kv_mb: float
    compute_mb: float
    offloaded_layers: int
    total_layers: int
    within_budget: bool
    residual_mb: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "budget_mb": self.budget_mb,
            "measured_mb": round(self.measured_mb, 1),
            "model_mb": round(self.model_mb, 1),
            "kv_mb": round(self.kv_mb, 1),
            "compute_mb": round(self.compute_mb, 1),
            "offloaded_layers": self.offloaded_layers,
            "total_layers": self.total_layers,
            "within_budget": self.within_budget,
            "residual_mb": self.residual_mb,
        }


# --------------------------------------------------------------------------- events


@dataclass(frozen=True)
class KieEvent:
    type: EventType
    run_id: str
    seq: int
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"type": str(self.type), "run_id": self.run_id, "seq": self.seq, **self.data}


EventSink = Callable[[KieEvent], None]


# --------------------------------------------------------------------------- tools


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    access: Access = Access.READ
    scopes: tuple[str, ...] = ()
    timeout_s: float = 20.0
    max_result_chars: int = 4000

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "access": str(self.access),
            "scopes": list(self.scopes),
            "timeout_s": self.timeout_s,
            "max_result_chars": self.max_result_chars,
        }


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    ok: bool
    content: str
    duration_ms: float
    error: str | None = None
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "ok": self.ok,
            "content": self.content,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class PlanStep:
    index: int
    kind: str  # "answer" | "tool"
    description: str
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Plan:
    goal: str
    steps: tuple[PlanStep, ...]
    mode: Mode
    max_steps: int = 4

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal[:500],
            "mode": str(self.mode),
            "max_steps": self.max_steps,
            "steps": [
                {
                    "index": step.index,
                    "kind": step.kind,
                    "description": step.description,
                    "tool": step.tool,
                    "arguments": step.arguments,
                }
                for step in self.steps
            ],
        }


# --------------------------------------------------------------------------- ports


@runtime_checkable
class EnginePort(Protocol):
    """The only thing ``ModelManager`` knows about llama.cpp."""

    @property
    def loaded(self) -> bool: ...

    def load(self) -> Any: ...

    def unload(self) -> None: ...

    def shutdown(self) -> None: ...

    def backend_identity(self) -> dict[str, Any]: ...

    def generate(
        self,
        messages: list[dict[str, str]] | None = ...,
        *,
        prompt: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
        top_p: float = ...,
        thinking: bool = ...,
        cancel_event: threading.Event | None = ...,
        on_token: Callable[[str], None] | None = ...,
    ) -> Any: ...


@runtime_checkable
class ToolPort(Protocol):
    def specs(self) -> Sequence[ToolSpec]: ...

    def execute(self, call: ToolCall, *, confirmed: bool = False) -> ToolResult: ...


# --------------------------------------------------------------------------- helpers


def messages_from_dicts(rows: Iterable[dict[str, Any]]) -> tuple[Message, ...]:
    messages: list[Message] = []
    for row in rows:
        role = str(row.get("role") or "").strip().lower()
        content = row.get("content")
        if role not in {"system", "user", "assistant", "tool"} or not isinstance(content, str):
            continue
        if not content.strip():
            continue
        messages.append(Message(role=role, content=content))
    return tuple(messages)
