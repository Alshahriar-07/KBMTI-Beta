"""KieService: the facade used by the container, HTTP routes and the chat responder.

It owns the objects that must exist once per process (model manager, core, planners) and
turns their state into plain dictionaries for the API. Nothing here raises on import or
construction: KIE is optional, and a machine without the model artifacts must still start
KBMTI and report a degraded KIE status.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Iterator
from typing import Any

from app.kie.config import KieConfig, load_config
from app.kie.contracts import (
    EventType,
    KieEvent,
    Mode,
    RunRequest,
    messages_from_dicts,
)
from app.kie.core import KieCore, validate_prompt_budget
from app.kie.errors import (
    KieDisabledError,
    KieValidationError,
    ModelNotLoadedError,
    RunNotFoundError,
)
from app.kie.model_manager import ModelManager
from app.kie.planner import Planner
from app.kie.reasoning import ReasoningEngine
from app.kie.repository import KieRepository
from app.kie.tools.engine import ToolEngine
from app.kie.tools.registry import ToolRegistry
from app.kie.workflow import WorkflowController
from app.persistence.db import Database

logger = logging.getLogger(__name__)

MAX_MESSAGES = 32
MAX_MESSAGE_CHARS = 4000


def parse_run_request(
    *,
    messages: list[dict[str, Any]] | None = None,
    message: str | None = None,
    mode: Mode | str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    thinking: bool | None = None,
) -> RunRequest:
    """Validate the caller's input and build the engine-neutral request."""

    rows = list(messages or [])
    if message is not None:
        rows.append({"role": "user", "content": message})
    if not rows:
        raise KieValidationError("Provide either 'message' or 'messages'.")
    if len(rows) > MAX_MESSAGES:
        raise KieValidationError(f"At most {MAX_MESSAGES} messages per request.")
    for row in rows:
        content = row.get("content")
        if isinstance(content, str) and len(content) > MAX_MESSAGE_CHARS:
            raise KieValidationError(f"Each message is limited to {MAX_MESSAGE_CHARS} characters.")
    parsed = messages_from_dicts(rows)
    if not parsed:
        raise KieValidationError("No usable message was supplied (role must be system/user/assistant/tool).")
    if not any(item.role == "user" for item in parsed):
        raise KieValidationError("At least one user message is required.")
    if mode is None:
        parsed_mode = Mode.FAST
    else:
        try:
            parsed_mode = Mode(str(mode))
        except ValueError as exc:
            raise KieValidationError(
                "mode must be 'fast' or 'reasoning'.", {"mode": str(mode)}
            ) from exc
    return RunRequest(
        messages=parsed,
        mode=parsed_mode,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        thinking=thinking,
    )


class _NoopRepository:
    """Stand-in when KIE is constructed without a database (tests, tooling)."""

    def start_run(self, *args: Any, **kwargs: Any) -> None: ...
    def finish_run(self, *args: Any, **kwargs: Any) -> None: ...
    def record_tool_call(self, *args: Any, **kwargs: Any) -> None: ...
    def tool_calls(self, run_id: str) -> list[dict[str, Any]]:
        return []

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return None

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return []


