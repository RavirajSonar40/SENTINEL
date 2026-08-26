"""WebSocket endpoint — live investigation progress updates."""
import json
import asyncio
import logging
from typing import Dict, Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.websocket")

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections for live updates."""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.user_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel: str, user_id: Optional[str] = None):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = set()
        self.active_connections[channel].add(websocket)

        if user_id:
            if user_id not in self.user_connections:
                self.user_connections[user_id] = set()
            self.user_connections[user_id].add(websocket)

    def disconnect(self, websocket: WebSocket, channel: str, user_id: Optional[str] = None):
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)
        if user_id and user_id in self.user_connections:
            self.user_connections[user_id].discard(websocket)

    async def broadcast(self, channel: str, message: Dict):
        if channel in self.active_connections:
            dead = []
            for connection in self.active_connections[channel]:
                try:
                    await connection.send_json(message)
                except Exception:
                    dead.append(connection)
            for d in dead:
                self.active_connections[channel].discard(d)

    async def send_to_user(self, user_id: str, message: Dict):
        if user_id in self.user_connections:
            dead = []
            for connection in self.user_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    dead.append(connection)
            for d in dead:
                self.user_connections[user_id].discard(d)

    async def send_personal(self, websocket: WebSocket, message: Dict):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.debug(f"WebSocket send failed: {e}")


manager = ConnectionManager()


def get_ws_manager() -> ConnectionManager:
    return manager


# --- WebSocket Endpoints ---

@router.websocket("/ws/investigation/{investigation_id}")
async def investigation_ws(websocket: WebSocket, investigation_id: str):
    """WebSocket for live investigation updates."""
    await manager.connect(websocket, f"investigation:{investigation_id}")

    try:
        while True:
            # Keep connection alive, receive pings
            data = await websocket.receive_text()
            if data == "ping":
                await manager.send_personal(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket, f"investigation:{investigation_id}")


@router.websocket("/ws/incidents")
async def incidents_ws(websocket: WebSocket):
    """WebSocket for incident list updates."""
    await manager.connect(websocket, "incidents")

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await manager.send_personal(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket, "incidents")


@router.websocket("/ws/user/{user_id}")
async def user_ws(websocket: WebSocket, user_id: str):
    """WebSocket for user-specific notifications."""
    await manager.connect(websocket, f"user:{user_id}", user_id=user_id)

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await manager.send_personal(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket, f"user:{user_id}", user_id=user_id)


# --- Helper functions for broadcasting ---

async def broadcast_investigation_update(investigation_id: str, update: Dict):
    """Broadcast an investigation update to all connected clients."""
    await manager.broadcast(f"investigation:{investigation_id}", {
        "type": "investigation_update",
        "investigation_id": investigation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **update,
    })


async def broadcast_incident_update(update: Dict):
    """Broadcast an incident update."""
    await manager.broadcast("incidents", {
        "type": "incident_update",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **update,
    })


async def notify_user(user_id: str, notification: Dict):
    """Send a notification to a specific user."""
    await manager.send_to_user(user_id, {
        "type": "notification",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **notification,
    })
