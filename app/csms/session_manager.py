from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from app.db.repository import session_repository
from app.models.schemas import MeterValue, Session, SessionStatus


class SessionManager:
  def __init__(self) -> None:
    self._sessions: dict[str, Session] = {}

  async def load_from_db(self) -> None:
    sessions = await session_repository.list_all()
    self._sessions = {s.id: s for s in sessions}

  async def create_session(
    self,
    charger_id: str,
    connector_id: int = 1,
    transaction_id: Optional[str] = None,
    ev_id: Optional[str] = None,
  ) -> Session:
    session_id = transaction_id or str(uuid4())
    initial_soc = 20.0
    if ev_id:
      from app.virtual_ev.ev_pool import ev_pool

      ev = ev_pool.get(ev_id)
      if ev:
        initial_soc = ev.soc

    session = Session(
      id=session_id,
      charger_id=charger_id,
      ev_id=ev_id,
      connector_id=connector_id,
      start_time=datetime.utcnow().isoformat() + "Z",
      status=SessionStatus.ACTIVE,
      soc_percent=initial_soc,
    )
    self._sessions[session_id] = session
    await session_repository.create(session)
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

  def remove_sessions_for_charger(self, charger_id: str) -> None:
    to_remove = [
      session_id
      for session_id, session in self._sessions.items()
      if session.charger_id == charger_id
    ]
    for session_id in to_remove:
      del self._sessions[session_id]

  async def add_meter_value(self, session_id: str, meter_value: MeterValue) -> Optional[Session]:
    session = self._sessions.get(session_id)
    if not session:
      return None
    session.meter_values.append(meter_value)
    session.energy_kwh = meter_value.energy_kwh
    session.current_power_kw = meter_value.power_kw
    if meter_value.soc_percent is not None:
      session.soc_percent = meter_value.soc_percent

    updated = await session_repository.add_meter_value(session_id, meter_value)
    if updated:
      self._sessions[session_id] = updated
    return session

  async def end_session(
    self,
    session_id: str,
    status: SessionStatus = SessionStatus.COMPLETED,
  ) -> Optional[Session]:
    session = self._sessions.get(session_id)
    if not session:
      return None
    end_time = datetime.utcnow().isoformat() + "Z"
    session.status = status
    session.end_time = end_time
    session.current_power_kw = 0.0

    updated = await session_repository.end_session(session_id, status, end_time)
    if updated:
      self._sessions[session_id] = updated
    return session


session_manager = SessionManager()
