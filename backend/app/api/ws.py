"""WebSocket stream for live market updates."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

ws_router = APIRouter()


@ws_router.websocket("/ws/market")
async def market_stream(websocket: WebSocket) -> None:
    container = websocket.app.state.container
    container.broadcaster.bind_loop(asyncio.get_running_loop())
    await websocket.accept()
    queue = container.broadcaster.subscribe()
    try:
        await websocket.send_json(
            {
                "type": "hello",
                "payload": {
                    "status": container.market.status(),
                    "snapshot": container.market.snapshot(),
                    "forecast": container.forecast.status(),
                    "latest_forecast": container.forecast.latest(),
                    "server_time": datetime.now(UTC).isoformat(timespec="seconds"),
                },
            }
        )
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20.0)
            except TimeoutError:
                await websocket.send_json({"type": "heartbeat", "payload": {"server_time": datetime.now(UTC).isoformat(timespec="seconds")}})
                continue
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - transport level failure
        logger.debug("Market WebSocket closed", exc_info=True)
    finally:
        container.broadcaster.unsubscribe(queue)
