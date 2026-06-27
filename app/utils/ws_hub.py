"""
WebSocket hub for admin dashboard real-time message updates.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class AdminWsHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        logger.debug("Admin WS connected (%s clients)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        logger.debug("Admin WS disconnected (%s clients)", len(self._connections))

    async def broadcast_message(self, message: dict[str, Any]) -> None:
        if not self._connections:
            return
        payload = {"type": "message.new", "message": message}
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    def schedule_broadcast(self, message: dict[str, Any]) -> None:
        """Fire-and-forget broadcast from sync or async callers."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast_message(message))
        except RuntimeError:
            logger.debug("No event loop — skip WS broadcast")


admin_ws_hub = AdminWsHub()
