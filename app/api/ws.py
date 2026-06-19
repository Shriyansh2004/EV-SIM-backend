from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

router = APIRouter()
_connections: set[WebSocket] = set()


async def broadcast(event_type: str, data: dict[str, Any]) -> None:
  message = json.dumps({"type": event_type, "data": data})
  dead: set[WebSocket] = set()
  for ws in list(_connections):
    try:
      await ws.send_text(message)
    except Exception:
      dead.add(ws)
  for ws in dead:
    _connections.discard(ws)


def setup_broadcast_listeners() -> None:
  from app.csms.csms_handler import csms_registry
  from app.virtual_charger.charger_pool import charger_pool
  from app.virtual_ev.ev_pool import ev_pool

  def on_event(event_type: str, data: dict[str, Any]) -> None:
    asyncio.create_task(broadcast(event_type, data))

  csms_registry.subscribe(on_event)
  charger_pool.subscribe(on_event)
  ev_pool.subscribe(on_event)


@router.websocket("/ws/updates")
async def websocket_updates(websocket: WebSocket) -> None:
  await websocket.accept()
  _connections.add(websocket)
  try:
    while True:
      await websocket.receive_text()
  except WebSocketDisconnect:
    pass
  finally:
    _connections.discard(websocket)
