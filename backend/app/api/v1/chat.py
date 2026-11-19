from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import ContainerDep
from app.core.errors import ValidationError
from app.schemas.models import (
    ChatConversationsResponse,
    ChatMessageResponse,
    ChatMessagesResponse,
    ChatSuggestionsResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class SendMessageResponse(BaseModel):
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse
    context: dict


@router.get("/suggestions", response_model=ChatSuggestionsResponse)
def suggestions(container: ContainerDep) -> dict:
    return container.chat.suggestions()


@router.get("/conversations", response_model=ChatConversationsResponse)
def conversations(container: ContainerDep) -> dict:
    return container.chat.list_conversations()


@router.post("/conversations")
def create_conversation(payload: CreateConversationRequest, container: ContainerDep) -> dict:
    return container.chat.create_conversation(payload.title)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, container: ContainerDep) -> dict:
    return container.chat.delete_conversation(conversation_id)


@router.get("/conversations/{conversation_id}/messages", response_model=ChatMessagesResponse)
def conversation_messages(conversation_id: str, container: ContainerDep) -> dict:
    return container.chat.messages(conversation_id)


@router.post("/conversations/{conversation_id}/messages", response_model=SendMessageResponse)
def send_message(conversation_id: str, payload: SendMessageRequest, container: ContainerDep) -> dict:
    content = payload.content.strip()
    if not content:
        raise ValidationError("Message content is required.")
    return container.chat.send_message(conversation_id, content)


@router.delete("/conversations/{conversation_id}/messages")
def clear_messages(conversation_id: str, container: ContainerDep) -> dict:
    return container.chat.clear_messages(conversation_id)