class KieService:
    def __init__(
        self,
        config: KieConfig | None = None,
        *,
        db: Database | None = None,
        repository: Any | None = None,
        manager: ModelManager | None = None,
        engine_factory=None,
    ) -> None:
        self.config = config or load_config()
        self.manager = manager or ModelManager(self.config, engine_factory=engine_factory)
        self.registry = ToolRegistry()
        self.tools = ToolEngine(self.registry)
        self.repository = repository or (KieRepository(db) if db is not None else _NoopRepository())
        self.reasoning = ReasoningEngine(self.config)
        self.planner = Planner(self.config)
        # No retries on the answer step: re-running inference would double the cost and
        # hide a real engine failure. Tool retries live in the workflow for Phase C.
        self.workflow = WorkflowController(max_attempts=1)
        self.core = KieCore(
            self.manager,
            self.reasoning,
            self.planner,
            self.workflow,
            self.repository,
            self.config,
            tools=self.tools,
        )
        self._load_thread: threading.Thread | None = None
        self._last_load_error: str | None = None

    # ------------------------------------------------------------------ lifecycle
    def startup(self) -> None:
        """Optionally warm the model in the background; never blocks or raises."""

        if not self.config.enabled or not self.config.autoload:
            return
        if self._load_thread is not None and self._load_thread.is_alive():
            return

        def warm() -> None:
            try:
                self.manager.load()
                logger.info("KIE model loaded in the background")
            except Exception as exc:  # noqa: BLE001 - autoload must never crash startup
                self._last_load_error = str(exc)
                logger.warning("KIE autoload failed: %s", exc)

        self._load_thread = threading.Thread(target=warm, name="kie-autoload", daemon=True)
        self._load_thread.start()

    def shutdown(self) -> None:
        try:
            self.core.cancel_all()
        except Exception:  # noqa: BLE001 - shutdown is best effort
            logger.debug("KIE cancel_all failed during shutdown", exc_info=True)
        try:
            self.manager.shutdown()
        except Exception:  # noqa: BLE001
            logger.warning("KIE shutdown failed", exc_info=True)
        if self._load_thread is not None and self._load_thread.is_alive():
            self._load_thread.join(timeout=5.0)

    # -------------------------------------------------------------------- state
    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def ready(self) -> bool:
        return self.manager.loaded

    def artifacts(self) -> dict[str, Any]:
        """What is actually installed, without importing or loading anything."""

        from app.kie.runtime.manifest import MANIFEST_PATH, ManifestError, load_manifest, resolve_model

        result: dict[str, Any] = {
            "manifest_path": str(MANIFEST_PATH),
            "manifest_present": MANIFEST_PATH.is_file(),
            "model_present": False,
            "runtime": {},
            "error": None,
        }
        try:
            manifest = load_manifest()
            result["runtime_tag"] = manifest.tag
            for name, variant in manifest.variants.items():
                result["runtime"][name] = {
                    "path": str(variant.path),
                    "present": (variant.path / "llama.dll").is_file(),
                }
            try:
                resolve_model(manifest)
                result["model_present"] = True
            except ManifestError as exc:
                result["error"] = str(exc)
            result["model"] = {
                "file": manifest.model.filename,
                "quant": manifest.model.quant,
                "size_bytes": manifest.model.size_bytes,
                "sha256": manifest.model.sha256,
                "license": manifest.model.license,
            }
        except ManifestError as exc:
            result["error"] = str(exc)
        return result

    def status(self) -> dict[str, Any]:
        artifacts = self.artifacts()
        manager = self.manager.status()
        return {
            "enabled": self.config.enabled,
            "available": bool(
                self.config.enabled
                and artifacts.get("model_present")
                and any(item.get("present") for item in artifacts.get("runtime", {}).values())
            ),
            "state": manager["state"],
            "ready": manager["ready"],
            "backend": manager["backend"],
            "accelerated": manager["accelerated"],
            "identity": manager["identity"],
            "model": manager["model"],
            "context": manager["context"],
            "memory": manager["memory"],
            "fallback_reason": manager["fallback_reason"],
            "last_error": manager["last_error"] or self._last_load_error,
            "load_seconds": manager["load_seconds"],
            "loading_seconds": manager["loading_seconds"],
            "queue": manager["queue"],
            "runs": self.core.status(),
            "modes": {
                "default": str(Mode.FAST),
                "available": [str(Mode.FAST), str(Mode.REASONING)],
                "thinking_default": False,
            },
            "tools": {"count": len(self.registry), "names": [spec.name for spec in self.registry.specs()]},
            "artifacts": artifacts,
            "config": manager["config"],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def models(self) -> dict[str, Any]:
        artifacts = self.artifacts()
        return {
            "runtime_tag": artifacts.get("runtime_tag"),
            "model": artifacts.get("model"),
            "model_present": artifacts.get("model_present"),
            "runtime": artifacts.get("runtime"),
            "manifest_path": artifacts.get("manifest_path"),
            "error": artifacts.get("error"),
        }

    # ---------------------------------------------------------------- load/unload
    def load(self) -> dict[str, Any]:
        self._require_enabled()
        outcome = self.manager.load()
        payload = outcome.as_dict()
        payload["status"] = self.status()
        return payload

    def unload(self) -> dict[str, Any]:
        self.manager.unload()
        return {"unloaded": True, "state": str(self.manager.state), "status": self.status()}

    # --------------------------------------------------------------------- chat

    def chat(self, request: RunRequest, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_ready()
        validate_prompt_budget(self.core, request)
        result = self.core.run(request, context=context)
        return result.as_dict()

    def chat_from_payload(self, payload: dict[str, Any], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        request = parse_run_request(
            messages=payload.get("messages"),
            message=payload.get("message"),
            mode=payload.get("mode"),
            max_tokens=payload.get("max_tokens"),
            temperature=payload.get("temperature"),
            top_p=payload.get("top_p"),
            thinking=payload.get("thinking"),
        )
        return self.chat(request, context=context)

    def stream_events(
        self,
        request: RunRequest,
        *,
        context: dict[str, Any] | None = None,
    ) -> Iterator[KieEvent]:
        """Yield the run's events as they happen (one worker thread per stream)."""

        self._require_ready()
        validate_prompt_budget(self.core, request)
        events: queue.Queue[Any] = queue.Queue()
        sentinel = object()
        run_id_holder: dict[str, str] = {}

        def emit(event: KieEvent) -> None:
            run_id_holder.setdefault("id", event.run_id)
            events.put(event)

        def worker() -> None:
            try:
                self.core.run(request, context=context, on_event=emit)
            except Exception as exc:  # noqa: BLE001 - the stream reports failures as events
                logger.debug("KIE stream run failed: %s", exc)
                events.put(exc)
            finally:
                events.put(sentinel)

        thread = threading.Thread(target=worker, name="kie-stream", daemon=True)
        thread.start()
        terminal = False
        try:
            while True:
                item = events.get()
                if item is sentinel:
                    break
                if isinstance(item, Exception):
                    code = getattr(item, "code", "KIE_GENERATION_FAILED")
                    message = getattr(item, "message", str(item))
                    yield KieEvent(
                        type=EventType.ERROR,
                        run_id=run_id_holder.get("id", ""),
                        seq=0,
                        data={"code": code, "message": message},
                    )
                    terminal = True
                    break
                if item.type in (EventType.DONE, EventType.ERROR, EventType.CANCELLED):
                    terminal = True
                yield item
        finally:
            run_id = run_id_holder.get("id")
            if not terminal and run_id:
                # The client went away mid-stream: stop burning GPU cycles.
                self.core.cancel(run_id)
            thread.join(timeout=1.0)

    # ------------------------------------------------------------------- control
    def cancel(self, run_id: str) -> dict[str, Any]:
        cancelled = self.core.cancel(run_id)
        if not cancelled:
            existing = self.repository.get_run(run_id) if run_id else None
            if existing is None:
                raise RunNotFoundError(run_id)
            return {"cancelled": False, "run_id": run_id, "reason": "run already finished"}
        return {"cancelled": True, "run_id": run_id}

    def run(self, run_id: str) -> dict[str, Any]:
        record = self.repository.get_run(run_id)
        if record is None:
            raise RunNotFoundError(run_id)
        return record

    def recent_runs(self, limit: int = 20) -> dict[str, Any]:
        return {"runs": self.repository.recent_runs(limit)}

    def tool_specs(self) -> dict[str, Any]:
        return {
            "tools": [spec.as_dict() for spec in self.registry.specs()],
            "note": (
                "Phase B foundation: the registry, schema validation, access levels and audit "
                "trail exist, but no KBMTI tool is registered until Phase C."
            ),
        }

    # ---------------------------------------------------------------- guard rails
    def _require_enabled(self) -> None:
        if not self.config.enabled:
            raise KieDisabledError()

    def _require_ready(self) -> None:
        self._require_enabled()
        if not self.manager.loaded:
            raise ModelNotLoadedError()


__all__ = ["KieService", "parse_run_request"]
