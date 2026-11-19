"""KIE Core: the lifecycle of one request.

Responsibilities, in order:

1. register the run so it can be cancelled by id;
2. plan the turn (Planner) and execute it through the bounded workflow;
3. build the prompt (ReasoningEngine) and call the single-flight engine;
4. turn model output into events — thinking spans are separated from the answer, and
   the fast-mode empty block never reaches the caller as visible text;
5. enforce the wall-clock budget, record everything in SQLite, and emit a terminal event.

The core is I/O-free apart from the repository: it never touches DLLs, HTTP or threads
beyond what the engine and the caller supply.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.kie.config import KieConfig
from app.kie.contracts import (
    EventSink,
    EventType,
    FinishReason,
    GenerationStats,
    KieEvent,
    Mode,
    RunRequest,
    RunResult,
)
from app.kie.errors import GenerationFailedError, KieError, PromptTooLongError
from app.kie.model_manager import ModelManager
from app.kie.planner import Planner
from app.kie.reasoning import ReasoningEngine
from app.kie.repository import KieRepository
from app.kie.tools.engine import ToolEngine
from app.kie.workflow import StepOutcome, WorkflowController

logger = logging.getLogger(__name__)

_CLOSE_TAGS = ("</think>", "</think>")
_PREAMBLE_LIMIT = 64


@dataclass
class ActiveRun:
    run_id: str
    cancel_event: threading.Event
    mode: Mode
    started_at: float


class StreamFilter:
    """Split the model's token stream into a thinking phase and an answer.

    Qwen3 always starts with a thinking block. In fast mode that block is empty
    (`` thinking\\n\\n</think>``) and must not reach the user; in reasoning mode the block
    is delivered once as a single ``thinking`` event instead of token-by-token, which
    keeps this filter small and predictable.
    """

    def __init__(self, mode: Mode) -> None:
        self.mode = mode
        self._buffer = ""
        self._in_preamble = True
        self._answer_started = False
        self.answer = ""
        self.thinking = ""

    def _take_answer(self, text: str) -> str | None:
        """Append answer text, dropping the layout whitespace before the first word."""

        if not self._answer_started:
            text = text.lstrip()
            if not text:
                return None
            self._answer_started = True
        self.answer += text
        return text

    def feed(self, piece: str) -> list[tuple[EventType, str]]:
        if not piece:
            return []
        if not self._in_preamble:
            text = self._take_answer(piece)
            return [(EventType.TOKEN, text)] if text else []
        self._buffer += piece
        for tag in _CLOSE_TAGS:
            index = self._buffer.find(tag)
            if index != -1:
                head = self._buffer[:index]
                rest = self._buffer[index + len(tag) :].lstrip()
                self._buffer = ""
                self._in_preamble = False
                events: list[tuple[EventType, str]] = []
                opened = self._open_span(head)
                if opened is None:
                    # The close tag appeared without an opening tag: it is literal text.
                    literal = self._take_answer(head + tag + rest)
                    return [(EventType.TOKEN, literal)] if literal else []
                if opened:
                    self.thinking += opened
                    if self.mode is Mode.REASONING:
                        events.append((EventType.THINKING, opened))
                tail = self._take_answer(rest) if rest else None
                if tail:
                    events.append((EventType.TOKEN, tail))
                return events
        if len(self._buffer) > _PREAMBLE_LIMIT:
            # Not a thinking preamble at all: stream it as the answer.
            self._in_preamble = False
            flushed = self._buffer
            self._buffer = ""
            text = self._take_answer(flushed)
            return [(EventType.TOKEN, text)] if text else []
        return []

    def flush(self) -> list[tuple[EventType, str]]:
        if not self._buffer:
            return []
        pending = self._buffer
        self._buffer = ""
        if not self._in_preamble:
            text = self._take_answer(pending)
            return [(EventType.TOKEN, text)] if text else []
        self._in_preamble = False
        opened = self._open_span(pending)
        if opened is None:
            # No thinking tag at all: the buffer is the answer.
            text = self._take_answer(pending)
            return [(EventType.TOKEN, text)] if text else []
        if opened and self.mode is Mode.REASONING:
            self.thinking += opened
            return [(EventType.THINKING, opened)]
        # An unterminated thinking block in fast mode is dropped: it is not an answer.
        return []

    @staticmethod
    def _open_span(head: str) -> str | None:
        """Return the reasoning text if ``head`` is a thinking block, else ``None``."""

        text = head.strip()
        if text.startswith("<"):
            close = text.find(">")
            if close == -1:
                return None
            tag = text[1:close].strip().lower()
            # Accept the ``<think>`` and ``<thinking>`` spellings used by Qwen3 templates.
            if tag in {"think", "thinking"}:
                return text[close + 1 :].strip()
            return None
        lower = text.lower()
        for prefix in ("think", "thinking"):
            if lower.startswith(prefix):
                return text[len(prefix) :].strip()
        return None


class KieCore:
    def __init__(
        self,
        manager: ModelManager,
        reasoning: ReasoningEngine,
        planner: Planner,
        workflow: WorkflowController,
        repository: KieRepository,
        config: KieConfig,
        *,
        tools: ToolEngine | None = None,
    ) -> None:
        self.manager = manager
        self.reasoning = reasoning
        self.planner = planner
        self.workflow = workflow
        self.repository = repository
        self.config = config
        self.tools = tools
        self._lock = threading.RLock()
        self._active: dict[str, ActiveRun] = {}

    # ------------------------------------------------------------------ control
    def cancel(self, run_id: str) -> bool:
        with self._lock:
            active = self._active.get(run_id)
        if active is None:
            return False
        active.cancel_event.set()
        return True

    def cancel_all(self) -> int:
        with self._lock:
            runs = list(self._active.values())
        for run in runs:
            run.cancel_event.set()
        return len(runs)

    @property
    def active_run_id(self) -> str | None:
        with self._lock:
            return next(iter(self._active), None)

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = [
                {"run_id": run.run_id, "mode": str(run.mode), "started_at": run.started_at}
                for run in self._active.values()
            ]
        return {"active_runs": active, "queue": self.manager.queue}

    # ---------------------------------------------------------------------- run
    def run(
        self,
        request: RunRequest,
        *,
        context: dict[str, Any] | None = None,
        on_event: EventSink | None = None,
    ) -> RunResult:
        run_id = uuid.uuid4().hex
        cancel_event = threading.Event()
        started_at = time.time()
        active = ActiveRun(run_id=run_id, cancel_event=cancel_event, mode=request.mode, started_at=started_at)
        seq = 0

        def emit(event_type: EventType, data: dict[str, Any]) -> None:
            nonlocal seq
            if on_event is None:
                return
            seq += 1
            try:
                on_event(KieEvent(type=event_type, run_id=run_id, seq=seq, data=data))
            except Exception:  # noqa: BLE001 - a broken consumer must not kill the run
                logger.debug("KIE event sink raised", exc_info=True)

        with self._lock:
            self._active[run_id] = active

        backend = self.manager.backend or "unknown"
        model_id = (self.manager.status().get("model") or {}).get("description")
        prompt_spec = None
        plan = None
        filtered = StreamFilter(request.mode)
        deadline = time.monotonic() + self.config.generation_timeout_seconds
        timed_out = False
        report = None

        try:
            self.repository.start_run(
                run_id,
                mode=str(request.mode),
                backend=backend,
                model=model_id,
                request_chars=len(request.last_user_text),
            )
            prompt_spec = self.reasoning.build(request, context)
            filtered = StreamFilter(prompt_spec.mode)
            emit(
                EventType.START,
                {
                    "mode": str(prompt_spec.mode),
                    "backend": backend,
                    "model": model_id,
                    "max_tokens": prompt_spec.max_tokens,
                    "thinking": prompt_spec.thinking,
                    "context": bool(context),
                },
            )

            plan = self.planner.plan(
                request.last_user_text,
                mode=prompt_spec.mode,
                tools=list(self.tools.registry.specs()) if self.tools else None,
            )

            def on_token(piece: str) -> None:
                nonlocal timed_out
                if time.monotonic() > deadline:
                    timed_out = True
                    cancel_event.set()
                if cancel_event.is_set():
                    return
                for event_type, text in filtered.feed(piece):
                    if event_type is EventType.THINKING:
                        emit(EventType.THINKING, {"text": text})
                    else:
                        emit(EventType.TOKEN, {"text": text})

            def execute(step) -> StepOutcome:
                result = self.manager.generate(
                    messages=[dict(message) for message in prompt_spec.messages],
                    max_tokens=prompt_spec.max_tokens,
                    temperature=prompt_spec.temperature,
                    top_p=prompt_spec.top_p,
                    thinking=prompt_spec.thinking,
                    cancel_event=cancel_event,
                    on_token=on_token,
                )
                return StepOutcome(index=step.index, kind=step.kind, ok=True, output=getattr(result, "text", ""), meta={"report": result})

            workflow_result = self.workflow.run(plan, execute, cancel_event=cancel_event)
            for outcome in workflow_result.outcomes:
                if outcome.meta.get("report") is not None:
                    report = outcome.meta["report"]

            if workflow_result.cancelled or cancel_event.is_set() or (report is not None and getattr(report, "cancelled", False)):
                raise _CancelledRun()
            if not workflow_result.ok:
                raise GenerationFailedError(
                    "The KIE workflow stopped before producing an answer.",
                    {"reason": workflow_result.aborted_reason},
                )

            for event_type, text in filtered.flush():
                if event_type is EventType.THINKING:
                    emit(EventType.THINKING, {"text": text})
                else:
                    emit(EventType.TOKEN, {"text": text})
        except _CancelledRun:
            finish = FinishReason.TIMEOUT if timed_out else FinishReason.CANCELLED
            stats = self._stats(report, filtered, prompt_spec.max_tokens if prompt_spec else 0)
            text = self.reasoning.postprocess(filtered.answer, prompt_spec.mode if prompt_spec else request.mode)
            self.repository.finish_run(
                run_id,
                status="cancelled",
                finish=str(finish),
                cancelled=True,
                prompt_tokens=stats.prompt_tokens,
                completion_tokens=stats.completion_tokens,
                ttft_ms=stats.ttft_ms,
                tok_per_s=stats.tok_per_s,
                total_ms=stats.total_ms,
                prompt_truncated=stats.prompt_truncated_tokens,
                answer_chars=len(text),
                error="timeout" if timed_out else "cancelled",
            )
            emit(
                EventType.CANCELLED,
                {"text": text, "finish": str(finish), "stats": stats.as_dict(), "backend": backend},
            )
            return RunResult(
                run_id=run_id,
                text=text,
                mode=prompt_spec.mode if prompt_spec else request.mode,
                backend=backend,
                stats=stats,
                finish=finish,
                cancelled=True,
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)),
                plan=plan.as_dict() if plan is not None else {},
            )
        except KieError as exc:
            self.repository.finish_run(run_id, status="error", error=f"{exc.code}: {exc.message}")
            emit(EventType.ERROR, {"code": exc.code, "message": exc.message})
            raise
        except Exception as exc:  # noqa: BLE001 - unexpected engine failure
            logger.exception("KIE run %s failed", run_id)
            wrapped = GenerationFailedError(f"KIE generation failed: {exc}", {"run_id": run_id})
            self.repository.finish_run(run_id, status="error", error=str(exc))
            emit(EventType.ERROR, {"code": wrapped.code, "message": wrapped.message})
            raise wrapped from exc
        finally:
            with self._lock:
                self._active.pop(run_id, None)

        assert prompt_spec is not None and report is not None
        stats = self._stats(report, filtered, prompt_spec.max_tokens)
        text = self.reasoning.postprocess(filtered.answer, prompt_spec.mode)
        finish = FinishReason.LENGTH if getattr(report, "finish", "") == "length" else FinishReason.STOP
        plan_dict = plan.as_dict() if plan is not None else {}

        self.repository.finish_run(
            run_id,
            status="done",
            finish=str(finish),
            prompt_tokens=stats.prompt_tokens,
            completion_tokens=stats.completion_tokens,
            ttft_ms=stats.ttft_ms,
            tok_per_s=stats.tok_per_s,
            total_ms=stats.total_ms,
            prompt_truncated=stats.prompt_truncated_tokens,
            answer_chars=len(text),
        )
        emit(
            EventType.DONE,
            {
                "text": text,
                "finish": str(finish),
                "stats": stats.as_dict(),
                "backend": backend,
                "plan": plan_dict,
            },
        )
        return RunResult(
            run_id=run_id,
            text=text,
            mode=prompt_spec.mode,
            backend=backend,
            stats=stats,
            finish=finish,
            cancelled=False,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)),
            plan=plan_dict,
        )

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _stats(report: Any, filtered: StreamFilter, max_tokens: int) -> GenerationStats:
        if report is None:
            return GenerationStats(
                prompt_tokens=0,
                completion_tokens=0,
                ttft_ms=0.0,
                prompt_ms=0.0,
                decode_ms=0.0,
                total_ms=0.0,
                tok_per_s=0.0,
            )
        total_ms = float(getattr(report, "total_ms", 0.0) or 0.0)
        completion = int(getattr(report, "generated_tokens", 0) or 0)
        decode_ms = float(getattr(report, "decode_ms", 0.0) or 0.0)
        tok_per_s = float(getattr(report, "decode_tok_per_s", 0.0) or 0.0)
        return GenerationStats(
            prompt_tokens=int(getattr(report, "prompt_tokens", 0) or 0),
            completion_tokens=completion,
            ttft_ms=float(getattr(report, "ttft_ms", 0.0) or 0.0),
            prompt_ms=float(getattr(report, "prompt_ms", 0.0) or 0.0),
            decode_ms=decode_ms,
            total_ms=total_ms,
            tok_per_s=tok_per_s,
            prompt_truncated_tokens=int(getattr(report, "prompt_truncated_tokens", 0) or 0),
        )


class _CancelledRun(Exception):
    """Internal signal: the run was cancelled or hit its wall-clock budget."""


def validate_prompt_budget(core: KieCore, request: RunRequest) -> None:
    """Fail fast when the conversation alone cannot fit the context.

    The runtime truncates the prompt tail, which silently drops the oldest turns. That is
    acceptable for a long chat, but a single oversized message is a client error and is
    reported as ``PROMPT_TOO_LONG`` instead of being answered from a truncated question.
    """

    limit = core.config.n_ctx - core.config.hard_max_tokens
    tokens = core.manager.count_tokens(request.last_user_text)
    if tokens is not None and tokens > limit:
        raise PromptTooLongError(
            f"The message needs {tokens} tokens but only {limit} fit in the context budget.",
            {"request_tokens": tokens, "limit_tokens": limit, "n_ctx": core.config.n_ctx},
        )
