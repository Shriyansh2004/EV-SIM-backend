from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import async_session_factory
from app.db.models import ChargerRecord, MeterValueRecord, SessionRecord
from app.models.schemas import (
  ChargerConfig,
  ChargerStatus,
  MeterValue,
  Session,
  SessionStatus,
)


def _session_to_schema(record: SessionRecord) -> Session:
  return Session(
    id=record.id,
    charger_id=record.charger_id,
    connector_id=record.connector_id,
    start_time=record.start_time,
    end_time=record.end_time,
    energy_kwh=record.energy_kwh,
    current_power_kw=record.current_power_kw,
    soc_percent=record.soc_percent,
    status=SessionStatus(record.status),
    meter_values=[
      MeterValue(
        timestamp=mv.timestamp,
        power_kw=mv.power_kw,
        energy_kwh=mv.energy_kwh,
        soc_percent=mv.soc_percent,
        voltage_v=mv.voltage_v,
        current_a=mv.current_a,
      )
      for mv in record.meter_values
    ],
  )


class ChargerRepository:
  async def create(self, config: ChargerConfig) -> ChargerRecord:
    connector_statuses = [ChargerStatus.AVAILABLE.value] * config.connector_count
    record = ChargerRecord(
      id=config.id,
      max_power_kw=config.max_power_kw,
      connector_count=config.connector_count,
      status=ChargerStatus.AVAILABLE.value,
      connector_statuses=connector_statuses,
    )
    async with async_session_factory() as db:
      db.add(record)
      await db.commit()
      await db.refresh(record)
      return record

  async def delete(self, charger_id: str) -> bool:
    async with async_session_factory() as db:
      record = await db.get(ChargerRecord, charger_id)
      if not record:
        return False
      await db.delete(record)
      await db.commit()
      return True

  async def get(self, charger_id: str) -> ChargerRecord | None:
    async with async_session_factory() as db:
      return await db.get(ChargerRecord, charger_id)

  async def list_all(self) -> list[ChargerRecord]:
    async with async_session_factory() as db:
      result = await db.execute(select(ChargerRecord))
      return list(result.scalars().all())

  async def update_status(
    self,
    charger_id: str,
    status: str,
    last_heartbeat: str | None = None,
    connector_statuses: list[str] | None = None,
  ) -> None:
    async with async_session_factory() as db:
      record = await db.get(ChargerRecord, charger_id)
      if not record:
        return
      record.status = status
      if last_heartbeat is not None:
        record.last_heartbeat = last_heartbeat
      if connector_statuses is not None:
        record.connector_statuses = connector_statuses
      await db.commit()


class SessionRepository:
  async def create(self, session: Session) -> SessionRecord:
    record = SessionRecord(
      id=session.id,
      charger_id=session.charger_id,
      connector_id=session.connector_id,
      start_time=session.start_time,
      end_time=session.end_time,
      energy_kwh=session.energy_kwh,
      current_power_kw=session.current_power_kw,
      soc_percent=session.soc_percent,
      status=session.status.value,
    )
    async with async_session_factory() as db:
      db.add(record)
      await db.commit()
      await db.refresh(record)
      return record

  async def get(self, session_id: str) -> Session | None:
    async with async_session_factory() as db:
      record = await self._get_with_meter_values(db, session_id)
      return _session_to_schema(record) if record else None

  async def list_all(self) -> list[Session]:
    async with async_session_factory() as db:
      result = await db.execute(
        select(SessionRecord)
        .options(selectinload(SessionRecord.meter_values))
        .order_by(SessionRecord.start_time.desc())
      )
      return [_session_to_schema(r) for r in result.scalars().all()]

  async def add_meter_value(self, session_id: str, meter_value: MeterValue) -> Session | None:
    async with async_session_factory() as db:
      record = await self._get_with_meter_values(db, session_id)
      if not record:
        return None

      mv_record = MeterValueRecord(
        session_id=session_id,
        timestamp=meter_value.timestamp,
        power_kw=meter_value.power_kw,
        energy_kwh=meter_value.energy_kwh,
        soc_percent=meter_value.soc_percent,
        voltage_v=meter_value.voltage_v,
        current_a=meter_value.current_a,
      )
      record.meter_values.append(mv_record)
      record.energy_kwh = meter_value.energy_kwh
      record.current_power_kw = meter_value.power_kw
      if meter_value.soc_percent is not None:
        record.soc_percent = meter_value.soc_percent

      await db.commit()
      await db.refresh(record, ["meter_values"])
      return _session_to_schema(record)

  async def end_session(
    self,
    session_id: str,
    status: SessionStatus = SessionStatus.COMPLETED,
    end_time: str | None = None,
  ) -> Session | None:
    async with async_session_factory() as db:
      record = await self._get_with_meter_values(db, session_id)
      if not record:
        return None

      record.status = status.value
      record.end_time = end_time
      record.current_power_kw = 0.0

      await db.commit()
      await db.refresh(record, ["meter_values"])
      return _session_to_schema(record)

  async def _get_with_meter_values(
    self,
    db: AsyncSession,
    session_id: str,
  ) -> SessionRecord | None:
    result = await db.execute(
      select(SessionRecord)
      .options(selectinload(SessionRecord.meter_values))
      .where(SessionRecord.id == session_id)
    )
    return result.scalar_one_or_none()


charger_repository = ChargerRepository()
session_repository = SessionRepository()
