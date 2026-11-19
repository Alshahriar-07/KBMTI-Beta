"""KIE errors mapped onto the backend's stable API error envelope.

Every failure mode of the engine is expressed as one of these so the HTTP layer never
has to guess a status code, and so the UI can distinguish "model not loaded yet" from
"busy" from "budget exceeded" without parsing prose.
"""

from __future__ import annotations

from typing import Any

from app.core.errors import ApiError


class KieError(ApiError):
    """Base class for KIE failures (always reported through the standard envelope).

    ``retryable`` tells the workflow controller whether re-running the step could help.
    A busy queue or an unloaded model will not fix itself inside one request, so these
    propagate unchanged instead of being flattened into a generic step failure.
    """

    retryable = False


class KieDisabledError(KieError):
    def __init__(self, message: str = "KIE is disabled by configuration.") -> None:
        super().__init__("KIE_DISABLED", message, 503)


class KieValidationError(KieError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("KIE_VALIDATION_ERROR", message, 422, details)


class ModelNotLoadedError(KieError):
    def __init__(self, message: str = "The KIE model is not loaded. Call POST /api/v1/kie/load first.") -> None:
        super().__init__("MODEL_NOT_LOADED", message, 503)


class ModelLoadingError(KieError):
    def __init__(self, message: str = "The KIE model is still loading.", retry_after_s: float | None = None) -> None:
        details: dict[str, Any] = {}
        if retry_after_s is not None:
            details["retry_after_s"] = round(float(retry_after_s), 1)
        super().__init__("MODEL_LOADING", message, 503, details)


class ModelLoadFailedError(KieError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("MODEL_LOAD_FAILED", message, 503, details)


class KieBusyError(KieError):
    """The single inference slot is occupied and the bounded queue is full/timed out."""

    def __init__(self, message: str, queue_depth: int, max_queue: int) -> None:
        super().__init__(
            "KIE_BUSY",
            message,
            429,
            {"queue_depth": queue_depth, "max_queue": max_queue},
        )


class KieMemoryBudgetError(KieError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("KIE_MEMORY_BUDGET", message, 507, details)


class PromptTooLongError(KieError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("PROMPT_TOO_LONG", message, 422, details)


class RunNotFoundError(KieError):
    def __init__(self, run_id: str) -> None:
        super().__init__("RUN_NOT_FOUND", f"No KIE run with id {run_id}.", 404, {"run_id": run_id})


class ToolNotFoundError(KieError):
    def __init__(self, name: str, available: list[str] | None = None) -> None:
        super().__init__(
            "TOOL_NOT_FOUND",
            f"Unknown tool '{name}'. The registry is a closed allow-list.",
            404,
            {"tool": name, "available": sorted(available or [])},
        )


class ToolArgumentsError(KieError):
    def __init__(self, name: str, errors: list[str]) -> None:
        super().__init__(
            "TOOL_ARGUMENTS_INVALID",
            f"Arguments for '{name}' do not match its schema.",
            422,
            {"tool": name, "errors": errors},
        )


class ToolAccessError(KieError):
    def __init__(self, name: str, access: str, reason: str) -> None:
        super().__init__(
            "TOOL_FORBIDDEN",
            f"Tool '{name}' is not callable in this session: {reason}",
            403,
            {"tool": name, "access": access},
        )


class ToolTimeoutError(KieError):
    def __init__(self, name: str, timeout_s: float) -> None:
        super().__init__(
            "TOOL_TIMEOUT",
            f"Tool '{name}' exceeded its {timeout_s:.0f}s budget.",
            504,
            {"tool": name, "timeout_s": timeout_s},
        )


class GenerationFailedError(KieError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("KIE_GENERATION_FAILED", message, 500, details)
