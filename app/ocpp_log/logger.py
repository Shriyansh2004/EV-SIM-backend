from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import uuid4

from app.models.schemas import MessageDirection, MessageType, OcppMessage

MAX_MESSAGES = 500


class OcppLogger:
  def __init__(self) -> None:
    self._messages: deque[OcppMessage] = deque(maxlen=MAX_MESSAGES)
    self._listeners: list[Callable[[OcppMessage], None]] = []

  def subscribe(self, listener: Callable[[OcppMessage], None]) -> None:
    self._listeners.append(listener)

  def log(
    self,
    charger_id: str,
    direction: MessageDirection,
    message_type: MessageType,
    action: str,
    payload: dict[str, Any],
    correlation_id: Optional[str] = None,
  ) -> OcppMessage:
    msg = OcppMessage(
      id=str(uuid4()),
      timestamp=datetime.utcnow().isoformat() + "Z",
      charger_id=charger_id,
      direction=direction,
      message_type=message_type,
      action=action,
      payload=payload,
      correlation_id=correlation_id,
    )
    self._messages.append(msg)
    for listener in self._listeners:
      listener(msg)
    return msg

  def get_messages(
    self,
    charger_id: Optional[str] = None,
    limit: int = 100,
  ) -> list[OcppMessage]:
    messages = list(self._messages)
    if charger_id:
      messages = [m for m in messages if m.charger_id == charger_id]
    return messages[-limit:]


ocpp_logger = OcppLogger()
