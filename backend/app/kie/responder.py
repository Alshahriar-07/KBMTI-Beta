"""Optional ``ChatResponder`` backed by the embedded model.

This is the *only* bridge into the existing chat path, and it is dark by default
(``KBMTI_KIE_CHAT_RESPONDER=0``): Phase B must not change what ``/api/v1/chat/*``
returns until the UI can show which engine answered. When enabled, a loaded model
answers; anything else — KIE disabled, model unloaded, busy, cancelled, empty output —
falls back to ``RuleBasedResponder`` so chat never degrades to an error.
"""

from __future__ import annotations

import logging
from typing import Any

from app.chat.service import ChatContext, ChatResponder, RuleBasedResponder
from app.kie.service import KieService, parse_run_request

logger = logging.getLogger(__name__)

RESPONDER_ID = "kie-qwen3-4b"


def context_payload(context: ChatContext) -> dict[str, Any]:
    """Project ``ChatContext`` onto the keys the reasoning engine renders."""

    return {
        "symbol": context.symbol,
        "timeframe": context.timeframe,
        "snapshot": context.snapshot,
        "signal": context.signal,
        "patron": context.patron,
        "latest_forecast": context.latest_forecast,
        "data_state": context.data_state,
        "notes": context.reason,
    }


class KieResponder:
    responder_id = RESPONDER_ID

    def __init__(self, kie: KieService, fallback: ChatResponder | None = None) -> None:
        self._kie = kie
        self._fallback: ChatResponder = fallback or RuleBasedResponder()

    def respond(self, question: str, context: ChatContext) -> str:
        if not self._kie.ready:
            return self._fallback.respond(question, context)
        try:
            history = [
                {"role": item["role"], "content": item["content"]}
                for item in context.history[-self._kie.config.history_limit :]
                if item.get("role") in {"user", "assistant"} and item.get("content")
            ]
            request = parse_run_request(
                messages=[*history, {"role": "user", "content": question}],
                mode="fast",
            )
            result = self._kie.chat(request, context=context_payload(context))
        except Exception as exc:  # noqa: BLE001 - the deterministic answer must always exist
            logger.warning("KIE responder fell back to rules: %s", exc)
            return self._fallback.respond(question, context)
        text = str(result.get("text") or "").strip()
        if not text:
            return self._fallback.respond(question, context)
        return text
