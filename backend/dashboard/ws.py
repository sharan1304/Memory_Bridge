"""WebSocket broadcasting for the dashboard's Live Feed panel."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import mcp_server
from schema import SessionEvent

router = APIRouter(prefix="/dashboard")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, event: SessionEvent) -> None:
        payload = event.model_dump(mode="json")
        dead = []
        for connection in list(self._connections):
            try:
                await connection.send_json(payload)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)


manager = ConnectionManager()


def _on_event(event: SessionEvent) -> None:
    asyncio.create_task(manager.broadcast(event))


mcp_server.set_broadcast_hook(_on_event)


@router.websocket("/ws")
async def live_feed(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
