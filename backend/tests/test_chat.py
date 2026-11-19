from __future__ import annotations

from fastapi.testclient import TestClient


def select_symbol(client: TestClient) -> None:
    response = client.post("/api/v1/market/symbol", json={"symbol": "BTCUSDm"})
    assert response.status_code == 200


def new_conversation(client: TestClient) -> str:
    response = client.post("/api/v1/chat/conversations", json={})
    assert response.status_code == 200
    return response.json()["id"]


def test_suggestions_present_with_context(client: TestClient) -> None:
    select_symbol(client)
    body = client.get("/api/v1/chat/suggestions").json()
    assert body["context_available"] is True
    assert len(body["suggestions"]) >= 5
    assert all({"id", "label", "prompt"} <= set(item) for item in body["suggestions"])


def test_assistant_uses_real_market_context(client: TestClient) -> None:
    select_symbol(client)
    conversation_id = new_conversation(client)
    response = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "What is the current market structure?"},
    )
    assert response.status_code == 200
    body = response.json()
    answer = body["assistant_message"]["content"]
    assert "BTCUSDm" in answer
    assert "M15" in answer
    assert "deterministic" in answer.lower()
    assert body["assistant_message"]["context"]["ai_available"] is False
    assert body["context"]["symbol"] == "BTCUSDm"

    messages = client.get(f"/api/v1/chat/conversations/{conversation_id}/messages").json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_conversation_title_is_derived_from_first_question(client: TestClient) -> None:
    select_symbol(client)
    conversation_id = new_conversation(client)
    client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "How volatile is the market right now?"},
    )
    conversations = client.get("/api/v1/chat/conversations").json()["conversations"]
    assert conversations[0]["title"].startswith("How volatile")


def test_forecast_question_does_not_invent_predictions(client: TestClient) -> None:
    select_symbol(client)
    conversation_id = new_conversation(client)
    answer = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "Predict the next 6 candles with PATRON."},
    ).json()["assistant_message"]["content"]
    assert "not ready" in answer.lower()
    assert "no model forecast" in answer.lower()
    assert "no forecast value is substituted" in answer.lower()


def test_no_market_context_is_stated_not_fabricated(client: TestClient) -> None:
    conversation_id = new_conversation(client)
    answer = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "What is the market structure?"},
    ).json()["assistant_message"]["content"]
    assert "Market context is unavailable" in answer


def test_clear_and_delete_conversation(client: TestClient) -> None:
    select_symbol(client)
    conversation_id = new_conversation(client)
    client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"content": "Explain the signal."},
    )
    cleared = client.delete(f"/api/v1/chat/conversations/{conversation_id}/messages")
    assert cleared.status_code == 200
    assert client.get(f"/api/v1/chat/conversations/{conversation_id}/messages").json()["messages"] == []

    deleted = client.delete(f"/api/v1/chat/conversations/{conversation_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/chat/conversations/{conversation_id}/messages").status_code == 404


def test_empty_message_is_rejected(client: TestClient) -> None:
    conversation_id = new_conversation(client)
    response = client.post(f"/api/v1/chat/conversations/{conversation_id}/messages", json={"content": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"VALIDATION_ERROR", "VALIDATION"}
