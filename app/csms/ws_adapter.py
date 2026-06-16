from __future__ import annotations

from fastapi import WebSocket


class FastAPIWebSocketAdapter:
  """Adapter so the mobilityhouse/ocpp library can use FastAPI WebSockets."""

  def __init__(self, websocket: WebSocket) -> None:
    self._ws = websocket

  async def recv(self) -> str:
    message = await self._ws.receive()
    if message["type"] == "websocket.disconnect":
      raise ConnectionError("WebSocket disconnected")
    return message.get("text") or ""

  async def send(self, message: str) -> None:
    await self._ws.send_text(message)

  async def close(self) -> None:
    await self._ws.close()
