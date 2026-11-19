"""Phase B core tests: lifecycle, budget, single flight, cancellation, planning, tools.

Everything runs against ``tests.kie_fakes.FakeEngine`` — no DLL, no model file, no GPU —
so the suite stays fast and deterministic. The real runtime has its own smoke test.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from app.kie.config import KieConfig
from app.kie.contracts import Access, Mode, RunRequest, ToolCall, ToolSpec, messages_from_dicts
from app.kie.core import StreamFilter, validate_prompt_budget
from app.kie.errors import (
    KieBusyError,
    KieDisabledError,
    KieValidationError,
    ModelLoadFailedError,
    ModelNotLoadedError,
    PromptTooLongError,
    ToolArgumentsError,
)
from app.kie.model_manager import ModelManager, parse_buffers, parse_offloaded_layers
from app.kie.planner import Planner
from app.kie.service import KieService, parse_run_request
from app.kie.tools.engine import ToolEngine
from app.kie.tools.registry import ToolRegistry, validate_arguments
from app.kie.workflow import WorkflowController
from app.persistence.db import Database
from tests.kie_fakes import EngineFactory


def make_config(**overrides) -> KieConfig:
    return KieConfig(**overrides)


@pytest.fixture
def factory() -> EngineFactory:
    return EngineFactory(chunk_delay=0.0)


def loaded_manager(config: KieConfig, factory: EngineFactory) -> ModelManager:
    manager = ModelManager(config, engine_factory=factory)
    manager.load()
    return manager


def service_for(tmp_path: Path, config: KieConfig, factory: EngineFactory) -> KieService:
    db = Database(tmp_path / "kie.db")
    db.initialize()
    return KieService(config=config, db=db, engine_factory=factory)


# --------------------------------------------------------------------- parsing


def test_buffer_parsing_separates_vram_from_host_memory() -> None:
    lines = [
        "load_tensors:      Vulkan0 model buffer size =  2375.91 MiB",
        "load_tensors:   CPU_Mapped model buffer size =   304.28 MiB",
        "llama_kv_cache:    Vulkan0 KV buffer size =   576.00 MiB",
        "sched_reserve:    Vulkan0 compute buffer size =   324.77 MiB",
        "sched_reserve: Vulkan_Host compute buffer size =    28.02 MiB",
        "llama_context: Vulkan_Host  output buffer size =     0.58 MiB",
    ]
    buffers = parse_buffers(lines)
    assert buffers.vram_model_mb == pytest.approx(2375.91)
    assert buffers.vram_kv_mb == pytest.approx(576.0)
    assert buffers.vram_total_mb == pytest.approx(3276.68, abs=0.01)
    assert buffers.ram_total_mb == pytest.approx(332.30, abs=0.01)


def test_offload_parser_reads_layer_counts() -> None:
    assert parse_offloaded_layers(["load_tensors: offloaded 37/37 layers to GPU"]) == (37, 37)
    assert parse_offloaded_layers(["load_tensors: offloaded 0/37 layers to GPU"]) == (0, 37)
    assert parse_offloaded_layers(["nothing here"]) == (0, 37)


# -------------------------------------------------------------------- lifecycle


def test_load_reports_measured_budget(factory: EngineFactory) -> None:
    config = make_config(vram_budget_mb=4096)
    manager = loaded_manager(config, factory)
    status = manager.status()
    assert status["state"] == "ready"
    assert status["backend"] == "vulkan"
    assert status["accelerated"] is True
    memory = status["memory"]
    assert memory["offloaded_layers"] == 37
    assert memory["measured_mb"] == pytest.approx(64.86 * 37 + 576 + 325, abs=0.1)
    assert memory["within_budget"] is True
    assert memory["residual_mb"] == pytest.approx(config.vulkan_residual_mb)
    assert status["queue"]["max_queue"] == config.queue_max


def test_unload_returns_to_unloaded(factory: EngineFactory) -> None:
    manager = loaded_manager(make_config(), factory)
    manager.unload()
    assert manager.state == "unloaded"
    assert manager.loaded is False
    assert manager.status()["backend"] is None
    with pytest.raises(ModelNotLoadedError):
        manager.generate(messages=[])


def test_load_is_idempotent(factory: EngineFactory) -> None:
    manager = loaded_manager(make_config(), factory)
    manager.load()
    assert len(factory.instances) == 1


def test_disabled_manager_refuses_to_load() -> None:
    manager = ModelManager(make_config(enabled=False), engine_factory=EngineFactory())
    assert manager.state == "disabled"
    with pytest.raises(KieDisabledError):
        manager.load()


def test_cpu_fallback_when_vulkan_fails(factory: EngineFactory) -> None:
    factory.fail("vulkan", "no Vulkan device")
    manager = loaded_manager(make_config(), factory)
    status = manager.status()
    assert status["backend"] == "cpu"
    assert status["accelerated"] is False
    assert "no Vulkan device" in (status["fallback_reason"] or "")
    assert [call[0] for call in factory.calls] == ["vulkan", "cpu"]
    assert factory.calls[1][1] == 0


def test_gpu_load_without_device_is_rejected(factory: EngineFactory) -> None:
    factory.kwargs["gpu_present"] = False
    manager = loaded_manager(make_config(), factory)
    assert manager.status()["backend"] == "cpu"
    assert manager.status()["fallback_reason"]


def test_vulkan_backend_identity(factory: EngineFactory) -> None:
    manager = loaded_manager(make_config(), factory)
    identity = manager.status()["identity"]
    assert identity["runtime_tag"] == "b12503"
    assert identity["gpu_offload"] is True
    assert identity["devices"] == ["fake-vulkan-0"]


def test_cpu_backend_reports_no_acceleration(factory: EngineFactory) -> None:
    factory.fail("vulkan")
    manager = loaded_manager(make_config(), factory)
    identity = manager.status()["identity"]
    assert identity["gpu_offload"] is False
    assert manager.status()["accelerated"] is False


# ---------------------------------------------------------------------- budget


def test_over_budget_retries_with_fewer_layers(factory: EngineFactory) -> None:
    manager = loaded_manager(make_config(vram_budget_mb=3000), factory)
    memory = manager.status()["memory"]
    assert len(factory.calls) == 2
    assert factory.calls[0][1] == 99
    assert factory.calls[1][1] < 37
    assert memory["offloaded_layers"] == factory.calls[1][1]
    assert memory["measured_mb"] <= 3000
    assert memory["within_budget"] is True


def test_budget_failure_unloads_and_reports(factory: EngineFactory) -> None:
    config = make_config(vram_budget_mb=1000, ram_budget_mb=1000)
    factory.kwargs["kv_mb"] = 1200.0  # the KV cache alone does not fit either budget
    manager = ModelManager(config, engine_factory=factory)
    with pytest.raises(ModelLoadFailedError) as excinfo:
        manager.load()
    attempts = excinfo.value.details["attempts"]
    assert {item["backend"] for item in attempts} == {"vulkan", "cpu"}
    assert manager.state == "error"
    assert all(engine.unload_calls >= 1 for engine in factory.instances)


def test_kv_cache_overflow_falls_back_to_cpu_with_reason(factory: EngineFactory) -> None:
    # GPU budget alone is too small for the KV cache; the CPU build still works (RAM budget),
    # so KIE stays usable and reports why it is not accelerated.
    config = make_config(vram_budget_mb=1000)
    factory.kwargs["kv_mb"] = 1200.0
    manager = ModelManager(config, engine_factory=factory)
    manager.load()
    status = manager.status()
    assert status["backend"] == "cpu"
    assert "KV" in (status["fallback_reason"] or "")
    assert len(factory.instances) == 2
    assert factory.instances[0].unload_calls >= 1


# ---------------------------------------------------------------- single flight


def test_single_flight_serialises_generations(tmp_path: Path) -> None:
    factory = EngineFactory(text="word " * 80, chunk_delay=0.002)
    service = service_for(tmp_path, make_config(), factory)
    service.load()
    errors: list[Exception] = []

    def run() -> None:
        try:
            service.chat(parse_run_request(message="hello"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    engine = factory.instances[0]
    assert engine.max_concurrent == 1
    assert service.manager.queue["served"] >= 3


def test_full_queue_is_rejected(tmp_path: Path) -> None:
    gate = threading.Event()
    factory = EngineFactory(text="a b c d e f", gate=gate)
    service = service_for(tmp_path, make_config(queue_max=0, queue_wait_seconds=0.1), factory)
    service.load()

    worker = threading.Thread(target=lambda: service.chat(parse_run_request(message="first")))
    worker.start()
    time.sleep(0.2)
    with pytest.raises(KieBusyError) as excinfo:
        service.chat(parse_run_request(message="second"))
    assert excinfo.value.status_code == 429
    gate.set()
    worker.join(timeout=10)
    assert not worker.is_alive()


# ------------------------------------------------------------------------- core


def test_run_emits_events_and_persists(tmp_path: Path) -> None:
    factory = EngineFactory(text="A short fake answer.")
    service = service_for(tmp_path, make_config(), factory)
    service.load()
    events = []
    request = parse_run_request(message="what is up", mode="fast")
    result = service.core.run(request, context={"symbol": "BTC/USDT", "timeframe": "M15"}, on_event=events.append)

    kinds = [str(event.type) for event in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "done"
    assert "token" in kinds
    assert result.text == "A short fake answer."
    assert result.backend == "vulkan"
    assert result.stats.completion_tokens > 0

    stored = service.repository.get_run(result.run_id)
    assert stored is not None
    assert stored["status"] == "done"
    assert stored["backend"] == "vulkan"
    assert stored["answer_chars"] == len(result.text)
    assert stored["tool_calls"] == []


def test_fast_mode_strips_empty_thinking_block(tmp_path: Path) -> None:
    factory = EngineFactory(text=" thinking\n\n</think>\n\nThe actual answer.")
    service = service_for(tmp_path, make_config(), factory)
    service.load()
    result = service.chat(parse_run_request(message="hi"))
    assert result["text"] == "The actual answer."
    assert " thinking" not in result["text"]


def test_reasoning_mode_separates_thinking_events(tmp_path: Path) -> None:
    factory = EngineFactory(text=" thinking\nBecause of X.\n</think>\nAnswer body.")
    service = service_for(tmp_path, make_config(), factory)
    service.load()
    events = []
    service.core.run(
        parse_run_request(message="why", mode="reasoning"),
        on_event=events.append,
    )
    thinking = [event.data["text"] for event in events if str(event.type) == "thinking"]
    tokens = "".join(event.data["text"] for event in events if str(event.type) == "token")
    assert "Because of X." in "".join(thinking)
    assert tokens.strip() == "Answer body."


def test_cancel_stops_a_running_generation(tmp_path: Path) -> None:
    factory = EngineFactory(text="word " * 400, chunk_delay=0.01)
    service = service_for(tmp_path, make_config(), factory)
    service.load()
    seen: list = []
    result_box: dict = {}

    def run() -> None:
        result_box["result"] = service.core.run(
            parse_run_request(message="long one"),
            on_event=lambda event: seen.append(event),
        )

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 5
    run_id = None
    while time.monotonic() < deadline and run_id is None:
        run_id = next((event.run_id for event in seen if str(event.type) == "token"), None)
        time.sleep(0.01)
    assert run_id is not None
    assert service.cancel(run_id)["cancelled"] is True
    worker.join(timeout=10)
    result = result_box["result"]
    assert result.cancelled is True
    assert result.finish == "cancelled"
    stored = service.repository.get_run(run_id)
    assert stored is not None and stored["status"] == "cancelled"
    assert service.cancel(run_id)["cancelled"] is False


def test_wall_clock_timeout_is_reported_separately(tmp_path: Path) -> None:
    factory = EngineFactory(text="word " * 400, chunk_delay=0.02)
    service = service_for(tmp_path, make_config(generation_timeout_seconds=0.05), factory)
    service.load()
    result = service.chat(parse_run_request(message="slow"))
    assert result["cancelled"] is True
    assert result["finish"] == "timeout"


def test_prompt_budget_guard(tmp_path: Path) -> None:
    factory = EngineFactory()
    service = service_for(tmp_path, make_config(n_ctx=1024, hard_max_tokens=256), factory)
    service.load()
    request = RunRequest(messages=messages_from_dicts([{"role": "user", "content": "x" * 4000}]))
    with pytest.raises(PromptTooLongError):
        validate_prompt_budget(service.core, request)


def test_run_not_loaded_raises(tmp_path: Path) -> None:
    service = service_for(tmp_path, make_config(), EngineFactory())
    with pytest.raises(ModelNotLoadedError):
        service.chat(parse_run_request(message="hi"))


# --------------------------------------------------------------------- workflow


def _step_plan(*steps):
    from app.kie.contracts import Plan, PlanStep

    return Plan(goal="test", steps=tuple(PlanStep(i, kind, f"step {i}") for i, kind in enumerate(steps)), mode=Mode.FAST)


def test_workflow_loop_guard_aborts_duplicate_steps() -> None:
    workflow = WorkflowController()
    from app.kie.contracts import Plan, PlanStep

    plan = Plan(goal="loop", steps=(PlanStep(0, "answer", "same"), PlanStep(1, "answer", "same")), mode=Mode.FAST)
    result = workflow.run(plan, lambda step: "ok")
    assert result.ok is False
    assert "loop guard" in (result.aborted_reason or "")


def test_workflow_retries_a_failing_step() -> None:
    workflow = WorkflowController(max_attempts=2)
    attempts = {"count": 0}

    def executor(step):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("transient")
        return "recovered"

    result = workflow.run(_step_plan("answer"), executor)
    assert result.ok is True
    assert result.last_output == "recovered"
    assert result.outcomes[0].attempts == 2


def test_workflow_rejects_oversized_plan() -> None:
    from app.kie.contracts import Plan, PlanStep

    plan = Plan(goal="too big", steps=tuple(PlanStep(i, "answer", f"s{i}") for i in range(3)), mode=Mode.FAST, max_steps=2)
    result = WorkflowController().run(plan, lambda step: "ok")
    assert result.ok is False
    assert "budget" in (result.aborted_reason or "")


def test_planner_is_single_answer_step() -> None:
    plan = Planner(make_config()).plan("do something", mode=Mode.FAST)
    assert len(plan.steps) == 1
    assert plan.steps[0].kind == "answer"
    assert plan.max_steps >= 1


# ------------------------------------------------------------------------ tools


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="test.status",
            description="Return a fixed status.",
            parameters={
                "type": "object",
                "properties": {"depth": {"type": "integer", "minimum": 1, "maximum": 5}},
                "required": [],
                "additionalProperties": False,
            },
        ),
        lambda args: {"depth": args.get("depth", 1), "ok": True},
    )
    registry.register(
        ToolSpec(name="test.write", description="Pretend to write.", parameters={"type": "object", "properties": {}}, access=Access.WRITE),
        lambda args: "written",
    )
    registry.register(
        ToolSpec(name="test.slow", description="Sleep.", parameters={"type": "object", "properties": {}}, timeout_s=0.05),
        lambda args: time.sleep(0.5),
    )
    return registry


def test_registry_validates_arguments() -> None:
    schema = _registry().get("test.status").parameters
    assert validate_arguments(schema, {}) == []
    assert validate_arguments(schema, {"depth": 3}) == []
    assert "unexpected property" in validate_arguments(schema, {"other": 1})[0]
    assert "must be integer" in validate_arguments(schema, {"depth": "3"})[0]
    assert "must be <= 5" in validate_arguments(schema, {"depth": 9})[0]
    assert "not a boolean" in validate_arguments(schema, {"depth": True})[0]


def test_registry_rejects_non_object_schema() -> None:
    registry = ToolRegistry()
    with pytest.raises(ValueError):
        registry.register(ToolSpec(name="bad.name", description="x", parameters={"type": "array"}), lambda args: None)
    with pytest.raises(ValueError):
        registry.register(ToolSpec(name="notnamespaced", description="x", parameters={"type": "object"}), lambda args: None)


def test_engine_executes_and_truncates() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="test.big", description="Big payload.", parameters={"type": "object", "properties": {}}, max_result_chars=20),
        lambda args: "x" * 100,
    )
    engine = ToolEngine(registry)
    result = engine.execute(ToolCall(name="test.big", arguments={}, call_id="1"))
    assert result.ok is True
    assert result.truncated is True
    assert len(result.content) == 20
    assert result.content.endswith("...")


def test_engine_blocks_write_without_confirmation() -> None:
    engine = ToolEngine(_registry())
    denied = engine.execute(ToolCall(name="test.write", arguments={}, call_id="1"))
    assert denied.ok is False
    assert "confirmation" in (denied.error or "")
    allowed = engine.execute(ToolCall(name="test.write", arguments={}, call_id="2"), confirmed=True)
    assert allowed.ok is True


def test_engine_times_out_and_reports_failure() -> None:
    engine = ToolEngine(_registry())
    timed_out = engine.execute(ToolCall(name="test.slow", arguments={}, call_id="1"))
    assert timed_out.ok is False
    assert "timeout" in (timed_out.error or "")
    bad_args = engine.execute(ToolCall(name="test.status", arguments={"depth": 99}, call_id="2"))
    assert bad_args.ok is False
    assert bad_args.error


def test_registry_rejects_unknown_tool() -> None:
    engine = ToolEngine(_registry())
    result = engine.execute(ToolCall(name="shell.run", arguments={}, call_id="1"))
    assert result.ok is False
    assert "Unknown tool" in (result.error or "")


def test_engine_validation_error_type_is_imported() -> None:
    # Guard against silently losing the structured error type.
    assert issubclass(ToolArgumentsError, Exception)


# --------------------------------------------------------------- request parsing


def test_parse_run_request_validation() -> None:
    with pytest.raises(KieValidationError):
        parse_run_request()
    with pytest.raises(KieValidationError):
        parse_run_request(messages=[{"role": "system", "content": "only system"}])
    with pytest.raises(KieValidationError):
        parse_run_request(message="hi", mode="turbo")
    with pytest.raises(KieValidationError):
        parse_run_request(message="x" * 4001)
    parsed = parse_run_request(message="hi", mode="reasoning")
    assert parsed.mode is Mode.REASONING
    assert parsed.last_user_text == "hi"


def test_stream_filter_modes() -> None:
    fast = StreamFilter(Mode.FAST)
    for piece in (" <thi", "nk>\n\n", "</thi", "nk>\n\n", "Hello"):
        fast.feed(piece)
    fast.flush()
    assert fast.answer.strip() == "Hello"
    assert fast.thinking == ""

    reasoning = StreamFilter(Mode.REASONING)
    output = reasoning.feed("<thi") + reasoning.feed("nk>\nPlan.\n</thi") + reasoning.feed("nk>\nDone")
    output += reasoning.flush()
    assert reasoning.thinking == "Plan."
    assert reasoning.answer.strip() == "Done"
    assert any(str(kind) == "thinking" for kind, _ in output)


# ------------------------------------------------------------------ availability


def test_autoload_failure_is_recorded_not_raised(tmp_path: Path) -> None:
    factory = EngineFactory(fail_on_load=True)
    service = service_for(tmp_path, make_config(autoload=True), factory)
    service.startup()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and service.manager.state != "error":
        time.sleep(0.02)
    assert service.manager.state == "error"
    assert service.status()["enabled"] is True
    service.shutdown()


def test_service_reports_degraded_without_artifacts(tmp_path: Path, monkeypatch) -> None:
    from app.kie.runtime import manifest as manifest_module

    monkeypatch.setattr(manifest_module, "MANIFEST_PATH", tmp_path / "missing-manifest.json")
    service = service_for(tmp_path, make_config(), EngineFactory())
    status = service.status()
    assert status["available"] is False
    assert status["artifacts"]["manifest_present"] is False
    assert "manifest not found" in (status["artifacts"]["error"] or "")
