"""Phase B API tests for ``/api/v1/kie`` and the opt-in chat responder.

The app is built exactly as production builds it (``create_app``), with a fake engine
injected into ``KieService`` so no model file or GPU is required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chat.service import ChatContext, RuleBasedResponder
from app.core.config import Settings
from app.kie.config import KieConfig
from app.kie.responder import KieResponder
from app.kie.service import KieService
from app.main import create_app
from app.market_data.mt5_gateway import MT5Gateway
from app.persistence.db import Database
from tests.fake_mt5 import FakeMT5
from tests.kie_fakes import EngineFactory


def make_service(tmp_path: Path, factory: EngineFactory, **config) -> KieService:
    db = Database(tmp_path / "kie-api.db")
    db.initialize()
    return KieService(config=KieConfig(**config), db=db, engine_factory=factory)


@pytest.fixture
def api(tmp_path: Path, terminal_exe: Path):
    factory = EngineFactory(text="Hello from the fake engine.")
    service = make_service(tmp_path, factory)
    settings = Settings(
        data_dir=tmp_path,
        default_provider="mt5",
        patron_autoload=False,
        patron_checkpoint=tmp_path / "missing.pt",
        patron_warmup_path=tmp_path / "missing.parquet",
    )
    app = create_app(
        settings=settings,
        gateway=MT5Gateway(module=FakeMT5(), terminal_path=str(terminal_exe)),
        kie=service,
        start_polling=False,
        configure_logs=False,
    )
    with TestClient(app) as client:
        yield client, service, factory


def test_status_reports_disabled_and_enabled_features(api) -> None:
    client, _service, _factory = api
    body = client.get("/api/v1/kie/status").json()
    assert body["state"] == "unloaded"
    assert body["ready"] is False
    assert body["modes"]["default"] == "fast"
    assert body["modes"]["available"] == ["fast", "reasoning"]
    assert body["modes"]["thinking_default"] is False
    assert body["tools"]["count"] == 0
    assert body["config"]["n_ctx"] == 4096
    assert body["config"]["queue_max"] == 3
    assert "artifacts" in body


def test_models_and_tools_endpoints(api) -> None:
    client, _service, _factory = api
    models = client.get("/api/v1/kie/models").json()
    assert "runtime_tag" in models
    assert "model_present" in models
    tools = client.get("/api/v1/kie/tools").json()
    assert tools["tools"] == []
    assert "Phase C" in tools["note"]


def test_chat_requires_a_loaded_model(api) -> None:
    client, _service, _factory = api
    response = client.post("/api/v1/kie/chat", json={"message": "hi"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_NOT_LOADED"
    stream = client.post("/api/v1/kie/chat/stream", json={"message": "hi"})
    assert stream.status_code == 503


def test_chat_validates_input(api) -> None:
    client, _service, _factory = api
    assert client.post("/api/v1/kie/chat", json={}).status_code == 422
    assert client.post("/api/v1/kie/chat", json={"message": "hi", "mode": "turbo"}).status_code == 422
    assert client.post("/api/v1/kie/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/v1/kie/chat", json={"message": "hi", "max_tokens": 5000}).status_code == 422
    assert client.post("/api/v1/kie/cancel", json={"run_id": ""}).status_code == 422


def test_load_chat_and_run_history(api) -> None:
    client, service, _factory = api
    loaded = client.post("/api/v1/kie/load")
    assert loaded.status_code == 200
    payload = loaded.json()
    assert payload["backend"] == "vulkan"
    assert payload["memory"]["offloaded_layers"] == 37
    assert payload["status"]["state"] == "ready"

    response = client.post(
        "/api/v1/kie/chat",
        json={"message": "Summarise the market.", "mode": "fast", "context": {"symbol": "BTC/USDT"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Hello from the fake engine."
    assert body["backend"] == "vulkan"
    assert body["mode"] == "fast"
    assert body["finish"] == "stop"
    assert body["stats"]["completion_tokens"] > 0
    run_id = body["run_id"]

    detail = client.get(f"/api/v1/kie/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "done"

    history = client.get("/api/v1/kie/runs").json()
    assert any(item["id"] == run_id for item in history["runs"])
    assert client.get("/api/v1/kie/runs/does-not-exist").status_code == 404
    assert client.post("/api/v1/kie/cancel", json={"run_id": "does-not-exist"}).status_code == 404


def test_stream_emits_sse_events(api) -> None:
    client, _service, _factory = api
    client.post("/api/v1/kie/load")
    response = client.post("/api/v1/kie/chat/stream", json={"message": "hi"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = []
    for block in response.text.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line.startswith("data: ")]
        if lines:
            events.append(json.loads(lines[0][6:]))
    kinds = [event["type"] for event in events]
    assert kinds[0] == "start"
    assert "token" in kinds
    assert kinds[-1] == "done"
    assert events[-1]["run_id"] == events[0]["run_id"]
    assert "".join(event["text"] for event in events if event["type"] == "token").startswith("Hello")


def test_unload_frees_the_model(api) -> None:
    client, _service, factory = api
    client.post("/api/v1/kie/load")
    response = client.post("/api/v1/kie/unload")
    assert response.status_code == 200
    assert response.json()["state"] == "unloaded"
    assert factory.instances[0].unload_calls >= 1
    assert client.post("/api/v1/kie/chat", json={"message": "hi"}).status_code == 503


def test_disabled_kie_rejects_work(tmp_path: Path, terminal_exe: Path) -> None:
    factory = EngineFactory()
    service = make_service(tmp_path, factory, enabled=False)
    settings = Settings(
        data_dir=tmp_path,
        default_provider="mt5",
        patron_autoload=False,
        patron_checkpoint=tmp_path / "missing.pt",
        patron_warmup_path=tmp_path / "missing.parquet",
    )
    app = create_app(
        settings=settings,
        gateway=MT5Gateway(module=FakeMT5(), terminal_path=str(terminal_exe)),
        kie=service,
        start_polling=False,
        configure_logs=False,
    )
    with TestClient(app) as client:
        status = client.get("/api/v1/kie/status").json()
        assert status["state"] == "disabled"
        assert status["enabled"] is False
        assert client.post("/api/v1/kie/load").json()["error"]["code"] == "KIE_DISABLED"
        assert client.post("/api/v1/kie/chat", json={"message": "hi"}).json()["error"]["code"] == "KIE_DISABLED"


def test_existing_chat_contract_is_unchanged(api) -> None:
    client, _service, _factory = api
    created = client.post("/api/v1/chat/conversations", json={"title": "regression"})
    assert created.status_code == 200
    conversation_id = created.json()["id"]
    sent = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "What is the current market structure?"},
    )
    assert sent.status_code == 200
    body = sent.json()
    assert set(body) == {"user_message", "assistant_message", "context"}
    assert body["assistant_message"]["context"]["responder"] == RuleBasedResponder.responder_id
    assert body["context"]["patron_grounded"] is True
    assert "KIE" not in body["assistant_message"]["content"]


def test_responder_falls_back_to_rules_when_model_is_not_ready() -> None:
    class NotReady:
        ready = False
        config = KieConfig()

    context = ChatContext(symbol=None, timeframe="M15", snapshot={}, signal={}, candles=[], data_state="unavailable")
    responder = KieResponder(NotReady())
    answer = responder.respond("hello", context)
    assert answer == RuleBasedResponder().respond("hello", context)
    assert responder.responder_id == "kie-qwen3-4b"


def test_responder_uses_the_model_when_ready() -> None:
    calls: list = []

    class Ready:
        ready = True
        config = KieConfig()

        def chat(self, request, context=None):
            calls.append((request, context))
            return {"text": "Model answer."}

    context = ChatContext(
        symbol="BTC/USDT",
        timeframe="M15",
        snapshot={"last_close": 60_000.0},
        signal={"label": "NEUTRAL"},
        candles=[],
        data_state="ok",
        history=[{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}],
    )
    answer = KieResponder(Ready()).respond("what now?", context)
    assert answer == "Model answer."
    request, payload = calls[0]
    assert request.messages[-1].content == "what now?"
    assert payload["symbol"] == "BTC/USDT"


def test_responder_falls_back_on_empty_model_output() -> None:
    class Empty:
        ready = True
        config = KieConfig()

        def chat(self, request, context=None):
            return {"text": "   "}

    context = ChatContext(symbol=None, timeframe="M15", snapshot={}, signal={}, candles=[], data_state="unavailable")
    answer = KieResponder(Empty()).respond("hello", context)
    assert "KBMTI" in answer or "unavailable" in answer.lower() or answer.startswith("Here is")
