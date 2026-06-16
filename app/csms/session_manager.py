from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from app.models.schemas import MeterValue, Session, SessionStatus


class SessionManager:
  def __init__(self) -> None:
    self._sessions: dict[str, Session] = {}

  def create_session(
    self,
    charger_id: str,
    connector_id: int = 1,
    transaction_id: Optional[str] = None,
  ) -> Session:
    session_id = transaction_id or str(uuid4())
    session = Session(
      id=session_id,
      charger_id=charger_id,
      connector_id=connector_id,
      start_time=datetime.utcnow().isoformat() + "Z",
      status=SessionStatus.ACTIVE,
      soc_percent=20.0,
    )
    self._sessions[session_id] = session
    return session

  def get_session(self, session_id: str) -> Optional[Session]:
    return self._sessions.get(session_id)

  def get_active_session(self, charger_id: str) -> Optional[Session]:
    for session in self._sessions.values():
      if session.charger_id == charger_id and session.status == SessionStatus.ACTIVE:
        return session
    return None

  def list_sessions(self) -> list[Session]:
    return sorted(
      self._sessions.values(),
      key=lambda s: s.start_time,
      reverse=True,
    )

  def add_meter_value(self, session_id: str, meter_value: MeterValue) -> Optional[Session]:
    session = self._sessions.get(session_id)
    if not session:
      return None
    session.meter_values.append(meter_value)
    session.energy_kwh = meter_value.energy_kwh
    session.current_power_kw = meter_value.power_kw
    if meter_value.soc_percent is not None:
      session.soc_percent = meter_value.soc_percent
    return session

  def end_session(
    self,
    session_id: str,
    status: SessionStatus = SessionStatus.COMPLETED,
  ) -> Optional[Session]:
    session = self._sessions.get(session_id)
    if not session:
      return None
    session.status = status
    session.end_time = datetime.utcnow().isoformat() + "Z"
    session.current_power_kw = 0.0
    return session


session_manager = SessionManager()
